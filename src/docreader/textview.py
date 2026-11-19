"""Loading read text for `docreader text` (contracts/cli.md; tasks T017, T037, T050)."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, field

import psycopg
from psycopg.rows import dict_row

from docreader.config import Settings
from docreader.db import fetch_row
from docreader.errors import UserError
from docreader.ids import format_document_id
from docreader.quality import FLAG_ORDER, recognition_flags
from docreader.registry import _not_found, find_document
from docreader.stages import Stage, State
from docreader.textnorm import is_empty_phrase, locate, normalize_chars


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
    "source", "flags": [{"code", "reason"}], "lines": [<page_text.lines elements>]}]};
    a recognised page also has `engine`, `engine_version`, `quality`.
    """
    doc = _require_read(conn, seq)
    doc_id = doc["id"]
    if not 1 <= page <= doc["page_count"]:
        raise UserError(f"В документе {doc_id} нет страницы {page} (страниц: {doc['page_count']})")
    with conn.cursor(row_factory=dict_row) as cur:
        row = cur.execute(
            "SELECT rotation, has_table, lines, source FROM page_text"
            " WHERE document_id = %s AND page_number = %s",
            (doc_id, page),
        ).fetchone()
    flags = _flags_by_page(conn, doc_id).get(page, [])
    if row is None:
        raise UserError(f"Страница {page} документа {doc_id} не прочитана")
    view = {
        "page": page,
        "rotation": row["rotation"],
        "has_table": row["has_table"],
        "source": row["source"],
        "flags": flags,
        "lines": row["lines"],
    }
    if row["source"] == "recognized":
        with conn.cursor(row_factory=dict_row) as cur:
            rec = cur.execute(
                "SELECT engine, engine_version, quality FROM page_recognition"
                " WHERE document_id = %s AND page_number = %s",
                (doc_id, page),
            ).fetchone()
        if rec is not None:
            view.update(rec)
    return {"id": doc_id, "pages": [view]}


_CONTEXT_CHARS = 30
_REMOVED_ROLES = ("header", "footer", "page_number")


def _covered_lines(
    spans: list[tuple[int, int, int, int]], ends: list[int], start: int, end: int
) -> list[tuple[int, int]]:
    """(page, line) of every `text_span` that `[start, end)` overlaps, in text order."""
    covered = []
    k = bisect_right(ends, start)  # the first span that ends after `start`
    while k < len(spans) and spans[k][0] < end:
        covered.append((spans[k][2], spans[k][3]))
        k += 1
    return covered


def find_phrase(
    conn: psycopg.Connection, seq: int, phrase: str, *, with_context: bool = False
) -> dict:
    """Search a phrase in the clean text and in removed page elements (tasks T037, T066).

    Matching is `textnorm.locate`: the comparison form, so a phrase across a line or page
    break, «ё»/«е», dash and quote variants are found. `{"id", "phrase" (normalized),
    "matches": [{"start", "end", "page", "line", "bbox", "role", "lines": [{"page",
    "line", "bbox"}]}]}`; `page`, `line`, `bbox` are those of the first line, `lines`
    lists every line the match covers. Clean-text matches first (by start), then matches
    in lines with role header/footer/page_number (by page and line; offsets inside the
    line). With `with_context` every match also gets a `context` string (up to 30
    characters around it) for text rendering.
    """
    doc = _require_read(conn, seq)
    doc_id = doc["id"]
    if is_empty_phrase(phrase):
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
    spans = conn.execute(
        "SELECT start, end_, page_number, line_index FROM text_span"
        " WHERE document_id = %s ORDER BY start",
        (doc_id,),
    ).fetchall()
    ends = [span[1] for span in spans]

    def context(source: str, start: int, end: int) -> dict:
        if not with_context:
            return {}
        before = source[max(0, start - _CONTEXT_CHARS) : start]
        after = source[end : end + _CONTEXT_CHARS]
        return {"context": f"{before}{source[start:end]}{after}".replace("\n", " ")}

    def line_ref(page: int, index: int) -> dict:
        bbox = page_lines.get(page, {}).get(index, {}).get("bbox")
        return {"page": page, "line": index, "bbox": bbox}

    matches: list[dict] = []
    for start, end in locate(text, phrase):
        covered = _covered_lines(spans, ends, start, end)
        if not covered:
            continue
        page, index = covered[0]
        line = page_lines.get(page, {}).get(index, {})
        matches.append(
            {
                "start": start,
                "end": end,
                "page": page,
                "line": index,
                "bbox": line.get("bbox"),
                "role": line.get("role", "body"),
                "lines": [line_ref(p, i) for p, i in covered],
                **context(text, start, end),
            }
        )
    for page in sorted(page_lines):
        for index in sorted(page_lines[page]):
            line = page_lines[page][index]
            if line.get("role") not in _REMOVED_ROLES:
                continue
            for start, end in locate(line["text"], phrase):
                matches.append(
                    {
                        "start": start,
                        "end": end,
                        "page": page,
                        "line": index,
                        "bbox": line.get("bbox"),
                        "role": line["role"],
                        "lines": [line_ref(page, index)],
                        **context(line["text"], start, end),
                    }
                )
    return {"id": doc_id, "phrase": normalize_chars(phrase), "matches": matches}


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
        " JOIN stage_status s ON s.document_id = d.id AND s.stage = %(stage)s"
        " LEFT JOIN (SELECT document_id,"
        "   count(*) FILTER (WHERE jsonb_array_length(lines) > 0) AS read,"
        "   count(*) FILTER (WHERE has_table) AS tables"
        "   FROM page_text GROUP BY document_id) pt ON pt.document_id = d.id"
        f" LEFT JOIN (SELECT document_id, {flag_columns}"
        "   FROM page_flag GROUP BY document_id) pf ON pf.document_id = d.id"
        " WHERE s.state <> %(pending)s ORDER BY d.seq",
        {"stage": Stage.READING, "pending": State.PENDING},
    ).fetchall()
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


# --- recognition report (feature 13, US7, FR-018; task T047) -------------------------------

REPORT_FLAGS: tuple[str, ...] = ("low_recognition_quality", "scan_no_text", "empty")
ERROR_CODE = "recognition_error"


def _zero_flags() -> dict[str, int]:
    return dict.fromkeys(REPORT_FLAGS, 0)


@dataclass
class RecognitionDocument:
    id: str
    name: str
    scan_pages: int
    recognized: int
    errors: int
    flags: dict[str, int]
    mean_quality: float | None
    seconds: float
    state: str


@dataclass
class RecognitionTotals:
    scan_pages: int
    recognized: int
    errors: int
    flags: dict[str, int]
    mean_quality: float | None
    seconds: float


@dataclass
class RecognitionReport:
    documents: list[RecognitionDocument] = field(default_factory=list)
    totals: RecognitionTotals = field(
        default_factory=lambda: RecognitionTotals(0, 0, 0, _zero_flags(), None, 0.0)
    )

    def to_json(self) -> dict:
        return {"documents": [asdict(d) for d in self.documents], "totals": asdict(self.totals)}


@dataclass(frozen=True)
class ReviewPage:
    id: str
    page: int
    code: str
    reason: str
    quality: float | None


_SCAN_PAGE_ROWS = (
    "SELECT d.id, d.original_name, p.page_number, pr.lines, pr.quality, pr.ink_share,"
    " pr.orientation_unknown, pr.seconds, pr.error, s.state"
    " FROM document d"
    " JOIN page p ON p.document_id = d.id AND p.kind = 'scan' AND p.image_coverage > 0"
    " LEFT JOIN page_recognition pr"
    "   ON pr.document_id = p.document_id AND pr.page_number = p.page_number"
    " LEFT JOIN stage_status s ON s.document_id = d.id AND s.stage = %s"
    " ORDER BY d.seq, p.page_number"
)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def recognition_report(conn: psycopg.Connection, settings: Settings) -> RecognitionReport:
    """Per-document recognition counts over documents with scan pages (US7, FR-018).

    Flags are recomputed from the stored values with the current thresholds. Pages
    without a recognition row count as scan pages only. No text, only numbers.
    """
    rows = conn.execute(_SCAN_PAGE_ROWS, (Stage.RECOGNITION,)).fetchall()
    documents: list[RecognitionDocument] = []
    qualities: dict[str, list[float]] = {}
    total_flags = _zero_flags()
    by_doc: dict[str, RecognitionDocument] = {}
    for doc_id, name, _page, lines, quality, ink, unknown, seconds, error, state in rows:
        doc = by_doc.get(doc_id)
        if doc is None:
            doc = RecognitionDocument(
                doc_id, name, 0, 0, 0, _zero_flags(), None, 0.0, state or State.PENDING.value
            )
            by_doc[doc_id] = doc
            documents.append(doc)
        doc.scan_pages += 1
        if lines is None:
            continue  # not recognised yet
        doc.seconds += seconds
        if error is not None:
            doc.errors += 1
            continue
        doc.recognized += 1
        if quality is not None:
            qualities.setdefault(doc_id, []).append(quality)
        for flag in recognition_flags(lines, quality, ink, unknown, settings.recognition):
            if flag.code in doc.flags:
                doc.flags[flag.code] += 1
                total_flags[flag.code] += 1
    for doc in documents:
        doc.mean_quality = _mean(qualities.get(doc.id, []))
        doc.seconds = round(doc.seconds, 1)
    all_qualities = [q for values in qualities.values() for q in values]
    totals = RecognitionTotals(
        scan_pages=sum(d.scan_pages for d in documents),
        recognized=sum(d.recognized for d in documents),
        errors=sum(d.errors for d in documents),
        flags=total_flags,
        mean_quality=_mean(all_qualities),
        seconds=round(sum(d.seconds for d in documents), 1),
    )
    return RecognitionReport(documents, totals)


def recognition_review(conn: psycopg.Connection, settings: Settings) -> list[ReviewPage]:
    """Pages to look at: engine errors first, then low quality / no text, worst first."""
    errors: list[ReviewPage] = []
    others: list[tuple[float, ReviewPage]] = []
    for doc_id, _name, page, lines, quality, ink, unknown, _sec, error, _state in conn.execute(
        _SCAN_PAGE_ROWS, (Stage.RECOGNITION,)
    ):
        if lines is None:
            continue
        if error is not None:
            errors.append(ReviewPage(doc_id, page, ERROR_CODE, error, None))
            continue
        for flag in recognition_flags(lines, quality, ink, unknown, settings.recognition):
            if flag.code in ("low_recognition_quality", "scan_no_text"):
                key = -1.0 if quality is None else float(quality)
                others.append((key, ReviewPage(doc_id, page, flag.code, flag.reason, quality)))
    # the query is ordered by document seq and page; the sort is stable
    others.sort(key=lambda item: item[0])
    return errors + [page for _key, page in others]
