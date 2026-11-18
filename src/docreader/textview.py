"""Loading read text for `docreader text` (contracts/cli.md; tasks T017, T037, T050)."""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from docreader.errors import UserError
from docreader.ids import format_document_id
from docreader.quality import FLAG_ORDER
from docreader.registry import _not_found, find_document


def _require_read(conn: psycopg.Connection, seq: int) -> dict:
    """The document row; errors if it is unknown or has no document_text row."""
    doc = find_document(conn, seq)
    if doc is None:
        raise _not_found(seq)
    found = conn.execute(
        "SELECT 1 FROM document_text WHERE document_id = %s", (doc["id"],)
    ).fetchone()
    if found is None:
        doc_id = format_document_id(seq)
        raise UserError(
            f"Документ {doc_id} ещё не прочитан — выполните docreader read {doc_id}"
        )
    return doc


def _flags_by_page(conn: psycopg.Connection, doc_id: str) -> dict[int, list[dict]]:
    rows = conn.execute(
        "SELECT page_number, code, reason FROM page_flag WHERE document_id = %s",
        (doc_id,),
    ).fetchall()
    order = {code: i for i, code in enumerate(FLAG_ORDER)}
    rows.sort(key=lambda r: (r[0], order.get(r[1], len(order))))
    by_page: dict[int, list[dict]] = {}
    for page, code, reason in rows:
        by_page.setdefault(page, []).append({"code": code, "reason": reason})
    return by_page


def load_document_text(conn: psycopg.Connection, seq: int) -> dict:
    """Clean text of a read document split by pages (task T017).

    `{"id": "D-0001", "read_pages": int, "pages": [{"page": 1, "flags": [{"code",
    "reason"}], "text": "<slice of document_text.text for this page>"}]}`
    """
    doc = _require_read(conn, seq)
    doc_id = doc["id"]
    text, read_pages = conn.execute(
        "SELECT text, read_pages FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()
    numbers = [
        r[0]
        for r in conn.execute(
            "SELECT page_number FROM page_text WHERE document_id = %s ORDER BY page_number",
            (doc_id,),
        )
    ]
    bounds = {
        page: (start, end)
        for page, start, end in conn.execute(
            "SELECT page_number, min(start), max(end_) FROM text_span"
            " WHERE document_id = %s GROUP BY page_number",
            (doc_id,),
        )
    }
    flags = _flags_by_page(conn, doc_id)
    conn.commit()
    return {
        "id": doc_id,
        "read_pages": read_pages,
        "pages": [
            {
                "page": n,
                "flags": flags.get(n, []),
                "text": text[bounds[n][0] : bounds[n][1]] if n in bounds else "",
            }
            for n in numbers
        ],
    }


def load_page(conn: psycopg.Connection, seq: int, page: int) -> dict:
    """One page of a read document (task T017).

    `{"id": "D-0001", "pages": [{"page": 2, "rotation": 0, "has_table": false,
    "flags": [{"code", "reason"}], "lines": [<page_text.lines elements>]}]}`
    """
    doc = _require_read(conn, seq)
    doc_id = doc["id"]
    if not 1 <= page <= doc["page_count"]:
        raise UserError(f"В документе {doc_id} нет страницы {page} (страниц: {doc['page_count']})")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT rotation, has_table, lines FROM page_text"
            " WHERE document_id = %s AND page_number = %s",
            (doc_id, page),
        ).fetchone()
    flags = _flags_by_page(conn, doc_id).get(page, [])
    conn.commit()
    if row is None:
        raise UserError(f"Страница {page} документа {doc_id} не прочитана")
    return {
        "id": doc_id,
        "pages": [
            {
                "page": page,
                "rotation": row["rotation"],
                "has_table": row["has_table"],
                "flags": flags,
                "lines": row["lines"],
            }
        ],
    }
