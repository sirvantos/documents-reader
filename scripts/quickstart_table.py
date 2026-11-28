"""Quickstart Б4 of feature 10 (table answers): the measurement (SC-001, SC-004).

Run from the repository root on the Mac, with the language model running:

    uv run --env-file .env python scripts/quickstart_table.py [--questions <file>.toml]

Without `--questions` the file is `$DOCREADER_DATA_DIR/questions/table-10.toml` (made by
`scripts/make_table_questions.py`). The file is TOML: a list of `[[question]]` tables with
`text`, `source` (`template` or `analyst`) and exactly one of `expected = {action, field, op,
value, value_to?}` or `expected_outcome = "refused" | "clarify" | "unsupported"`; optional
`documents = ["D-0003", …]` (the expected list of contracts).

Each question is asked as `docreader ask-table` does. The program compares the outcome, then
the query (action, field, comparison and the checked value) and then the contracts of the
answer with `documents` or, without them, with the same program's result of the expected
query over the same table.

Printed and saved (next to the questions file, `table-b4-summary-<date>-<time>.txt`):
numbers, question numbers and ids only — never a question or a value. The full answers go
to `table-b4-<date>-<time>.txt` next to the questions file: they hold contract values, only
the analyst reads that file.
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules at first, and `@dataclass` then cannot resolve string annotations.

import argparse
import dataclasses
import os
import statistics
import sys
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from docreader import llm
from docreader.config import load_settings
from docreader.db import connect
from docreader.errors import EnvironmentProblem, UserError
from docreader.ids import format_document_id, parse_document_id
from docreader.render import render_table_text
from docreader.table_answer import TableAnswer, TableOutcome, ask_table, load_rows
from docreader.table_prompt import TableReply
from docreader.table_query import (
    DocRow,
    NonQuery,
    TableQuery,
    execute,
    match_names,
    resolve_party,
    validate,
)

SOURCES = ("template", "analyst")
EXPECTED_OUTCOMES = ("refused", "clarify", "unsupported")
NAME_FIELDS = ("customer_name_short", "contractor_name_short", "party")
QUERY_KEYS = ("action", "field", "op", "value")


class QuestionsFileError(Exception):
    """The questions file cannot be used (exit 1); never holds a question text."""


@dataclass(frozen=True)
class Question:
    number: int
    text: str
    source: str
    expected: dict[str, str] | None
    expected_outcome: str | None
    documents: tuple[str, ...] | None


@dataclass(frozen=True)
class Row:
    """One question's result; no question text."""

    number: int
    source: str
    verdict: str
    outcome: str
    retried: bool
    seconds: float
    detail: str | None = None  # for a wrong query: action, field and op only (`query_detail`)


@dataclass
class Summary:
    questions: int
    template: int
    right_template: int
    analyst: int
    right_analyst: int
    wrong_query: list[int]
    wrong_outcome: list[int]
    wrong_list: list[int]
    retried: int
    outcomes: dict[str, int]
    median_seconds: float | None
    max_seconds: float | None
    details: dict[int, str] = dataclass_field(default_factory=dict)


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


def _reply(expected: Mapping[str, str]) -> TableReply:
    return TableReply.model_validate({"kind": "query", **expected})


def _question(number: int, entry: Any) -> Question:
    """One entry of the file; a format error names the number only, never the text."""

    def bad(reason: str) -> QuestionsFileError:
        return QuestionsFileError(f"вопрос {number}: {reason}")

    if not isinstance(entry, dict):
        raise bad("нет текста вопроса")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        raise bad("нет текста вопроса (`text`)")
    source = entry.get("source")
    if source not in SOURCES:
        raise bad("`source` — «template» или «analyst»")
    expected = entry.get("expected")
    outcome = entry.get("expected_outcome")
    if (expected is None) == (outcome is None):
        raise bad("нужно одно из двух: `expected` или `expected_outcome`")
    if outcome is not None and outcome not in EXPECTED_OUTCOMES:
        raise bad("`expected_outcome` — «refused», «clarify» или «unsupported»")
    if expected is not None:
        if not isinstance(expected, dict) or not all(
            isinstance(expected.get(k), str) for k in QUERY_KEYS
        ):
            raise bad("`expected` — action, field, op, value (строки)")
        if not all(isinstance(v, str) for v in expected.values()):
            raise bad("`expected` — только строки")
        parsed = validate(_reply(expected), date.today())
        if not isinstance(parsed, TableQuery):
            raise bad("`expected` — не верный запрос")
    documents = entry.get("documents")
    docs: tuple[str, ...] | None = None
    if documents is not None:
        if not isinstance(documents, list) or not all(isinstance(d, str) for d in documents):
            raise bad("`documents` — список идентификаторов договоров")
        try:
            docs = tuple(format_document_id(parse_document_id(d)) for d in documents)
        except UserError:
            raise bad("неверный идентификатор в `documents`") from None
    return Question(number, text, str(source), expected, outcome, docs)


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


def _same_query(expected: TableQuery, got: TableQuery) -> bool:
    if (expected.action, expected.op, expected.value_to) != (got.action, got.op, got.value_to):
        return False
    if expected.field == "party" or got.field == "party" or expected.field in NAME_FIELDS:
        parties = ("party", "customer_name_short", "contractor_name_short")
        if expected.field == "party":
            if got.field not in parties:
                return False
        elif got.field not in (expected.field, "party"):
            return False
        a, b = str(expected.value), str(got.value)
        return match_names(a, b) or match_names(b, a)
    return expected.field == got.field and expected.value == got.value


def judge(question: Question, answer: TableAnswer, rows: Sequence[DocRow], today: date) -> str:
    """The program's verdict: `right`, `wrong_outcome`, `wrong_query` or `wrong_list`."""
    if question.expected_outcome is not None:
        return "right" if answer.outcome.value == question.expected_outcome else "wrong_outcome"
    assert question.expected is not None
    if answer.outcome is not TableOutcome.ANSWERED or answer.result is None:
        return "wrong_outcome"
    expected = validate(_reply(question.expected), today)
    if not isinstance(expected, TableQuery) or not _same_query(expected, answer.result.query):
        return "wrong_query"
    if question.documents is not None:
        wanted = set(question.documents)
    else:
        resolved = resolve_party(expected, rows, False)
        runnable = expected if isinstance(resolved, NonQuery) else resolved
        wanted = {r.row.document_id for r in execute(runnable, rows, False).rows}
    got = {r.row.document_id for r in answer.result.rows}
    return "right" if got == wanted else "wrong_list"


def _shape(q: TableQuery) -> str:
    field_name = f"party→{q.field}" if q.side is not None else q.field
    return f"{q.action} {field_name} {q.op}"


def query_detail(question: Question, answer: TableAnswer, today: date) -> str | None:
    """«ожидалось A F O, модель A F O[; значение другое]» — never a value (principle I)."""
    if question.expected is None or answer.result is None:
        return None
    expected = validate(_reply(question.expected), today)
    if not isinstance(expected, TableQuery):
        return None
    got = answer.result.query
    text = f"ожидалось {_shape(expected)}, модель {_shape(got)}"
    same_shape = (expected.action, expected.op) == (got.action, got.op) and (
        expected.field == got.field or (expected.field == "party" and got.side is not None))
    return text + "; значение другое" if same_shape else text


def summarize(rows: Sequence[Row]) -> Summary:
    times = [r.seconds for r in rows]
    return Summary(
        questions=len(rows),
        template=sum(1 for r in rows if r.source == "template"),
        right_template=sum(1 for r in rows if r.source == "template" and r.verdict == "right"),
        analyst=sum(1 for r in rows if r.source == "analyst"),
        right_analyst=sum(1 for r in rows if r.source == "analyst" and r.verdict == "right"),
        wrong_query=[r.number for r in rows if r.verdict == "wrong_query"],
        wrong_outcome=[r.number for r in rows if r.verdict == "wrong_outcome"],
        wrong_list=[r.number for r in rows if r.verdict == "wrong_list"],
        retried=sum(1 for r in rows if r.retried),
        outcomes=dict(Counter(r.outcome for r in rows)),
        median_seconds=statistics.median(times) if times else None,
        max_seconds=max(times) if times else None,
        details={r.number: r.detail for r in rows if r.verdict == "wrong_query" and r.detail},
    )


def _plural(n: int) -> str:
    if n % 100 in range(11, 15):
        return "вопросов"
    return {1: "вопрос", 2: "вопроса", 3: "вопроса", 4: "вопроса"}.get(n % 10, "вопросов")


def _genitive(n: int) -> str:
    """«вопроса» after 1, 21, … (not 11), else «вопросов»."""
    return "вопроса" if n % 10 == 1 and n % 100 != 11 else "вопросов"


def _s(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}".replace(".", ",")


def _numbers(items: Sequence[int]) -> str:
    return ", ".join(map(str, items)) if items else "нет"


def render(summary: Summary) -> list[str]:
    """Russian lines with numbers only."""
    outcomes = ", ".join(f"{name} {n}" for name, n in summary.outcomes.items()) or "—"
    return [
        f"Б4. Замер табличных ответов: {summary.questions} {_plural(summary.questions)}",
        f"  верно: по шаблонам {summary.right_template} из {summary.template} "
        f"{_genitive(summary.template)}, аналитика {summary.right_analyst} из "
        f"{summary.analyst} {_genitive(summary.analyst)}",
        f"  неверный запрос: {_numbers(summary.wrong_query)}",
        *(f"    {n}: {d}" for n, d in sorted(summary.details.items())),
        f"  неверный исход: {_numbers(summary.wrong_outcome)}",
        f"  неверный список: {_numbers(summary.wrong_list)}",
        f"  исходы: {outcomes}",
        f"  повторов {summary.retried}",
        f"  время: медиана {_s(summary.median_seconds)} с, "
        f"наибольшее {_s(summary.max_seconds)} с",
    ]


def questions_path(arg: str | None, env: Mapping[str, str]) -> Path:
    if arg:
        return Path(arg).expanduser()
    data_dir = env.get("DOCREADER_DATA_DIR", "").strip()
    if data_dir:  # `~` expanded as in config.load_settings
        return Path(data_dir).expanduser() / "questions" / "table-10.toml"
    raise QuestionsFileError("укажите --questions или задайте DOCREADER_DATA_DIR")


def _measure(questions: Sequence[Question]) -> tuple[Summary, list[str]]:
    """Ask every question; returns the summary and the answer blocks (the analyst's file)."""
    settings = load_settings()
    client = llm.load_client(
        dataclasses.replace(
            settings.extraction,
            max_tokens=settings.table.max_tokens,
            max_retries=settings.table.max_retries,
        )
    )
    today = date.today()
    results: list[Row] = []
    blocks: list[str] = []
    with connect(settings) as conn:
        rows = load_rows(conn, settings)
        for q in questions:
            answer = ask_table(conn, settings, q.text, client=client, today=today)
            verdict = judge(q, answer, rows, today)
            detail = query_detail(q, answer, today) if verdict == "wrong_query" else None
            results.append(
                Row(q.number, q.source, verdict, answer.outcome.value, answer.retried,
                    answer.seconds, detail)
            )
            blocks.append(
                f"{q.number}. {q.text}\nпроверка: {verdict}\n"
                f"{render_table_text(answer, settings.table.list_rows)}"
            )
    return summarize(results), blocks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--questions",
        help="the TOML file with the questions (default: in the data folder, see the docstring)",
    )
    parser.add_argument("--env-file", help="an env file; without it the environment is used")
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            os.environ.update(read_env(Path(args.env_file)))
        path = questions_path(args.questions, os.environ)
        questions = read_questions(path)
        summary, blocks = _measure(questions)
    except (QuestionsFileError, UserError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except EnvironmentProblem as exc:
        print(exc, file=sys.stderr)
        return 2
    now = datetime.now()
    stamp = f"{now:%Y%m%d-%H%M}"
    answers_path = path.parent / f"table-b4-{stamp}.txt"
    summary_path = path.parent / f"table-b4-summary-{stamp}.txt"
    answers_path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    text = "\n".join([*render(summary), f"  дата: {now:%Y-%m-%d}"]) + "\n"
    summary_path.write_text(text, encoding="utf-8")
    print(text, end="")
    print(f"\nОтветы для оценки: {answers_path} (только для вас — содержит значения договоров)")
    print(f"Сводка сохранена: {summary_path} (её можно прислать агенту)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
