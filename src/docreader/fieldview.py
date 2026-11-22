"""Loading the fields of one document for `docreader fields` (feature 05, US4; T022).

The view carries contract text (values, quotes): its output is never sent to the agent
for real contracts (contracts/cli.md «Что можно присылать агенту»).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from docreader.errors import UserError
from docreader.fields import PROTOTYPE_FIELDS
from docreader.ids import format_clause_id
from docreader.quality import LOW_QUALITY
from docreader.registry import _not_found, find_document
from docreader.stages import Stage


@dataclass(frozen=True)
class FieldView:
    """One field as `fields` shows it (contracts/cli.md «docreader fields», `--json`)."""

    field: str
    label: str
    result: str
    value_text: str | None
    value_normalized: str | None
    quote: str | None
    quote_start: int | None
    quote_end: int | None
    clause_id: str | None  # None when the clause no longer holds the quote (data-model.md)
    clause_missing: bool  # a found value whose clause is not in the current parse
    page: int | None
    pages: list[int] | None
    low_quality: bool  # a page of the quote has the flag low_recognition_quality
    reason: str | None
    proposed_value: str | None
    proposed_quote: str | None
    proposed_clause: str | None


@dataclass(frozen=True)
class FieldsView:
    document_id: str
    state: str
    reason: str | None
    run_id: int
    run_started_at: datetime
    model: str | None
    prompt_version: str | None
    fields: list[FieldView]  # the six prototype fields in catalog order

    def to_json(self) -> dict:
        def item(f: FieldView) -> dict:
            data = asdict(f)
            del data["clause_missing"]
            return data

        return {
            "document_id": self.document_id,
            "state": self.state,
            "reason": self.reason,
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "fields": [item(f) for f in self.fields],
        }


def load_fields(conn: psycopg.Connection, seq: int) -> FieldsView:
    """The fields of document `seq`, or UserError (unknown, not extracted, stale); T022."""
    doc = find_document(conn, seq)
    if doc is None:
        raise _not_found(seq)
    doc_id = doc["id"]
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT * FROM field_value WHERE document_id = %s", (doc_id,)
        ).fetchall()
    if not rows:
        raise UserError(f"Поля {doc_id} не извлекались — выполните docreader extract {doc_id}")
    found = conn.execute(
        "SELECT text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()
    if found is None or any(r["source_text_sha256"] != found[0] for r in rows):
        raise UserError(f"Поля устарели: текст изменён — выполните docreader extract {doc_id}")

    run_id = rows[0]["run_id"]
    with conn.cursor(row_factory=dict_row) as cur:
        run = cur.execute(
            "SELECT started_at, model, prompt_version FROM run WHERE id = %s", (run_id,)
        ).fetchone()
    assert run is not None  # run_id is a foreign key to run
    state, reason = conn.execute(
        "SELECT state, reason FROM stage_status WHERE document_id = %s AND stage = %s",
        (doc_id, Stage.EXTRACTION),
    ).fetchone() or ("", None)
    clauses = {
        key: (start, end)
        for key, start, end in conn.execute(
            "SELECT key, start, end_ FROM clause WHERE document_id = %s", (doc_id,)
        )
    }
    low_pages = {
        r[0]
        for r in conn.execute(
            "SELECT page_number FROM page_flag WHERE document_id = %s AND code = %s",
            (doc_id, LOW_QUALITY),
        )
    }
    by_field = {r["field"]: r for r in rows}
    views = []
    for spec in PROTOTYPE_FIELDS:
        r = by_field.get(spec.name)
        if r is None:
            raise UserError(
                f"Поля {doc_id} неполные ({spec.name}) — выполните docreader extract {doc_id}"
            )
        is_found = r["result"] == "found"
        clause_id: str | None = None
        clause_missing = False
        if is_found:
            span = clauses.get(r["clause_key"])
            if span is not None and span[0] <= r["quote_start"] < span[1]:
                clause_id = format_clause_id(doc_id, r["clause_key"])
            else:
                clause_missing = True
        views.append(
            FieldView(
                field=spec.name,
                label=spec.label,
                result=r["result"],
                value_text=r["value_text"],
                value_normalized=r["value_normalized"],
                quote=r["quote"],
                quote_start=r["quote_start"],
                quote_end=r["quote_end"],
                clause_id=clause_id,
                clause_missing=clause_missing,
                page=r["page"],
                pages=list(r["pages"]) if r["pages"] is not None else None,
                low_quality=is_found and any(p in low_pages for p in r["pages"]),
                reason=r["reason"],
                proposed_value=r["proposed_value"],
                proposed_quote=r["proposed_quote"],
                proposed_clause=r["proposed_clause"],
            )
        )
    return FieldsView(
        document_id=doc_id,
        state=state,
        reason=reason,
        run_id=run_id,
        run_started_at=run["started_at"],
        model=run["model"],
        prompt_version=run["prompt_version"],
        fields=views,
    )
