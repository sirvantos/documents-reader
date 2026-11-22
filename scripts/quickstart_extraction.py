"""Quickstart Б4–Б5 of feature 05 (field extraction): the numbers after `extract --all`.

Run from the repository root, after `extract --all --json` has been saved:

    uv run --env-file .env python scripts/quickstart_extraction.py
    uv run python scripts/quickstart_extraction.py --env-file .env --report extract-05.json

What it does (specs/005-field-extraction/quickstart.md, task T028):
  Б4  documents by extraction state; per field found / not found / rejected / failed;
      kinds of rejection reasons; run time (from the saved `extract --json`, if given);
      SC-001: every found value is checked again against the current text (the quote is
      at its place, in the shown part, and holds the value) and against the parse (the
      clause of the quote exists and contains it);
  Б5  the ids of the documents for the manual check: all text-layer contracts and seven
      scans at an even step, one of them «требует просмотра» if there is one.

Printed and saved (to `$DOCREADER_DATA_DIR/reports/extraction-b4-summary-….txt`): counts,
shares and document ids only. Never a value, a quote, a name or a file name.
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules, and `@dataclass` then cannot resolve string annotations.

import argparse
import json
import os
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from docreader.config import load_settings
from docreader.db import connect
from docreader.extraction_text import shown_end
from docreader.fields import FIELD_NAMES, PROTOTYPE_FIELDS, Kind, Result
from docreader.values import find_in_quote
from docreader.verify import NO_QUOTE, PARTIES, QUOTE_NOT_FOUND, VALUE_NOT_CONFIRMED

SCANS_TO_CHECK = 7
_CONVERT_PREFIX = "значение не приводится к"
CONVERT_KIND = "значение не приводится к виду"
OTHER_KIND = "другое"
_KIND_BY_FIELD = {f.name: f.kind for f in PROTOTYPE_FIELDS}
_LABEL_BY_FIELD = {f.name: f.label for f in PROTOTYPE_FIELDS}


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


def reason_kind(reason: str) -> str:
    """The kind of a rejection reason (one of the strings of `verify`, or «другое»)."""
    if reason.startswith(_CONVERT_PREFIX):
        return CONVERT_KIND
    if reason in (NO_QUOTE, QUOTE_NOT_FOUND, VALUE_NOT_CONFIRMED):
        return reason
    return OTHER_KIND


def field_counts(rows: Iterable[tuple[str, str]]) -> dict[str, dict[str, int]]:
    """Results per field, `(field, result)` rows in, fields in catalog order out."""
    counts = {name: {result.value: 0 for result in Result} for name in FIELD_NAMES}
    for name, result in rows:
        counts[name][result] += 1
    return counts


def recheck(
    kind: Kind,
    value_normalized: str,
    quote: str,
    quote_start: int,
    quote_end: int,
    text: str,
    shown_end: int,
) -> bool:
    """SC-001: the quote is at its place in the shown part of the text and holds the value."""
    if quote_end > shown_end or text[quote_start:quote_end] != quote:
        return False
    return find_in_quote(kind, value_normalized, quote) is not None


def seconds_summary(seconds: list[float | None]) -> dict[str, Any]:
    """Documents with a model request, their total, median and the largest time."""
    known = [s for s in seconds if s is not None]
    if not known:
        return {"documents": 0, "total": 0.0, "median": None, "max": None}
    return {
        "documents": len(known),
        "total": sum(known),
        "median": statistics.median(known),
        "max": max(known),
    }


def pick_review(docs: list[dict[str, Any]]) -> list[str]:
    """Б5: all text-layer ids, then seven scans at an even step, one `needs_review` if any."""
    ordered = sorted(docs, key=lambda d: d["document_id"])
    layer = [d["document_id"] for d in ordered if d["text_layer"]]
    scans = [d for d in ordered if not d["text_layer"]]
    n = len(scans)
    if n <= SCANS_TO_CHECK:
        picked = list(scans)
    else:
        picked = [scans[round(i * n / SCANS_TO_CHECK)] for i in range(SCANS_TO_CHECK)]
    if picked and not any(d["state"] == "needs_review" for d in picked):
        spare = next(
            (d for d in scans if d["state"] == "needs_review" and d not in picked), None
        )
        if spare is not None:
            picked[-1] = spare
    scan_ids = sorted(d["document_id"] for d in picked)
    return layer + scan_ids


@dataclass
class Report:
    states: dict[str, int] = field(default_factory=dict)
    fields: dict[str, dict[str, int]] = field(default_factory=dict)
    rejection_kinds: dict[str, int] = field(default_factory=dict)
    found_total: int = 0
    found_rechecked: int = 0
    clause_mismatch: int = 0
    party_marks: int = 0
    review: list[str] = field(default_factory=list)
    seconds: dict[str, Any] | None = None


def collect(conn: psycopg.Connection) -> Report:
    """Read the database after `extract` and count (no value or quote leaves this function)."""
    report = Report()
    rows = conn.execute("SELECT field, result FROM field_value").fetchall()
    report.fields = field_counts((r[0], r[1]) for r in rows)
    report.rejection_kinds = dict(
        Counter(
            reason_kind(r[0])
            for r in conn.execute(
                "SELECT reason FROM field_value WHERE result = 'rejected'"
            ).fetchall()
        )
    )

    statuses = conn.execute(
        "SELECT s.document_id, s.state, s.reason FROM stage_status s "
        "WHERE s.stage = 'extraction' AND EXISTS "
        "(SELECT 1 FROM field_value f WHERE f.document_id = s.document_id) "
        "ORDER BY s.document_id"
    ).fetchall()
    report.states = dict(Counter(s[1] for s in statuses))
    report.party_marks = sum(1 for s in statuses if s[2] and PARTIES in s[2])

    scanned = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT document_id FROM page_text WHERE source = 'recognized'"
        ).fetchall()
    }
    report.review = pick_review(
        [
            {"document_id": s[0], "text_layer": s[0] not in scanned, "state": s[1]}
            for s in statuses
        ]
    )

    found = conn.execute(
        "SELECT f.document_id, f.field, f.value_normalized, f.quote, f.quote_start, "
        "f.quote_end, f.clause_key, "
        "EXISTS (SELECT 1 FROM clause c WHERE c.document_id = f.document_id "
        "AND c.key = f.clause_key AND c.start <= f.quote_start AND f.quote_start < c.end_) "
        "FROM field_value f WHERE f.result = 'found' ORDER BY f.document_id, f.field"
    ).fetchall()
    texts: dict[str, tuple[str, int]] = {}
    for doc_id, name, normalized, quote, start, end, _key, clause_ok in found:
        if doc_id not in texts:
            text_row = conn.execute(
                "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
            ).fetchone()
            tail = conn.execute(
                "SELECT start FROM clause WHERE document_id = %s AND kind = 'tail'", (doc_id,)
            ).fetchone()
            text = text_row[0] if text_row else ""
            texts[doc_id] = (text, shown_end(text, tail[0] if tail else None))
        text, shown = texts[doc_id]
        report.found_total += 1
        if recheck(_KIND_BY_FIELD[name], normalized, quote, start, end, text, shown):
            report.found_rechecked += 1
        if not clause_ok:
            report.clause_mismatch += 1
    return report


def render(report: Report) -> list[str]:
    """Russian lines with numbers and document ids only."""
    total_docs = sum(report.states.values())
    lines = [
        "Б4. Результаты извлечения",
        f"  документов: {total_docs}; готово {report.states.get('done', 0)}, "
        f"требует просмотра {report.states.get('needs_review', 0)}, "
        f"ошибка {report.states.get('failed', 0)}",
        "  по полям (найдено / не найдено / отклонено / ошибка):",
    ]
    for name, c in report.fields.items():
        lines.append(
            f"    {_LABEL_BY_FIELD[name]}: {c['found']} / {c['not_found']} / "
            f"{c['rejected']} / {c['failed']}"
        )
    if report.rejection_kinds:
        lines.append("  виды причин отклонения:")
        lines += [f"    {kind}: {n}" for kind, n in sorted(report.rejection_kinds.items())]
    if report.seconds is not None:
        s = report.seconds
        lines.append(
            f"  время: запросов к модели {s['documents']}, всего {s['total']:.1f} с"
            + (
                f", медиана {s['median']:.1f} с, наибольшее {s['max']:.1f} с"
                if s["median"] is not None
                else ""
            )
        )
    lines += [
        "",
        f"SC-001: {report.found_rechecked} из {report.found_total} найденных значений "
        "прошли повторную проверку",
        f"  пункт цитаты не совпал с разбором: {report.clause_mismatch}",
        f"  документов с пометкой о составе сторон: {report.party_marks}",
        "",
        "Б5. Документы для ручной проверки (SC-002, SC-003)",
        "  " + (", ".join(report.review) if report.review else "нет"),
    ]
    return lines


def _seconds_from_report(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return seconds_summary([d.get("seconds") for d in data.get("documents", [])])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--report", help="the saved output of `extract --json` (run time)")
    args = parser.parse_args(argv)
    env = read_env(Path(args.env_file))
    if not env.get("DOCREADER_DATA_DIR"):
        sys.exit(f"В {args.env_file} нет DOCREADER_DATA_DIR")
    os.environ.update(env)
    settings = load_settings()

    with connect(settings) as conn:
        report = collect(conn)
    if args.report:
        report.seconds = _seconds_from_report(Path(args.report))
    text = "\n".join(render(report)) + "\n"
    print(text, end="")
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary = reports / f"extraction-b4-summary-{datetime.now():%Y%m%d-%H%M%S}.txt"
    summary.write_text(text, encoding="utf-8")
    print(f"\nСводка сохранена: {summary} (её можно прислать агенту)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
