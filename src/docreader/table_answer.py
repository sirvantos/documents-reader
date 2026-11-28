"""The answer by the table (feature 10, research R-1, R-5, R-9).

`load_rows` reads the table of every contract of the registry by the effective values of
feature 06; nothing is written to the database (FR-013).
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any

import psycopg

from docreader import checks, llm
from docreader.checks import CellState, FieldStatus
from docreader.config import Settings
from docreader.errors import UserError
from docreader.ids import format_clause_id
from docreader.runs import code_version
from docreader.table_prompt import (
    PROMPT_VERSION,
    TableReply,
    build_messages,
    build_retry,
    prompt_sha256,
)
from docreader.table_query import (
    Cell,
    DocRow,
    NonQuery,
    Problem,
    Result,
    TableQuery,
    execute,
    resolve_party,
    validate,
)

__all__ = [
    "Cell",
    "DocRow",
    "TableAnswer",
    "TableOutcome",
    "TableProvenance",
    "Translation",
    "ask_table",
    "load_rows",
    "translate",
]

FIELDS = checks.FIELDS


def _whole(state: CellState) -> dict[str, Cell]:
    return {field: Cell(state, None, None, ()) for field in FIELDS}


def load_rows(conn: psycopg.Connection, settings: Settings) -> list[DocRow]:
    """Six cells of every registry document, in id order (research R-5).

    A document without extracted fields has all six cells `no_extraction`; one whose checks
    are missing or stale (`checks.split_fresh`) all six `checks_stale`: its statuses may not
    belong to its values.
    """
    registry = [r[0] for r in conn.execute("SELECT id FROM document ORDER BY seq")]
    extracted = checks.documents_with_extraction(conn)
    fresh, _ = checks.split_fresh(conn, settings, extracted)
    fresh_set, extracted_set = set(fresh), set(extracted)
    cells: dict[str, dict[str, Cell]] = {doc: {} for doc in fresh}
    for doc, field, status, flags, result, value, clause_key, decided in conn.execute(
        "SELECT v.document_id, v.field, s.status, s.flags, v.result, v.value_normalized,"
        " v.clause_key, d.value_normalized"
        " FROM field_value v JOIN field_status s USING (document_id, field)"
        " LEFT JOIN field_decision d USING (document_id, field)"
        " WHERE v.document_id = ANY(%s) AND v.field = ANY(%s)",
        (fresh, list(FIELDS)),
    ):
        state, cell_value = checks.effective_cell(
            FieldStatus(status), tuple(flags), str(result),
            None if value is None else str(value), None if decided is None else str(decided),
        )
        clause = None if clause_key is None else format_clause_id(doc, clause_key)
        cells[doc][field] = Cell(state, cell_value, clause, tuple(flags))
    rows: list[DocRow] = []
    for doc in registry:
        if doc not in extracted_set:
            rows.append(DocRow(doc, _whole(CellState.NO_EXTRACTION)))
        elif doc not in fresh_set or set(cells[doc]) != set(FIELDS):
            rows.append(DocRow(doc, _whole(CellState.CHECKS_STALE)))
        else:
            rows.append(DocRow(doc, {f: cells[doc][f] for f in FIELDS}))
    return rows


class TableOutcome(StrEnum):
    """How a question ended (data-model.md)."""

    ANSWERED = "answered"
    REFUSED = "refused"
    CLARIFY = "clarify"
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class Translation:
    """The question turned into a query, or the reason it was not (research R-9)."""

    outcome: TableOutcome
    parsed: TableQuery | NonQuery | None
    reason: str | None
    retried: bool


_NON_QUERY = {
    "refuse": TableOutcome.REFUSED,
    "clarify": TableOutcome.CLARIFY,
    "unsupported": TableOutcome.UNSUPPORTED,
}


def _done(parsed: TableQuery | NonQuery, retried: bool) -> Translation:
    if isinstance(parsed, TableQuery):
        return Translation(TableOutcome.ANSWERED, parsed, None, retried)
    return Translation(_NON_QUERY[parsed.kind], parsed, parsed.reason, retried)


def translate(client: llm.ModelClient, question: str, today: date) -> Translation:
    """One model call, the check of its reply, one retry for an invalid query (R-9).

    `ModelUnavailable` (no connection, a timeout) propagates.
    """
    messages = build_messages(question, today)
    try:
        reply = client.extract(messages, TableReply)
    except (llm.AnswerFormError, llm.ModelRequestError) as exc:
        return Translation(TableOutcome.FAILED, None, str(exc), False)
    first = validate(reply, today)
    if not isinstance(first, Problem):
        return _done(first, False)
    retry = build_retry(messages, reply.model_dump_json(), first.retry_text())
    try:
        again = client.extract(retry, TableReply)
    except (llm.AnswerFormError, llm.ModelRequestError):
        return Translation(TableOutcome.REJECTED, None, first.text(), True)
    second = validate(again, today)
    if isinstance(second, Problem):
        return Translation(TableOutcome.REJECTED, None, second.text(), True)
    return _done(second, True)


@dataclass(frozen=True)
class TableProvenance:
    """What the answer was made with."""

    code_version: str
    llm_model: str
    prompt_version: str
    prompt_sha256: str
    checks_version: str


@dataclass(frozen=True)
class TableAnswer:
    """The result of one question (data-model.md)."""

    question: str
    outcome: TableOutcome
    result: Result | None
    reason: str | None
    other: str | None
    retried: bool
    today: date
    provenance: TableProvenance
    seconds: float

    def to_json(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "other": self.other,
            "retried": self.retried,
            "today": self.today.isoformat(),
            "seconds": self.seconds,
            "provenance": dataclasses.asdict(self.provenance),
            "result": None if self.result is None else _result_json(self.result),
        }


def _result_json(result: Result) -> dict[str, Any]:
    q = result.query
    return {
        "query": {
            "action": q.action,
            "field": q.field,
            "op": q.op,
            "value": str(q.value),
            "value_to": q.value_to,
            "period": q.period,
            "side": q.side,
        },
        "count": result.count,
        "considered": result.considered,
        "total": result.total,
        "include_unreviewed": result.include_unreviewed,
        "matched_names": list(result.matched_names),
        "rows": [
            {
                "document_id": item.row.document_id,
                "unreviewed": item.unreviewed,
                "cells": {
                    field: {
                        "state": cell.state.value,
                        "value": cell.value,
                        "clause_id": cell.clause_id,
                        "flags": list(cell.flags),
                    }
                    for field, cell in item.row.cells.items()
                },
            }
            for item in result.rows
        ],
        "excluded": {state: list(docs) for state, docs in result.excluded.items()},
    }


def ask_table(
    conn: psycopg.Connection,
    settings: Settings,
    question: str,
    include_unreviewed: bool = False,
    client: llm.ModelClient | None = None,
    today: date | None = None,
) -> TableAnswer:
    """Answer `question` from the table of effective values; nothing is written (R-1)."""
    if not question.strip():
        raise UserError("Пустой вопрос — введите вопрос о договорах")
    if client is None:
        client = llm.load_client(
            dataclasses.replace(
                settings.extraction,
                max_tokens=settings.table.max_tokens,
                max_retries=settings.table.max_retries,
            )
        )
    llm_model = client.check()
    started = time.perf_counter()
    if not checks.documents_with_extraction(conn):
        raise UserError(
            "По таблице ответить нельзя: нет извлечённых полей "
            "(docreader extract, docreader check)"
        )
    day = today if today is not None else date.today()
    translation = translate(client, question, day)
    result: Result | None = None
    outcome = translation.outcome
    reason = translation.reason
    parsed = translation.parsed
    other: str | None = None
    if isinstance(parsed, TableQuery):
        other = parsed.other
        rows = load_rows(conn, settings)
        resolved = resolve_party(parsed, rows, include_unreviewed)
        if isinstance(resolved, NonQuery):
            outcome, reason = TableOutcome.CLARIFY, resolved.reason
        else:
            result = execute(resolved, rows, include_unreviewed)
    return TableAnswer(
        question=question,
        outcome=outcome,
        result=result,
        reason=reason,
        other=other,
        retried=translation.retried,
        today=day,
        provenance=TableProvenance(
            code_version=code_version(),
            llm_model=llm_model,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=prompt_sha256(),
            checks_version=checks.CHECKS_VERSION,
        ),
        seconds=round(time.perf_counter() - started, 3),
    )
