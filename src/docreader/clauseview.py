"""Loading the clause outline and clause text for `docreader outline` / `clause` (task T015)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import psycopg
from psycopg.rows import dict_row

from docreader.errors import UserError
from docreader.ids import PREAMBLE_KEY, TAIL_KEY, format_clause_id, format_document_id
from docreader.parsing import UNREAD_FLAGS
from docreader.quality import LOW_QUALITY
from docreader.registry import _not_found, find_document
from docreader.stages import Stage

_HEAD_CHARS = 60
_WHITESPACE = re.compile(r"\s+")
_NAMED_KEYS = (PREAMBLE_KEY, TAIL_KEY)


@dataclass(frozen=True)
class OutlineRecord:
    id: str
    key: str
    kind: str
    number_printed: str | None
    depth: int
    parent: str | None
    title: str | None
    section_number: int | None
    section_title: str | None
    start: int
    end: int
    first_page: int
    last_page: int
    recognized: bool
    low_quality: bool
    head: str


@dataclass(frozen=True)
class Outline:
    document_id: str
    state: str
    reason: str | None
    run_id: int
    parsed_at: str
    records: list[OutlineRecord]
    unread_pages: list[int]

    def to_json(self) -> dict:
        return {
            "document_id": self.document_id,
            "state": self.state,
            "reason": self.reason,
            "run_id": self.run_id,
            "records": [asdict(r) for r in self.records],
            "unread_pages": self.unread_pages,
        }


@dataclass(frozen=True)
class ClausePart:
    id: str
    number_printed: str | None
    depth: int
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class ClauseView:
    id: str
    section_title: str | None
    first_page: int
    last_page: int
    recognized: bool
    records: list[ClausePart]

    def to_json(self) -> dict:
        return asdict(self)


def _load_rows(conn: psycopg.Connection, seq: int) -> tuple[dict, list[dict], str]:
    """The document, its clause rows in `ordinal` order and `document_text.text`.

    Raises `UserError` if the document is unknown, not parsed, or the parse is stale.
    """
    doc = find_document(conn, seq)
    if doc is None:
        raise _not_found(seq)
    doc_id = doc["id"]
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            "SELECT c.key, c.kind, c.number_printed, c.depth, c.parent_key, c.title,"
            " c.section_number, c.section_title, c.start, c.end_ AS end, c.first_page,"
            " c.last_page, c.source_text_sha256, c.run_id,"
            " to_char(r.started_at, 'YYYY-MM-DD') AS parsed_at"
            " FROM clause c JOIN run r ON r.id = c.run_id"
            " WHERE c.document_id = %s ORDER BY c.ordinal",
            (doc_id,),
        ).fetchall()
    if not rows:
        raise UserError(
            f"Документ {doc_id} не разобран — выполните docreader parse {doc_id}"
        )
    found = conn.execute(
        "SELECT text, text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()
    if found is None or any(r["source_text_sha256"] != found[1] for r in rows):
        raise UserError(f"Разбор устарел: текст изменён — выполните docreader parse {doc_id}")
    return doc, rows, found[0]


def _recognized_pages(conn: psycopg.Connection, doc_id: str) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT page_number FROM page_text WHERE document_id = %s AND source = 'recognized'"
            " ORDER BY page_number",
            (doc_id,),
        )
    ]


def _low_quality_pages(conn: psycopg.Connection, doc_id: str) -> list[int]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT page_number FROM page_flag WHERE document_id = %s AND code = %s"
            " ORDER BY page_number",
            (doc_id, LOW_QUALITY),
        )
    ]


def _any_in(pages: list[int], first: int, last: int) -> bool:
    return any(first <= p <= last for p in pages)


def _head(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()[:_HEAD_CHARS]


def load_outline(conn: psycopg.Connection, seq: int) -> Outline:
    """Every clause record of a parsed document with the `structure` state (task T015)."""
    doc, rows, text = _load_rows(conn, seq)
    doc_id = doc["id"]
    state, reason = conn.execute(
        "SELECT state, reason FROM stage_status WHERE document_id = %s AND stage = %s",
        (doc_id, Stage.STRUCTURE),
    ).fetchone() or ("", None)
    unread = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT page_number FROM page_flag"
            " WHERE document_id = %s AND code = ANY(%s) ORDER BY page_number",
            (doc_id, list(UNREAD_FLAGS)),
        )
    ]
    recognized = _recognized_pages(conn, doc_id)
    low_quality = _low_quality_pages(conn, doc_id)
    records = [
        OutlineRecord(
            id=format_clause_id(doc_id, r["key"]),
            key=r["key"],
            kind=r["kind"],
            number_printed=r["number_printed"],
            depth=r["depth"],
            parent=r["parent_key"],
            title=r["title"],
            section_number=r["section_number"],
            section_title=r["section_title"],
            start=r["start"],
            end=r["end"],
            first_page=r["first_page"],
            last_page=r["last_page"],
            recognized=_any_in(recognized, r["first_page"], r["last_page"]),
            low_quality=_any_in(low_quality, r["first_page"], r["last_page"]),
            head=_head(text[r["start"] : r["end"]]),
        )
        for r in rows
    ]
    return Outline(
        document_id=doc_id,
        state=state,
        reason=reason,
        run_id=rows[0]["run_id"],
        parsed_at=rows[0]["parsed_at"],
        records=records,
        unread_pages=unread,
    )


def load_clause(conn: psycopg.Connection, seq: int, key: str, own: bool) -> ClauseView:
    """The text of a clause: the record and every record under it, or only its own (T015)."""
    doc, rows, text = _load_rows(conn, seq)
    doc_id = doc["id"]
    if not any(r["key"] == key for r in rows):
        raise UserError(
            f"Пункт {format_clause_id(doc_id, key)} не найден — оглавление: docreader outline "
            f"{format_document_id(seq)}"
        )
    if own or key in _NAMED_KEYS:
        chosen = [r for r in rows if r["key"] == key]
    else:
        chosen = [r for r in rows if r["key"] == key or r["key"].startswith(key + ".")]
    recognized = _recognized_pages(conn, doc_id)
    first = min(r["first_page"] for r in chosen)
    last = max(r["last_page"] for r in chosen)
    top = chosen[0]
    return ClauseView(
        id=format_clause_id(doc_id, key),
        section_title=top["section_title"],
        first_page=first,
        last_page=last,
        recognized=_any_in(recognized, first, last),
        records=[
            ClausePart(
                id=format_clause_id(doc_id, r["key"]),
                number_printed=r["number_printed"],
                depth=r["depth"],
                start=r["start"],
                end=r["end"],
                text=text[r["start"] : r["end"]],
            )
            for r in chosen
        ],
    )
