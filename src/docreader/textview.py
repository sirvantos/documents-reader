"""Loading read text for `docreader text` (contracts/cli.md; tasks T017, T037, T050)."""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from docreader.db import fetch_row
from docreader.errors import UserError
from docreader.ids import format_document_id
from docreader.quality import FLAG_ORDER
from docreader.registry import _not_found, find_document
from docreader.textnorm import normalize_chars


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
    text, read_pages = fetch_row(
        conn.execute(
            "SELECT text, read_pages FROM document_text WHERE document_id = %s", (doc_id,)
        )
    )
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


_CONTEXT_CHARS = 30
_REMOVED_ROLES = ("header", "footer", "page_number")


def _occurrences(text: str, phrase: str) -> list[int]:
    """Start offsets of non-overlapping, left-to-right, exact occurrences."""
    found: list[int] = []
    pos = text.find(phrase)
    while pos != -1:
        found.append(pos)
        pos = text.find(phrase, pos + len(phrase))
    return found


def find_phrase(
    conn: psycopg.Connection, seq: int, phrase: str, *, with_context: bool = False
) -> dict:
    """Search a phrase in the clean text and in removed page elements (task T037).

    `{"id", "phrase" (normalized), "matches": [{"start", "end", "page", "line",
    "bbox", "role"}]}`; clean-text matches first (by start), then matches in lines
    with role header/footer/page_number (by page and line; offsets inside the line). With
    `with_context` every match also gets a `context` string (up to 30 characters around it)
    for text rendering.
    """
    doc = _require_read(conn, seq)
    doc_id = doc["id"]
    needle = normalize_chars(phrase)
    if not needle:
        raise UserError("Пустая фраза для поиска")
    text = fetch_row(
        conn.execute("SELECT text FROM document_text WHERE document_id = %s", (doc_id,))
    )[0]
    page_lines: dict[int, dict[int, dict]] = {}
    for page, lines in conn.execute(
        "SELECT page_number, lines FROM page_text WHERE document_id = %s ORDER BY page_number",
        (doc_id,),
    ):
        page_lines[page] = {line["i"]: line for line in lines}

    def context(source: str, start: int, end: int) -> dict:
        if not with_context:
            return {}
        before = source[max(0, start - _CONTEXT_CHARS) : start]
        after = source[end : end + _CONTEXT_CHARS]
        return {"context": f"{before}{source[start:end]}{after}".replace("\n", " ")}

    matches: list[dict] = []
    for start in _occurrences(text, needle):
        end = start + len(needle)
        span = conn.execute(
            "SELECT page_number, line_index FROM text_span"
            " WHERE document_id = %s AND end_ > %s AND start < %s"
            " ORDER BY start LIMIT 1",
            (doc_id, start, end),
        ).fetchone()
        if span is None:
            continue
        page, index = span
        line = page_lines.get(page, {}).get(index, {})
        matches.append(
            {
                "start": start,
                "end": end,
                "page": page,
                "line": index,
                "bbox": line.get("bbox"),
                "role": line.get("role", "body"),
                **context(text, start, end),
            }
        )
    for page in sorted(page_lines):
        for index in sorted(page_lines[page]):
            line = page_lines[page][index]
            if line.get("role") not in _REMOVED_ROLES:
                continue
            for start in _occurrences(line["text"], needle):
                matches.append(
                    {
                        "start": start,
                        "end": start + len(needle),
                        "page": page,
                        "line": index,
                        "bbox": line.get("bbox"),
                        "role": line["role"],
                        **context(line["text"], start, start + len(needle)),
                    }
                )
    conn.commit()
    return {"id": doc_id, "phrase": needle, "matches": matches}


def reading_report(conn: psycopg.Connection) -> dict:
    """Reading report over documents whose `reading` stage is not pending (task T050).

    `{"documents": [{"id", "name", "pages", "read", "flags": {code: n}, "tables",
    "state"}], "totals": {"pages", "read", "flags": {code: n}, "tables"}}`. Only ids,
    names and numbers; no text. `state` is the stage state code (done, needs_review,
    failed), as in `read --json`.
    """
    flag_columns = ", ".join(
        f"count(*) FILTER (WHERE code = '{code}') AS {code}" for code in FLAG_ORDER
    )
    flag_selects = ", ".join(f"coalesce(pf.{code}, 0)" for code in FLAG_ORDER)
    rows = conn.execute(
        f"SELECT d.id, d.original_name, d.page_count, s.state,"
        f" coalesce(pt.read, 0), coalesce(pt.tables, 0), {flag_selects}"
        " FROM document d"
        " JOIN stage_status s ON s.document_id = d.id AND s.stage = 'reading'"
        " LEFT JOIN (SELECT document_id,"
        "   count(*) FILTER (WHERE jsonb_array_length(lines) > 0) AS read,"
        "   count(*) FILTER (WHERE has_table) AS tables"
        "   FROM page_text GROUP BY document_id) pt ON pt.document_id = d.id"
        f" LEFT JOIN (SELECT document_id, {flag_columns}"
        "   FROM page_flag GROUP BY document_id) pf ON pf.document_id = d.id"
        " WHERE s.state <> 'pending' ORDER BY d.seq"
    ).fetchall()
    conn.commit()
    documents = [
        {
            "id": doc_id,
            "name": name,
            "pages": pages,
            "read": read,
            "flags": dict(zip(FLAG_ORDER, counts, strict=True)),
            "tables": tables,
            "state": state,
        }
        for doc_id, name, pages, state, read, tables, *counts in rows
    ]
    totals = {
        "pages": sum(d["pages"] for d in documents),
        "read": sum(d["read"] for d in documents),
        "flags": {c: sum(d["flags"][c] for d in documents) for c in FLAG_ORDER},
        "tables": sum(d["tables"] for d in documents),
    }
    return {"documents": documents, "totals": totals}
