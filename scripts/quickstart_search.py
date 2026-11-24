"""Quickstart Б3 of feature 08 (hybrid search): the reranker measurement (FR-014).

Run from the repository root on the Mac, with the search model and the reranker running:

    uv run --env-file .env python scripts/quickstart_search.py --questions <data>/search-set.toml

The questions file is TOML: a list of `[[question]]` tables with `text` and `answer` (the clause
id that holds the answer, `D-0001/5.2`). Each question is searched inside the document of its
answer, twice: without and with the reranker. The result is the place of the answer, the time,
the shares at place 1 and in the first five, and the decision of FR-014.

Printed and saved (next to the questions file, `search-b3-summary-….txt`): numbers and clause
ids only. Never a question, a text, a title or a file name.
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules at first, and `@dataclass` then cannot resolve string annotations.

import argparse
import json
import os
import statistics
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from docreader import embedding, reranker, search
from docreader.config import load_settings
from docreader.db import connect
from docreader.errors import EnvironmentProblem, UserError
from docreader.ids import format_clause_id, format_document_id, parse_clause_id
from docreader.ranking import VariantStats, decide
from docreader.runs import code_version


class QuestionsFileError(Exception):
    """The questions file cannot be used at all (exit 1); never holds a question."""


@dataclass(frozen=True)
class Question:
    number: int
    text: str
    answer: str | None
    error: str | None
    source: str | None = None  # `field:<name>` (make_search_questions.py) or `analyst`


@dataclass(frozen=True)
class Row:
    number: int
    answer: str | None
    place_off: int | None
    place_on: int | None
    seconds_off: float | None
    seconds_on: float | None
    error: str | None
    source: str | None = None


@dataclass
class Summary:
    rows: list[Row]
    code_version: str
    embedding_model: str
    reranker_model: str
    candidates: int
    rrf_k: int
    rerank_candidates: int

    @property
    def _ok(self) -> list[Row]:
        return [r for r in self.rows if r.error is None]

    @property
    def off(self) -> VariantStats:
        return variant_stats(
            [r.place_off for r in self._ok], [r.seconds_off or 0.0 for r in self._ok]
        )

    @property
    def on(self) -> VariantStats:
        return variant_stats(
            [r.place_on for r in self._ok], [r.seconds_on or 0.0 for r in self._ok]
        )

    @property
    def decision(self) -> tuple[str, str]:
        return decide(self.off, self.on)


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
    """One entry of the file; a reading error is kept in the question, not raised."""
    if not isinstance(entry, dict):
        return Question(number, "", None, "нет текста вопроса")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        return Question(number, "", None, "нет текста вопроса")
    if "answer" not in entry:
        return Question(number, text, None, "нет ответа")
    answer = entry["answer"]
    bad = Question(number, text, None, "неверный идентификатор ответа")
    if not isinstance(answer, str):
        return bad
    try:
        seq, key = parse_clause_id(answer)
    except UserError:
        return bad
    source = entry.get("source")
    return Question(
        number,
        text,
        format_clause_id(format_document_id(seq), key),
        None,
        source if isinstance(source, str) and source.strip() else None,
    )


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


def place_of(clause_ids: Sequence[str], answer: str) -> int | None:
    """The place (from 1) of `answer` among `clause_ids`, or None."""
    for place, clause_id in enumerate(clause_ids, start=1):
        if clause_id == answer:
            return place
    return None


def variant_stats(places: Sequence[int | None], seconds: Sequence[float]) -> VariantStats:
    """Shares and times of one variant over the questions without an error."""
    return VariantStats(
        questions=len(places),
        top1=sum(1 for p in places if p == 1),
        top5=sum(1 for p in places if p is not None and p <= 5),
        median_s=statistics.median(seconds) if seconds else 0.0,
        max_s=max(seconds, default=0.0),
    )


def _plural(n: int) -> str:
    if n % 100 in range(11, 15):
        return "вопросов"
    return {1: "вопрос", 2: "вопроса", 3: "вопроса", 4: "вопроса"}.get(n % 10, "вопросов")


def _s(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}".replace(".", ",")


def _place(value: int | None) -> str:
    return "—" if value is None else str(value)


def _share(count: int, total: int) -> str:
    percent = round(100 * count / total) if total else 0
    return f"{count} из {total} ({percent}%)"


def render(summary: Summary) -> list[str]:
    """Russian lines with numbers and clause ids only."""
    rows = summary.rows
    errors = sum(1 for r in rows if r.error is not None)
    off, on = summary.off, summary.on
    lines = [
        f"Б3. Замер реранкера: {len(rows)} {_plural(len(rows))}, ошибок в наборе {errors}",
        f"  версия кода: {summary.code_version}",
        f"  модели: поиск {summary.embedding_model}, реранкер {summary.reranker_model}",
        f"  настройки: кандидатов {summary.candidates}, rrf_k {summary.rrf_k}, "
        f"реранкер читает {summary.rerank_candidates}",
        "",
        "  №   ответ   место без реранкера   место с реранкером   время без / с, с",
    ]
    for r in rows:
        if r.error is not None:
            lines.append(f"  {r.number}   —   ошибка в наборе: {r.error}")
        else:
            lines.append(
                f"  {r.number}   {r.answer}   {_place(r.place_off)}   {_place(r.place_on)}   "
                f"{_s(r.seconds_off)} / {_s(r.seconds_on)}"
            )
    lines += [
        "",
        "                     без реранкера   с реранкером",
        f"на первом месте      {_share(off.top1, off.questions)}   "
        f"{_share(on.top1, on.questions)}",
        f"в первых пяти        {_share(off.top5, off.questions)}   "
        f"{_share(on.top5, on.questions)}",
        f"время: медиана       {_s(off.median_s)} с   {_s(on.median_s)} с",
        f"время: наибольшее    {_s(off.max_s)} с   {_s(on.max_s)} с",
    ]
    by_source = source_lines(summary.rows)
    lines += by_source
    lines.append("")
    verdict, reason = summary.decision
    if verdict == "keep":
        lines.append(f"Решение (FR-014): оставить реранкер включённым — {reason}")
    else:
        lines.append(f"Решение (FR-014): выключить реранкер по умолчанию — {reason}")
    return lines


def _source_group(source: str | None) -> str:
    if source is None:
        return "без пометки"
    if source.startswith("field:"):
        return "поля"
    return "аналитик" if source == "analyst" else source


def source_lines(rows: Sequence[Row]) -> list[str]:
    """The first-five counts of both variants by source of the question (T026), when the
    set holds more than one source; questions with an error are left out."""
    groups: dict[str, list[Row]] = {}
    for r in rows:
        if r.error is None:
            groups.setdefault(_source_group(r.source), []).append(r)
    if len(groups) < 2:
        return []

    def top5(places: list[int | None]) -> int:
        return sum(1 for p in places if p is not None and p <= 5)

    parts = [
        f"{name} {top5([r.place_off for r in group])}/{top5([r.place_on for r in group])}"
        f" из {len(group)}"
        for name, group in sorted(groups.items())
    ]
    return ["в первых пяти по источникам (без / с реранкером): " + ", ".join(parts)]


def to_json(summary: Summary) -> dict[str, Any]:
    verdict, reason = summary.decision
    return {
        "code_version": summary.code_version,
        "models": {"embedding": summary.embedding_model, "reranker": summary.reranker_model},
        "settings": {
            "candidates": summary.candidates,
            "rrf_k": summary.rrf_k,
            "rerank_candidates": summary.rerank_candidates,
        },
        "questions": len(summary.rows),
        "errors": sum(1 for r in summary.rows if r.error is not None),
        "rows": [asdict(r) for r in summary.rows],
        "off": asdict(summary.off),
        "on": asdict(summary.on),
        "decision": {"verdict": verdict, "reason": reason},
    }


def _measure(argv_questions: list[Question]) -> Summary:
    settings = load_settings()
    cfg = settings.search
    embedder = embedding.load_embedder(settings.embedding)
    ranker = reranker.load_reranker(settings.reranker)
    embedding_model = embedder.check().served_model
    reranker_model = ranker.check().served_model
    rows: list[Row] = []
    with connect(settings) as conn:
        for q in argv_questions:
            if q.error is not None or q.answer is None:
                rows.append(Row(q.number, None, None, None, None, None, q.error, q.source))
                continue
            seq, key = parse_clause_id(q.answer)
            doc = format_document_id(seq)
            current = conn.execute(
                "SELECT 1 FROM passage p JOIN document_text t ON t.document_id = p.document_id"
                f" WHERE {search.CURRENT_PASSAGE} AND p.document_id = %s AND p.clause_key = %s",
                (doc, key),
            ).fetchone()
            if current is None:
                rows.append(
                    Row(q.number, q.answer, None, None, None, None, f"нет отрывка {q.answer}",
                        q.source)
                )
                continue
            try:
                off = search.search(
                    conn, settings, q.text, document_id=doc, rerank=False,
                    results=cfg.rerank_candidates, embedder=embedder,
                )
                on = search.search(
                    conn, settings, q.text, document_id=doc, rerank=True,
                    results=cfg.rerank_candidates, embedder=embedder, reranker=ranker,
                )
            except UserError as exc:
                rows.append(Row(q.number, q.answer, None, None, None, None, str(exc), q.source))
                continue
            rows.append(
                Row(
                    q.number,
                    q.answer,
                    place_of([h.clause_id for h in off.hits], q.answer),
                    place_of([h.clause_id for h in on.hits], q.answer),
                    off.seconds,
                    on.seconds,
                    None,
                    q.source,
                )
            )
    return Summary(
        rows=rows,
        code_version=code_version(),
        embedding_model=embedding_model,
        reranker_model=reranker_model,
        candidates=cfg.candidates,
        rrf_k=cfg.rrf_k,
        rerank_candidates=cfg.rerank_candidates,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--questions", required=True, help="the TOML file with the questions")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")
    parser.add_argument("--env-file", help="an env file; without it the environment is used")
    args = parser.parse_args(argv)
    questions_path = Path(args.questions)
    try:
        if args.env_file:
            os.environ.update(read_env(Path(args.env_file)))
        questions = read_questions(questions_path)
        summary = _measure(questions)
    except QuestionsFileError as exc:
        print(exc, file=sys.stderr)
        return 1
    except EnvironmentProblem as exc:
        print(exc, file=sys.stderr)
        return 2
    text = "\n".join(render(summary)) + "\n"
    saved = questions_path.parent / f"search-b3-summary-{datetime.now():%Y%m%d-%H%M%S}.txt"
    saved.write_text(text, encoding="utf-8")
    if args.json:
        print(json.dumps(to_json(summary), ensure_ascii=False, indent=2))
    else:
        print(text, end="")
    print(f"\nСводка сохранена: {saved} (её можно прислать агенту)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
