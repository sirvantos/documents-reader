"""Quickstart Б4 of feature 07 (passages and indexes): the numbers after `index --all`.

Run from the repository root, after `index --all --json` has been saved:

    uv run --env-file .env python scripts/quickstart_passages.py --report index-07-full.json
    uv run --env-file .env python scripts/quickstart_passages.py --report index-07-rerun.json \
        --compare index-07-full.json

What it does (specs/006-passages-and-indexes/quickstart.md, task T023): documents by state of
the indexing stage; passages by part; entries of both indexes; SC-001 (non-whitespace
characters outside every passage or inside two or more); SC-002 (pages and bounds of every
passage against `text_span`); run time (from the saved `index --json`); SC-003 (the counts of
two saved reports compared).

Printed and saved (to `$DOCREADER_DATA_DIR/reports/passages-b4-summary-….txt`): counts, shares
and document ids only. Never a text, a label, a title, a name or a file name.
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules at first, and `@dataclass` then cannot resolve string annotations.

import argparse
import bisect
import json
import os
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from docreader.config import load_settings
from docreader.db import connect
from docreader.extraction_text import shown_end
from docreader.passages import ClauseRecord, PassageSpan, coverage

_PART_LABELS = (
    ("preamble", "преамбула"),
    ("main", "основной текст"),
    ("tail", "реквизиты"),
)


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


def _page_at(spans: Sequence[tuple[int, int]], offset: int) -> int:
    """The page of the last span that starts at or before `offset` (the first one if none)."""
    index = bisect.bisect_right([s[0] for s in spans], offset) - 1
    return spans[max(index, 0)][1]


def pages_of(spans: Sequence[tuple[int, int]], start: int, end: int) -> tuple[int, int]:
    """(first_page, last_page) of the range [start, end): pages of `start` and `end - 1`."""
    return _page_at(spans, start), _page_at(spans, end - 1)


def traceable(
    passage: tuple[int, int, int, int], spans: Sequence[tuple[int, int]], text_len: int
) -> bool:
    """SC-002: the passage lies in the text and its stored pages match `text_span`."""
    start, end, first_page, last_page = passage
    if end > text_len:
        return False
    return (first_page, last_page) == pages_of(spans, start, end)


def seconds_summary(seconds: list[float]) -> dict[str, Any]:
    """Total, median and largest time per document."""
    if not seconds:
        return {"total": 0.0, "median": None, "max": None}
    return {"total": sum(seconds), "median": statistics.median(seconds), "max": max(seconds)}


def compare(report_a: dict[str, Any], report_b: dict[str, Any]) -> list[str]:
    """SC-003: ids of documents whose counts differ, or that are in one report only."""

    def counts(report: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
        return {
            d["document_id"]: (d["passages"], d["word_entries"], d["vectors"])
            for d in report.get("documents", [])
        }

    a, b = counts(report_a), counts(report_b)
    return sorted(doc_id for doc_id in a.keys() | b.keys() if a.get(doc_id) != b.get(doc_id))


@dataclass
class Report:
    states: Counter[str] = field(default_factory=Counter)
    parts: Counter[str] = field(default_factory=Counter)
    word_entries: int = 0
    vectors: int = 0
    uncovered_chars: int = 0
    doubled_chars: int = 0
    coverage_docs: list[str] = field(default_factory=list)
    traceable: int = 0
    passages: int = 0
    truncated: int = 0
    seconds: dict[str, Any] | None = None
    changed: list[str] | None = None


def collect(conn: psycopg.Connection) -> Report:
    """Read the database after `index` and count (no text or label leaves this function)."""
    report = Report()
    report.states = Counter(
        r[0]
        for r in conn.execute("SELECT state FROM stage_status WHERE stage = 'indexing'").fetchall()
    )
    report.parts = Counter(
        {r[0]: r[1] for r in conn.execute("SELECT part, count(*) FROM passage GROUP BY part")}
    )
    row = conn.execute("SELECT count(*) FROM passage").fetchone()
    report.word_entries = report.passages = row[0] if row else 0
    row = conn.execute("SELECT count(*) FROM passage_vector").fetchone()
    report.vectors = row[0] if row else 0
    row = conn.execute("SELECT count(*) FROM passage_vector WHERE truncated").fetchone()
    report.truncated = row[0] if row else 0

    doc_ids = [
        r[0]
        for r in conn.execute("SELECT DISTINCT document_id FROM passage ORDER BY 1").fetchall()
    ]
    for doc_id in doc_ids:
        text_row = conn.execute(
            "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
        ).fetchone()
        text = text_row[0] if text_row else ""
        records = [
            ClauseRecord(r[0], r[1], r[2], r[3], r[4], r[5], r[6])
            for r in conn.execute(
                "SELECT key, kind, depth, start, end_, section_number, section_title "
                "FROM clause WHERE document_id = %s ORDER BY ordinal",
                (doc_id,),
            ).fetchall()
        ]
        tail = next((r for r in records if r.kind == "tail"), None)
        tail_end = shown_end(text, tail.start if tail else None)
        stored = conn.execute(
            "SELECT clause_key, part, start, end_, first_page, last_page "
            "FROM passage WHERE document_id = %s ORDER BY ordinal",
            (doc_id,),
        ).fetchall()
        spans = [PassageSpan(r[0], r[1], r[2], r[3]) for r in stored]
        uncovered, doubled = coverage(text, records, tail_end, spans)
        report.uncovered_chars += uncovered
        report.doubled_chars += doubled
        if uncovered or doubled:
            report.coverage_docs.append(doc_id)
        text_spans = [
            (r[0], r[1])
            for r in conn.execute(
                "SELECT start, page_number FROM text_span WHERE document_id = %s ORDER BY start",
                (doc_id,),
            ).fetchall()
        ]
        for r in stored:
            if text_spans and traceable((r[2], r[3], r[4], r[5]), text_spans, len(text)):
                report.traceable += 1
    return report


def _verdict(ok: bool) -> str:
    return "выполнен" if ok else "не выполнен"


def render(report: Report) -> list[str]:
    """Russian lines with numbers and document ids only."""
    total_docs = sum(report.states.values())
    parts = ", ".join(f"{label} {report.parts.get(key, 0)}" for key, label in _PART_LABELS)
    cover_ok = report.uncovered_chars == 0 and report.doubled_chars == 0
    cover_docs = f" ({', '.join(report.coverage_docs)})" if report.coverage_docs else ""
    lines = [
        "Б4. Нарезка и индексы",
        f"  документов: {total_docs}; готово {report.states.get('done', 0)}, "
        f"требует просмотра {report.states.get('needs_review', 0)}, "
        f"ошибка {report.states.get('failed', 0)}",
        f"  отрывков: {report.passages} ({parts})",
        f"  записей индексов: по словам {report.word_entries}, по смыслу {report.vectors}",
        f"  обрезанных входов модели: {report.truncated}",
    ]
    if report.seconds is not None:
        s = report.seconds
        lines.append(
            f"  время: всего {s['total']:.1f} с"
            + (
                f", медиана {s['median']:.1f} с, наибольшее {s['max']:.1f} с"
                if s["median"] is not None
                else ""
            )
        )
    lines += [
        "",
        f"SC-001: непокрытых знаков {report.uncovered_chars}, в двух отрывках "
        f"{report.doubled_chars} — {_verdict(cover_ok)}{cover_docs}",
        f"SC-002: {report.traceable} из {report.passages} отрывков прослеживаются до "
        f"страниц — {_verdict(report.traceable == report.passages)}",
    ]
    if report.changed is not None:
        if report.changed:
            lines.append(
                f"SC-003: числа изменились у {', '.join(report.changed)} — {_verdict(False)}"
            )
        else:
            lines.append(
                f"SC-003: числа отрывков и записей не изменились — {_verdict(True)}"
            )
    return lines


def _load(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        sys.exit(f"{path}: ожидался объект JSON")
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--report", help="the saved output of `index --json` (run time)")
    parser.add_argument("--compare", help="another saved `index --json` to compare counts with")
    args = parser.parse_args(argv)
    env = read_env(Path(args.env_file))
    if not env.get("DOCREADER_DATA_DIR"):
        sys.exit(f"В {args.env_file} нет DOCREADER_DATA_DIR")
    os.environ.update(env)
    settings = load_settings()

    with connect(settings) as conn:
        report = collect(conn)
    if args.report:
        data = _load(args.report)
        report.seconds = seconds_summary(
            [d["seconds"] for d in data.get("documents", []) if d.get("seconds") is not None]
        )
        if args.compare:
            report.changed = compare(data, _load(args.compare))
    elif args.compare:
        sys.exit("--compare нужен вместе с --report")
    text = "\n".join(render(report)) + "\n"
    print(text, end="")
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary = reports / f"passages-b4-summary-{datetime.now():%Y%m%d-%H%M%S}.txt"
    summary.write_text(text, encoding="utf-8")
    print(f"\nСводка сохранена: {summary} (её можно прислать агенту)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
