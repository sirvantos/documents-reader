"""Comparison of fields with the gold set and the results table (feature 02, R-7, R-13).

`compare_fields` pairs every registry document with every field of the set, takes the
system value from feature 05 (`field_value`), from the rules (`rules.py`) or from a file,
decides each pair with `outcomes.field_outcome` and writes one record of `eval_result`
with its `eval_case` rows. `write_record` is shared with the search and blind records.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg.types.json import Jsonb

from docreader import catalog, outcomes, review, rules
from docreader.config import Settings
from docreader.errors import UserError
from docreader.fields import FIELD_NAMES
from docreader.gold import REVIEW_PATHS, GoldState, current_sha256
from docreader.ids import format_clause_id
from docreader.outcomes import (
    EvalStage,
    FieldCase,
    GoldValue,
    Outcome,
    SystemValue,
)
from docreader.runs import code_version
from docreader.values import normalize_field

FIELD_RESULTS_FORMAT = "docreader-field-results/1"
GOLD_SEPARATOR = " || "
ABSENT_WORD = "отсутствует"
UNLABELED_GOLD = "unlabeled"
_RESULTS = frozenset({"found", "not_found", "rejected", "failed"})
FieldSet = Literal["prototype", "queue1", "all"]
Source = Literal["extraction", "rules"]


# --- the record writer ------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseRow:
    """One `eval_case` row to write."""

    case_key: str
    document_id: str
    outcome: str | None
    gold_sha: str
    field: str | None = None
    question_key: str | None = None
    place: int | None = None
    flags: tuple[str, ...] = ()


def gold_fingerprint(gold: GoldValue | None) -> str:
    """First 16 hex of sha256 of the gold content of a pair (state + normalized variants)."""
    if gold is None:
        content = UNLABELED_GOLD
    else:
        content = "\t".join((gold.state.value, "\x1f".join(gold.normalized)))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def _check_sums(metrics: dict[str, Any], cases: Sequence[CaseRow]) -> None:
    """The counts stored in `metrics` must equal a recount of the cases (SC-002, SC-004)."""
    counts = metrics.get("overall", {}).get("counts")
    if counts is None:
        return
    recount = Counter(c.outcome for c in cases if c.outcome is not None)
    stored = {k: v for k, v in counts.items() if v}
    if stored != dict(recount):
        raise ValueError(
            f"the counts of the record ({stored}) differ from the recount of its cases "
            f"({dict(recount)})"
        )


def write_record(
    conn: psycopg.Connection,
    *,
    stage: EvalStage,
    label: str,
    provenance: dict[str, Any],
    gold_sha256: str | None,
    questions_sha256: str | None,
    reviewed_share: float | None,
    blind_summary: dict[str, Any] | None,
    metrics: dict[str, Any],
    cases: Sequence[CaseRow],
    review_file: str | Callable[[int], str] | None,
    from_file: str | None,
) -> int:
    """Write `eval_result` and all its `eval_case` rows in one transaction; return the id.

    `review_file` may be a function of the record id (the file name holds the number): it
    is called inside the transaction, so a failing file write leaves no record.
    """
    _check_sums(metrics, cases)
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO eval_result (label, stage, provenance, gold_sha256, questions_sha256,"
            " reviewed_share, blind_summary, metrics, from_file)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                label, stage.value, Jsonb(provenance), gold_sha256, questions_sha256,
                reviewed_share, None if blind_summary is None else Jsonb(blind_summary),
                Jsonb(metrics), from_file,
            ),
        ).fetchone()
        assert row is not None
        record = int(row[0])
        path = review_file(record) if callable(review_file) else review_file
        if path is not None:
            conn.execute("UPDATE eval_result SET review_file = %s WHERE id = %s", (path, record))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO eval_case (result_id, case_key, document_id, field, question_key,"
                " outcome, place, flags, gold_sha) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (record, c.case_key, c.document_id, c.field, c.question_key, c.outcome,
                     c.place, list(c.flags), c.gold_sha)
                    for c in cases
                ],
            )
    return record


def reviewed_share(conn: psycopg.Connection) -> float | None:
    """Share of `gold_field` rows with a path from the review page; None for an empty gold."""
    total, reviewed = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE path = ANY(%s)) FROM gold_field",
        ([p.value for p in REVIEW_PATHS],),
    ).fetchone() or (0, 0)
    return reviewed / total if total else None


def latest_blind_summary(conn: psycopg.Connection) -> dict[str, Any] | None:
    """`metrics` of the latest `gold_blind` record, or None."""
    row = conn.execute(
        "SELECT id, metrics FROM eval_result WHERE stage = %s ORDER BY id DESC LIMIT 1",
        (EvalStage.GOLD_BLIND.value,),
    ).fetchone()
    if row is None:
        return None
    summary: dict[str, Any] = dict(row[1])
    summary["record"] = row[0]
    return summary


def review_path(data_dir: Path, name: str, record: int, now: datetime) -> Path:
    """`eval/<name>-<record>-<YYYYMMDD-HHMMSS>.csv` in the data folder."""
    return data_dir / "eval" / f"{name}-{record}-{now:%Y%m%d-%H%M%S}.csv"


def write_csv(path: Path, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    """CSV in the format of the template: UTF-8 with BOM, `;`, every cell quoted."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(buffer.getvalue(), encoding="utf-8-sig")


def relative_label(path: Path, data_dir: Path) -> str:
    """Relative to the data folder when inside it, else only the file name."""
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return path.name


# --- system values ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Shown:
    """What the review file shows of the system value."""

    value: str
    clause: str
    quote: str


@dataclass(frozen=True)
class Collected:
    values: dict[tuple[str, str], SystemValue]
    shown: dict[tuple[str, str], Shown]
    provenance: dict[str, Any]


def _collect_extraction(
    conn: psycopg.Connection, documents: Sequence[str], fields: Sequence[str]
) -> Collected:
    text_sha: dict[str, str] = dict(
        conn.execute("SELECT document_id, text_sha256 FROM document_text").fetchall()
    )
    values: dict[tuple[str, str], SystemValue] = {}
    shown: dict[tuple[str, str], Shown] = {}
    run_ids: set[int] = set()
    rows = conn.execute(
        "SELECT document_id, field, result, value_text, value_normalized, clause_key, quote,"
        " proposed_value, proposed_clause, proposed_quote, source_text_sha256, run_id"
        " FROM field_value WHERE document_id = ANY(%s) AND field = ANY(%s)",
        (list(documents), list(fields)),
    ).fetchall()
    for doc, name, result, text, norm, clause, quote, p_value, p_clause, p_quote, sha, run in rows:
        run_ids.add(run)
        stale = text_sha.get(doc) != sha
        values[(doc, name)] = SystemValue(result, norm, stale)
        value, key, cite = (text, clause, quote) if result == "found" else (
            p_value, p_clause, p_quote
        )
        if value is not None:
            shown[(doc, name)] = Shown(
                value, format_clause_id(doc, key) if key else "", cite or ""
            )
    runs: list[dict[str, Any]] = []
    for run_id, model, prompt, started in conn.execute(
        "SELECT id, model, prompt_version, started_at FROM run WHERE id = ANY(%s) ORDER BY id",
        (sorted(run_ids),),
    ):
        runs.append({
            "id": run_id, "model": model, "prompt_version": prompt,
            "started_at": started.isoformat(),
        })
    return Collected(values, shown, {"code_version": code_version(), "runs": runs})


def _collect_rules(
    conn: psycopg.Connection, documents: Sequence[str], fields: Sequence[str]
) -> Collected:
    values: dict[tuple[str, str], SystemValue] = {}
    shown: dict[tuple[str, str], Shown] = {}
    for doc in documents:
        ready = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM document_text WHERE document_id = %s)"
            " AND EXISTS (SELECT 1 FROM clause WHERE document_id = %s)",
            (doc, doc),
        ).fetchone()
        if not ready or not ready[0]:
            continue  # no text or no parse: the pairs have no result
        found = review._load_rules(conn, doc)
        for name in fields:
            if name not in FIELD_NAMES:
                continue
            candidates = found.get((doc, name), [])
            if candidates:
                first = candidates[0]  # several values: the first, nothing flagged
                values[(doc, name)] = SystemValue("found", first.normalized)
                shown[(doc, name)] = Shown(
                    first.value, format_clause_id(doc, first.clause) if first.clause else "",
                    first.quote,
                )
            else:
                values[(doc, name)] = SystemValue("not_found", None)
    return Collected(
        values, shown, {"code_version": code_version(), "rules_version": rules.RULES_VERSION}
    )


def _collect_file(path: Path) -> tuple[dict[tuple[str, str], tuple[str, str | None]], str]:
    """The rows of a results file: (document, field) → (result, raw value), and the source."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise UserError(f"Файл результатов не читается или не JSON: {path}") from None
    if not isinstance(data, dict) or data.get("format") != FIELD_RESULTS_FORMAT:
        raise UserError(
            f"Файл результатов должен иметь формат «{FIELD_RESULTS_FORMAT}» (ключ format)"
        )
    rows: dict[tuple[str, str], tuple[str, str | None]] = {}
    for item in data.get("values", []):
        result = item.get("result")
        if result not in _RESULTS or "document" not in item or "field" not in item:
            raise UserError(
                "Строка файла результатов без document, field или с неизвестным result: "
                f"{item.get('document')}/{item.get('field')}"
            )
        value = item.get("value")
        rows[(item["document"], item["field"])] = (
            result, value if isinstance(value, str) else None
        )
    return rows, str(data.get("source", ""))


def _from_file_values(
    rows: dict[tuple[str, str], tuple[str, str | None]], fields: Sequence[catalog.CatalogField]
) -> dict[tuple[str, str], SystemValue]:
    by_name = {f.name: f for f in fields}
    values: dict[tuple[str, str], SystemValue] = {}
    for (doc, name), (result, raw) in rows.items():
        field = by_name.get(name)
        if field is None:
            continue
        normalized: str | None = None
        if result == "found":
            try:
                normalized = normalize_field(field, raw or "")
            except ValueError:
                result = "rejected"  # a value that does not fit the field is not a value
        values[(doc, name)] = SystemValue(result, normalized)
    return values


# --- the comparison ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldsRecord:
    """The written record of `eval fields`, as `render` needs it: counts and ids only."""

    record: int
    stage: str
    label: str
    source: str
    pairs: int
    totals: outcomes.Totals
    provenance: dict[str, Any]
    review_file: str
    gold_version: str
    reviewed_share: float | None
    blind: dict[str, Any] | None


def _gold_rows(conn: psycopg.Connection) -> tuple[dict[tuple[str, str], GoldValue], dict[
    tuple[str, str], list[str]
]]:
    gold: dict[tuple[str, str], GoldValue] = {}
    written: dict[tuple[str, str], list[str]] = {}
    for doc, name, state, texts, norm in conn.execute(
        "SELECT document_id, field, state, values_text, values_normalized FROM gold_field"
    ):
        gold[(doc, name)] = GoldValue(GoldState(state), tuple(norm))
        written[(doc, name)] = list(texts)
    return gold, written


def _fields_of(
    field_set: FieldSet | None, marked: set[str]
) -> list[catalog.CatalogField]:
    if field_set is None:
        return [f for f in catalog.CATALOG if f.name in marked]
    return {
        "prototype": list(catalog.PROTOTYPE),
        "queue1": list(catalog.QUEUE1),
        "all": list(catalog.CATALOG),
    }[field_set]


def _metrics(totals: outcomes.Totals) -> dict[str, Any]:
    def counts(c: outcomes.OutcomeCounts) -> dict[str, int]:
        return {o.value: c.counts[o] for o in Outcome}

    def shares(c: outcomes.OutcomeCounts) -> dict[str, float | None]:
        return {o.value: c.share(o) for o in outcomes.SCORED}

    return {
        "overall": {
            "counts": counts(totals.overall), "scored": totals.overall.scored,
            "shares": shares(totals.overall),
        },
        "fields": [
            {"field": t.field, "counts": counts(t.counts), "shares": shares(t.counts)}
            for t in totals.fields
        ],
        "not_extracted": [
            {"field": t.field, "counts": counts(t.counts), "shares": shares(t.counts)}
            for t in totals.not_extracted
        ],
    }


def compare_fields(
    conn: psycopg.Connection,
    settings: Settings,
    *,
    label: str,
    source: Source,
    from_file: Path | None,
    field_set: FieldSet | None,
) -> FieldsRecord:
    """Compare the system values with the gold set and write one record (research R-7)."""
    gold, written = _gold_rows(conn)
    if not gold:
        raise UserError(
            "Сравнивать не с чем: эталон пуст. Загрузите его: docreader eval load ФАЙЛ"
        )
    fields = _fields_of(field_set, {name for _, name in gold})
    names = [f.name for f in fields]
    documents = [d for (d,) in conn.execute("SELECT id FROM document ORDER BY id").fetchall()]

    shown: dict[tuple[str, str], Shown] = {}
    if from_file is not None:
        rows, file_source = _collect_file(from_file)
        values = _from_file_values(rows, fields)
        provenance: dict[str, Any] = {"code_version": code_version(), "source": file_source}
        stage = EvalStage.FIELDS
        extracted = {name: True for name in names}
        from_label: str | None = relative_label(from_file, settings.data_dir)
    else:
        collected = (
            _collect_rules(conn, documents, names)
            if source == "rules"
            else _collect_extraction(conn, documents, names)
        )
        values, shown, provenance = collected.values, collected.shown, collected.provenance
        stage = EvalStage.RULES if source == "rules" else EvalStage.FIELDS
        extracted = {name: name in FIELD_NAMES for name in names}
        from_label = None

    cases: list[FieldCase] = []
    rows_out: list[CaseRow] = []
    csv_rows: list[list[str]] = []
    for doc in documents:
        for field in fields:
            pair = (doc, field.name)
            g = gold.get(pair)
            result = outcomes.field_outcome(
                field, g, values.get(pair), extracted=extracted[field.name]
            )
            cases.append(FieldCase(doc, field.name, result, extracted[field.name]))
            rows_out.append(CaseRow(
                f"{doc}/{field.name}", doc, result.outcome.value, gold_fingerprint(g),
                field=field.name, flags=result.flags,
            ))
            gold_text = (
                "" if g is None else ABSENT_WORD if g.state is GoldState.ABSENT
                else GOLD_SEPARATOR.join(written[pair])
            )
            s = shown.get(pair)
            csv_rows.append([
                doc, field.name, result.outcome.value, ",".join(result.flags), gold_text,
                s.value if s else "", s.clause if s else "", s.quote if s else "",
            ])
    totals = outcomes.totals(cases)
    metrics = _metrics(totals)
    gold_version = current_sha256(conn)
    share = reviewed_share(conn)
    blind = latest_blind_summary(conn)
    now = datetime.now()

    def write_review(record: int) -> str:
        path = review_path(settings.data_dir, "fields", record, now)
        write_csv(
            path,
            ("document_id", "field", "outcome", "flags", "gold", "system", "clause", "quote"),
            csv_rows,
        )
        return relative_label(path, settings.data_dir)

    record = write_record(
        conn,
        stage=stage, label=label, provenance=provenance, gold_sha256=gold_version,
        questions_sha256=None, reviewed_share=share, blind_summary=blind, metrics=metrics,
        cases=rows_out, review_file=write_review, from_file=from_label,
    )
    review_file = conn.execute(
        "SELECT review_file FROM eval_result WHERE id = %s", (record,)
    ).fetchone()
    assert review_file is not None
    return FieldsRecord(
        record=record, stage=stage.value, label=label,
        source="file" if from_file is not None else source, pairs=len(cases), totals=totals,
        provenance=provenance, review_file=review_file[0], gold_version=gold_version,
        reviewed_share=share, blind=blind,
    )
