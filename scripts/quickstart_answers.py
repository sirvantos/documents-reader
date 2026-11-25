"""Quickstart Б4 of feature 09 (text answers): the answer measurement (FR-012, SC-001..SC-003).

Run from the repository root on the Mac, with the answer model, the search model and the
reranker running:

    uv run --env-file .env python scripts/quickstart_answers.py [--questions <file>.toml]

Without `--questions` the file is `$DOCREADER_DATA_DIR/questions/answers-09.toml`.

The questions file is TOML: a list of `[[question]]` tables. Two forms:
- `text`, `document` (the contract the question is asked in, `D-0001`) and `expected`
  (`answer` or `none`: whether the contracts hold an answer);
- `text` and `answer = "D-0015/5.2"` (the feature 08 form): the contract comes from the
  clause, `expected` is `answer`; other keys (`source`) are ignored.
Optional `contains`: a string or a list of strings that the confirmed claims must hold
(not for `expected = "none"`). Each question is asked with `docreader ask --document`.

The program checks each answer: a confirmed claim in the expected clause (or its subclause)
and every `contains` value in the claims; the doubtful ones are listed by number.
The three servers are checked before the first question.

Printed and saved (next to the questions file, `answers-b4-summary-....txt`): numbers and ids
only. Never a question, a `contains` value or a contract text. The full answers go to
`answers-b4-....txt` next to the questions file; only the analyst reads it.
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules at first, and `@dataclass` then cannot resolve string annotations.

import argparse
import dataclasses
import json
import os
import statistics
import sys
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from docreader import answer, embedding, llm, reranker, search, textnorm
from docreader.answer_check import AnswerOutcome
from docreader.answer_prompt import PROMPT_VERSION
from docreader.config import load_settings
from docreader.db import connect
from docreader.errors import EnvironmentProblem, UserError
from docreader.ids import format_clause_id, format_document_id, parse_clause_id, parse_document_id
from docreader.render import render_answer_text
from docreader.runs import code_version

EXPECTED = ("answer", "none")
OUTCOMES = tuple(o.value for o in AnswerOutcome)


class QuestionsFileError(Exception):
    """The questions file cannot be used (exit 1); never holds a question text."""


@dataclass(frozen=True)
class Question:
    number: int
    text: str
    document: str
    expected: str
    answer_clause: str | None = None
    contains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Row:
    """One question's result; no question text (FR-012)."""

    number: int
    document: str
    expected: str
    outcome: str | None
    confirmed: int
    not_found: int
    retried: bool
    seconds: float | None
    error: str | None
    check: str | None = None


@dataclass
class Summary:
    rows: list[Row]
    code_version: str
    llm_model: str
    prompt_version: str
    embedding_model: str
    reranker_model: str
    passages: int
    candidates: int
    rrf_k: int
    rerank_candidates: int
    rechecked: int
    recheck_missing: int


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of an env file (comments and blank lines skipped)."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def _question(number: int, entry: Any) -> Question:
    """One entry of the file; a format error names the number only, never the text."""

    def bad(reason: str) -> QuestionsFileError:
        return QuestionsFileError(f"вопрос {number}: {reason}")

    if not isinstance(entry, dict):
        raise bad("нет текста вопроса")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        raise bad("нет текста вопроса (`text`)")
    answer_clause: str | None = None
    answer_doc: str | None = None
    answer_value = entry.get("answer")
    if answer_value is not None:
        if not isinstance(answer_value, str):
            raise bad("неверный пункт ответа (`answer`)")
        try:
            seq, key = parse_clause_id(answer_value)
        except UserError:
            raise bad("неверный пункт ответа (`answer`)") from None
        answer_doc = format_document_id(seq)
        answer_clause = format_clause_id(answer_doc, key)
    document = entry.get("document")
    if answer_doc is not None and document is None:
        document_id = answer_doc
    else:
        if not isinstance(document, str):
            raise bad("нет договора (`document`)")
        try:
            document_id = format_document_id(parse_document_id(document))
        except UserError:
            raise bad("неверный идентификатор договора (`document`)") from None
        if answer_doc is not None and document_id != answer_doc:
            raise bad("`answer` и `document` — разные договоры")
    expected = entry.get("expected", "answer" if answer_clause is not None else None)
    if expected not in EXPECTED:
        raise bad("`expected` — «answer» или «none»")
    if answer_clause is not None and expected != "answer":
        raise bad("с `answer` пометка `expected` — только «answer»")
    return Question(
        number, text, document_id, str(expected), answer_clause,
        _contains(entry.get("contains"), str(expected), bad),
    )


def _contains(
    value: Any, expected: str, bad: Callable[[str], QuestionsFileError]
) -> tuple[str, ...]:
    if value is None:
        return ()
    if expected == "none":
        raise bad("`contains` не нужен вопросу без ответа")
    items = [value] if isinstance(value, str) else value
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(i, str) and i.strip() for i in items)
    ):
        raise bad("`contains` — непустая строка или список непустых строк")
    return tuple(items)


def read_questions(path: Path) -> list[Question]:
    """The questions of the TOML file, numbered from 1."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuestionsFileError(f"нет файла с вопросами {path}") from exc
    try:
        data = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise QuestionsFileError(f"файл вопросов {path} — не TOML") from exc
    entries = data.get("question")
    if not isinstance(entries, list) or not entries:
        raise QuestionsFileError("в файле нет ни одного вопроса")
    return [_question(i, entry) for i, entry in enumerate(entries, start=1)]


CHECKS = {
    "right": "верно",
    "other_clause": "другой пункт — проверить",
    "no_value": "нет значения — проверить",
    "unchecked": "не проверено — проверить",
    "no_answer": "нет ответа",
    "refused": "отказ",
    "answered_none": "ответ есть — проверить",
}
TO_REVIEW = frozenset({"other_clause", "no_value", "unchecked", "answered_none"})


def judge(question: Question, claims: Sequence[Any]) -> str:
    """The program's verdict on one answer (a code of `CHECKS`); never a final grade."""
    confirmed = [c for c in claims if c.confirmed]
    if question.expected == "none":
        return "answered_none" if confirmed else "refused"
    if not confirmed:
        return "no_answer"
    clause = question.answer_clause
    if clause is None and not question.contains:
        return "unchecked"
    if clause is not None and not any(
        c.clause_id == clause or (c.clause_id or "").startswith(clause + ".")
        for c in confirmed
    ):
        return "other_clause"
    for value in question.contains:
        needle = value.casefold()  # `locate` is case-sensitive; the values are not
        if not any(
            textnorm.locate(c.text.casefold(), needle)
            or textnorm.locate(c.quote.casefold(), needle)
            for c in confirmed
        ):
            return "no_value"
    return "right"


@dataclass(frozen=True)
class ServerState:
    name: str
    model: str | None
    problem: str | None


class ServersDown(Exception):
    """At least one server does not answer; the run stops before the first question."""

    def __init__(self, states: Sequence[ServerState]) -> None:
        super().__init__("серверы моделей не готовы")
        self.states = list(states)


def check_servers(checks: Sequence[tuple[str, Callable[[], str]]]) -> list[ServerState]:
    states: list[ServerState] = []
    for name, check in checks:
        try:
            states.append(ServerState(name, check(), None))
        except EnvironmentProblem as exc:
            states.append(ServerState(name, None, str(exc)))
    return states


def render_servers(states: Sequence[ServerState]) -> list[str]:
    return [
        f"  {s.name}: {s.model}" if s.problem is None else f"  {s.name}: не отвечает — {s.problem}"
        for s in states
    ]


def questions_path(arg: str | None, env: Mapping[str, str]) -> Path:
    if arg:
        return Path(arg).expanduser()
    data_dir = env.get("DOCREADER_DATA_DIR", "").strip()
    if data_dir:  # `~` expanded as in config.load_settings
        return Path(data_dir).expanduser() / "questions" / "answers-09.toml"
    raise QuestionsFileError("укажите --questions или задайте DOCREADER_DATA_DIR")


def totals(rows: Sequence[Row]) -> dict[str, dict[str, int]]:
    """Counts of outcomes by mark; rows with a set error are left out."""
    result = {mark: {outcome: 0 for outcome in OUTCOMES} for mark in EXPECTED}
    for r in rows:
        if r.error is None and r.outcome is not None:
            result[r.expected][r.outcome] += 1
    return result


def _plural(n: int) -> str:
    if n % 100 in range(11, 15):
        return "вопросов"
    return {1: "вопрос", 2: "вопроса", 3: "вопроса", 4: "вопроса"}.get(n % 10, "вопросов")


def _genitive(n: int) -> str:
    """«вопроса» after 1, 21, … (not 11), else «вопросов»."""
    return "вопроса" if n % 10 == 1 and n % 100 != 11 else "вопросов"


def to_review(rows: Sequence[Row]) -> list[int]:
    return [r.number for r in rows if r.check in TO_REVIEW]


def _s(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}".replace(".", ",")


def render(summary: Summary) -> list[str]:
    """Russian lines with numbers and ids only."""
    rows = summary.rows
    errors = sum(1 for r in rows if r.error is not None)
    with_answer = sum(1 for r in rows if r.expected == "answer")
    without = sum(1 for r in rows if r.expected == "none")
    lines = [
        f"Б4. Замер ответов: {len(rows)} {_plural(len(rows))} "
        f"(с ответом {with_answer}, без ответа {without}), ошибок в наборе {errors}",
        f"  версия кода: {summary.code_version}",
        f"  модели: ответ {summary.llm_model} (подсказка {summary.prompt_version}), "
        f"поиск {summary.embedding_model}, реранкер {summary.reranker_model}",
        f"  настройки: отрывков {summary.passages}, кандидатов {summary.candidates}, "
        f"rrf_k {summary.rrf_k}, реранкер читает {summary.rerank_candidates}",
        "",
        "  №   договор   пометка   итог          подтв. / не найд.   повтор   время, с   проверка",
    ]
    for r in rows:
        if r.error is not None:
            lines.append(f"  {r.number}   {r.document}   —   ошибка в наборе: {r.error}")
        else:
            lines.append(
                f"  {r.number}   {r.document}   {r.expected}   {r.outcome}   "
                f"{r.confirmed} / {r.not_found}   {'да' if r.retried else 'нет'}   "
                f"{_s(r.seconds)}   {CHECKS[r.check] if r.check else '—'}"
            )
    by_mark = totals(rows)
    lines += [
        "",
        f"                         с ответом ({sum(by_mark['answer'].values())})   "
        f"без ответа ({sum(by_mark['none'].values())})",
    ]
    for outcome in OUTCOMES:
        lines.append(
            f"  {outcome:<22} {by_mark['answer'][outcome]:<16} {by_mark['none'][outcome]}"
        )
    none_total = sum(by_mark["none"].values())
    refused = by_mark["none"][AnswerOutcome.NOT_FOUND.value]
    percent = round(100 * refused / none_total) if none_total else 0
    lines.append(
        f"  отказов на «none»                       {refused} из {none_total} ({percent}%)"
    )
    rated = [r for r in rows if r.expected == "answer" and r.error is None]
    right = sum(1 for r in rated if r.check == "right")
    right_percent = round(100 * right / len(rated)) if rated else 0
    review = to_review(rows)
    lines += [
        f"  проверка программой: верно {right} из {len(rated)} {_genitive(len(rated))} "
        f"с ответом ({right_percent}%)",
        f"  проверить вручную: {', '.join(map(str, review)) if review else 'нет'}",
    ]
    times = [r.seconds for r in rows if r.error is None and r.seconds is not None]
    median = _s(statistics.median(times)) if times else "—"
    longest = _s(max(times)) if times else "—"
    lines += [
        "",
        f"  время: медиана {median} с, наибольшее {longest} с",
        f"  повторная проверка цитат: проверено {summary.rechecked}, "
        f"не найдено {summary.recheck_missing}",
        f"  повторов запроса: {sum(1 for r in rows if r.error is None and r.retried)}",
    ]
    return lines


def to_json(summary: Summary) -> dict[str, Any]:
    return {
        "code_version": summary.code_version,
        "models": {
            "llm": summary.llm_model,
            "embedding": summary.embedding_model,
            "reranker": summary.reranker_model,
        },
        "prompt_version": summary.prompt_version,
        "settings": {
            "passages": summary.passages,
            "candidates": summary.candidates,
            "rrf_k": summary.rrf_k,
            "rerank_candidates": summary.rerank_candidates,
        },
        "questions": len(summary.rows),
        "errors": sum(1 for r in summary.rows if r.error is not None),
        "rows": [asdict(r) for r in summary.rows],
        "totals": totals(summary.rows),
        "checks": {code: sum(1 for r in summary.rows if r.check == code) for code in CHECKS},
        "to_review": to_review(summary.rows),
        "recheck": {"checked": summary.rechecked, "missing": summary.recheck_missing},
    }


def _recheck(conn: psycopg.Connection, claims: Sequence[Any]) -> tuple[int, int]:
    """Read the text and the passage bounds again and locate each confirmed quote (SC-001)."""
    checked = missing = 0
    for claim in claims:
        if not claim.confirmed or claim.clause_id is None:
            continue
        checked += 1
        seq, key = parse_clause_id(claim.clause_id)
        doc = format_document_id(seq)
        row = conn.execute(
            "SELECT t.text, p.start, p.end_ FROM passage p"
            " JOIN document_text t ON t.document_id = p.document_id"
            f" WHERE {search.CURRENT_PASSAGE} AND p.document_id = %s AND p.clause_key = %s",
            (doc, key),
        ).fetchone()
        if row is None or not textnorm.locate(row[0][row[1] : row[2]], claim.quote):
            missing += 1
    return checked, missing


def _measure(questions: list[Question]) -> tuple[Summary, list[str]]:
    """Ask every question; returns the summary and the answers text blocks (analyst's file)."""
    settings = load_settings()
    client = llm.load_client(
        dataclasses.replace(
            settings.extraction,
            max_tokens=settings.answer.max_tokens,
            max_retries=settings.answer.max_retries,
        )
    )
    embedder = embedding.load_embedder(settings.embedding)
    ranker = reranker.load_reranker(settings.reranker)
    states = check_servers(
        [
            ("языковая модель", client.check),
            ("модель поиска", lambda: embedder.check().served_model),
            ("реранкер", lambda: ranker.check().served_model),
        ]
    )
    if any(s.problem is not None for s in states):
        raise ServersDown(states)
    llm_model, embedding_model, reranker_model = (str(s.model) for s in states)
    rows: list[Row] = []
    blocks: list[str] = []
    rechecked = missing = 0
    code = prompt = ""
    with connect(settings) as conn:
        for q in questions:
            try:
                result = answer.ask(
                    conn, settings, q.text, document_id=q.document,
                    client=client, embedder=embedder, reranker=ranker,
                )
            except UserError as exc:
                rows.append(
                    Row(q.number, q.document, q.expected, None, 0, 0, False, None, str(exc))
                )
                blocks.append(f"{q.number}. {q.text}\nошибка в наборе: {exc}")
                continue
            code = result.provenance.code_version
            prompt = result.provenance.prompt_version
            verdict = judge(q, result.claims)
            rows.append(
                Row(
                    q.number, q.document, q.expected, result.outcome.value,
                    sum(1 for c in result.claims if c.confirmed),
                    result.not_found_final, result.retried, result.seconds, None, verdict,
                )
            )
            note = f"проверка: {CHECKS[verdict]}"
            if q.answer_clause and verdict in ("other_clause", "no_value"):
                note += f" (ожидался пункт {q.answer_clause})"
            blocks.append(f"{q.number}. {q.text}\n{note}\n{render_answer_text(result)}")
            checked, absent = _recheck(conn, result.claims)
            rechecked += checked
            missing += absent
    if not code:
        code, prompt = code_version(), PROMPT_VERSION
    summary = Summary(
        rows=rows,
        code_version=code,
        llm_model=llm_model,
        prompt_version=prompt,
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        passages=settings.answer.passages,
        candidates=settings.search.candidates,
        rrf_k=settings.search.rrf_k,
        rerank_candidates=settings.search.rerank_candidates,
        rechecked=rechecked,
        recheck_missing=missing,
    )
    return summary, blocks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--questions",
        help="the TOML file with the questions (default: in the data folder, see the docstring)",
    )
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--env-file", help="an env file; without it the environment is used")
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            os.environ.update(read_env(Path(args.env_file)))
        path = questions_path(args.questions, os.environ)
        questions = read_questions(path)
        summary, blocks = _measure(questions)
    except QuestionsFileError as exc:
        print(exc, file=sys.stderr)
        return 1
    except ServersDown as exc:
        print("Серверы моделей не готовы, замер не начат:", file=sys.stderr)
        print("\n".join(render_servers(exc.states)), file=sys.stderr)
        return 2
    except EnvironmentProblem as exc:
        print(exc, file=sys.stderr)
        return 2
    stamp = f"{datetime.now():%Y%m%d-%H%M%S}"
    answers_path = path.parent / f"answers-b4-{stamp}.txt"
    summary_path = path.parent / f"answers-b4-summary-{stamp}.txt"
    answers_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    text = "\n".join(render(summary)) + "\n"
    summary_path.write_text(text, encoding="utf-8")
    if args.json:
        print(json.dumps(to_json(summary), ensure_ascii=False, indent=2))
    else:
        print(text, end="")
    print(f"\nОтветы для оценки: {answers_path} (только для вас — содержит текст договоров)")
    print(f"Сводка сохранена: {summary_path} (её можно прислать агенту)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
