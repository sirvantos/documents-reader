"""One passage by its clause id, for `docreader passage` (feature 07, T020)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import psycopg

from docreader import indexing
from docreader.errors import UserError
from docreader.ids import format_clause_id, parse_clause_id
from docreader.registry import _not_found, find_document


@dataclass(frozen=True)
class VectorInfo:
    model: str
    dims: int
    truncated: bool
    input_chars: int


@dataclass(frozen=True)
class PassageView:
    clause_id: str
    document_id: str
    clause_key: str
    part: str
    first_page: int
    last_page: int
    label: str
    text: str
    word_index: bool
    vectors: list[VectorInfo]
    run_id: int
    run_date: str  # YYYY-MM-DD of the indexing run

    def to_json(self) -> dict:
        data = asdict(self)
        del data["run_date"]
        return data


def load_passage(conn: psycopg.Connection, clause_id: str) -> PassageView:
    """The passage of `clause_id`, or UserError saying what to do (contracts/cli.md)."""
    seq, key = parse_clause_id(clause_id)
    doc = find_document(conn, seq)
    if doc is None:
        raise _not_found(seq)
    doc_id = doc["id"]
    full_id = format_clause_id(doc_id, key)
    count = conn.execute(
        "SELECT count(*) FROM passage WHERE document_id = %s", (doc_id,)
    ).fetchone()
    if not count or count[0] == 0:
        raise UserError(f"Отрывков нет: выполните docreader index {doc_id}")
    if not indexing.passages_current(conn, doc_id):
        raise UserError(
            "Отрывки устарели: текст или разбор изменились — "
            f"выполните docreader index {doc_id}"
        )
    row = conn.execute(
        "SELECT p.part, p.first_page, p.last_page, p.label,"
        " substr(t.text, p.start + 1, p.end_ - p.start), p.run_id, r.started_at::date::text"
        " FROM passage p JOIN document_text t ON t.document_id = p.document_id"
        " JOIN run r ON r.id = p.run_id"
        " WHERE p.document_id = %s AND p.clause_key = %s",
        (doc_id, key),
    ).fetchone()
    if row is None:
        known = conn.execute(
            "SELECT 1 FROM clause WHERE document_id = %s AND key = %s", (doc_id, key)
        ).fetchone()
        if known:
            raise UserError(f"Нет отрывка {full_id}: у записи нет текста, кроме заголовка")
        raise UserError(f"Нет записи {full_id}")
    part, first, last, label, text, run_id, run_date = row
    vectors = [
        VectorInfo(*v)
        for v in conn.execute(
            "SELECT model, dims, truncated, input_chars FROM passage_vector"
            " WHERE document_id = %s AND clause_key = %s ORDER BY model",
            (doc_id, key),
        )
    ]
    return PassageView(
        full_id, doc_id, key, part, first, last, label, text, True, vectors, run_id, run_date
    )
