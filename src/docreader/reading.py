"""`docreader read`: choose documents, read pages, write results (R-9, R-10, task T015).

Per document: page facts from the registry → the copy is opened read-only → for every
page either a skip flag (scan, blank) or chars → lines → flags → the document text →
one transaction that replaces the previous result (data-model «Порядок записи»).
A failing document gets the state `failed` and the others go on.
"""

from __future__ import annotations

import importlib.metadata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
import pypdfium2 as pdfium
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from docreader import runs
from docreader.cleanup import DocumentText, PageLines, build_document_text, mark_page_furniture
from docreader.config import Settings
from docreader.errors import UserError
from docreader.ids import format_document_id
from docreader.pagetext import Line, layout_page, read_page_chars, read_page_rules
from docreader.pdfpages import PdfOpenError, open_pdf
from docreader.quality import (
    FLAG_ORDER,
    Flag,
    PageInfo,
    content_flags,
    count_map_errors,
    document_state,
    layout_flag,
    skip_flag,
)

READING_STAGE = "reading"
# Stages that work on the read text; reset when the text changes (FR-012, task T029).
LATER_STAGES = ("structure", "extraction", "checks", "indexing")
TEXT_CHANGED_REASON = "текст изменён"

STATE_FAILED = "failed"
_STATES = ("done", "needs_review", STATE_FAILED)
_MAX_ERROR_LEN = 500


class ReadingError(Exception):
    """A document cannot be read; the message is the Russian `failed` reason."""


@dataclass
class PageResult:
    number: int
    rotation: int
    width: float
    height: float
    lines: list[Line] = field(default_factory=list)
    flags: list[Flag] = field(default_factory=list)
    has_table: bool = False
    display_height: float | None = None  # page height after /Rotate; None: same as `height`
    ends_in_columns: bool = False


WordCheck = Callable[[str], bool]
DICTIONARY_PACKAGE = "pymorphy3-dicts-ru"


def load_dictionary() -> tuple[WordCheck, str]:
    """The pymorphy3 word check for hyphenation (R-6), loaded once per run, and its version."""
    import pymorphy3  # loads the dictionary package from disk; no network

    analyzer = pymorphy3.MorphAnalyzer()
    return analyzer.word_is_known, importlib.metadata.version(DICTIONARY_PACKAGE)


# --- selection -------------------------------------------------------------------------


def _select_documents(
    conn: psycopg.Connection, seqs: Sequence[int] | None, all_documents: bool
) -> list[dict]:
    base = "SELECT d.id, d.seq, d.copy_path, d.page_count FROM document d"
    with conn.cursor(row_factory=dict_row) as cur:
        if seqs:
            found = {
                row["seq"]: row
                for row in cur.execute(base + " WHERE d.seq = ANY(%s)", (list(seqs),))
            }
            missing = [seq for seq in seqs if seq not in found]
            if missing:
                raise UserError(
                    f"Документ {format_document_id(missing[0])} не найден — "
                    "список документов: docreader list"
                )
            # Explicit order, each document once.
            return [found[seq] for seq in dict.fromkeys(seqs)]
        if all_documents:
            return cur.execute(base + " ORDER BY d.seq").fetchall()
        return cur.execute(
            base + " JOIN stage_status s ON s.document_id = d.id AND s.stage = %s"
            " WHERE s.state IN ('pending', 'failed') ORDER BY d.seq",
            (READING_STAGE,),
        ).fetchall()


# --- reading the copy --------------------------------------------------------------------


def _page_infos(conn: psycopg.Connection, doc_id: str) -> list[PageInfo]:
    rows = conn.execute(
        "SELECT page_number, kind, char_count, image_coverage FROM page"
        " WHERE document_id = %s ORDER BY page_number",
        (doc_id,),
    ).fetchall()
    return [PageInfo(*row) for row in rows]


def _read_page(
    page: pdfium.PdfPage,
    info: PageInfo,
    settings: Settings,
    continues_columns: bool = False,
) -> PageResult:
    left, bottom, right, top = page.get_cropbox()
    result = PageResult(
        number=info.page_number,
        rotation=page.get_rotation() % 360,
        width=right - left,
        height=top - bottom,
    )
    result.display_height = result.width if result.rotation in (90, 270) else result.height
    flag = skip_flag(info)
    if flag is not None:
        result.flags.append(flag)
        return result
    chars = read_page_chars(page)
    layout = layout_page(
        chars,
        rotation=result.rotation,
        width=result.width,
        height=result.height,
        rules=read_page_rules(page),
        settings=settings.reading,
        continues_columns=continues_columns,
    )
    result.lines = layout.lines
    result.has_table = layout.has_table
    result.ends_in_columns = layout.ends_in_columns
    text = "\n".join(line.text for line in result.lines)
    result.flags = content_flags(
        info,
        text,
        settings.reading,
        settings.text_min_chars,
        map_errors=count_map_errors(chars),
    )
    flag = layout_flag(
        rotated_lines=layout.rotated_lines, unresolved_lines=layout.unresolved_lines
    )
    if flag is not None:
        result.flags.append(flag)
    return result


def read_copy(
    path: Path, infos: Sequence[PageInfo], doc_id: str, settings: Settings
) -> list[PageResult]:
    """Read every page of the copy; the file is only read, never written (FR-014)."""
    if not path.is_file():
        raise ReadingError(f"файл копии не найден — проверьте docreader verify {doc_id}")
    try:
        pdf = open_pdf(path)
    except PdfOpenError as exc:
        raise ReadingError(f"копия не открывается: {exc.reason}") from exc
    try:
        if len(pdf) != len(infos):
            raise ReadingError(
                f"в копии {len(pdf)} стр., в реестре {len(infos)} — "
                f"проверьте docreader verify {doc_id}"
            )
        results: list[PageResult] = []
        continues = False
        for info in infos:
            page = pdf[info.page_number - 1]
            try:
                result = _read_page(page, info, settings, continues)
            finally:
                page.close()
            results.append(result)
            if skip_flag(info) is None:  # skipped pages are not read and keep the state
                continues = result.ends_in_columns
        return results
    finally:
        pdf.close()


# --- writing ------------------------------------------------------------------------------


def _write_result(
    conn: psycopg.Connection,
    run_id: int,
    doc_id: str,
    pages: Sequence[PageResult],
    text: DocumentText,
    state: str,
    reason: str | None,
) -> bool:
    """Replace the reading result of one document in one transaction; True if text changed."""
    conn.commit()  # end the implicit read transaction: the block below is a real one
    with conn.transaction():
        # (1) lock the stage row (serialises concurrent reads) and get the old fingerprint
        conn.execute(
            "SELECT 1 FROM stage_status WHERE document_id = %s AND stage = %s FOR UPDATE",
            (doc_id, READING_STAGE),
        )
        previous = conn.execute(
            "SELECT text_sha256 FROM document_text WHERE document_id = %s FOR UPDATE",
            (doc_id,),
        ).fetchone()

        # (2) drop the previous result (page_flag goes with page_text)
        conn.execute("DELETE FROM page_text WHERE document_id = %s", (doc_id,))
        conn.execute("DELETE FROM text_span WHERE document_id = %s", (doc_id,))

        # (3) the new result
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO page_text (document_id, page_number, rotation, width, height,"
                " lines, has_table, run_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        doc_id,
                        p.number,
                        p.rotation,
                        p.width,
                        p.height,
                        Jsonb([line.to_json() for line in p.lines]),
                        p.has_table,
                        run_id,
                    )
                    for p in pages
                ],
            )
            cur.executemany(
                "INSERT INTO page_flag (document_id, page_number, code, reason)"
                " VALUES (%s, %s, %s, %s)",
                [(doc_id, p.number, f.code, f.reason) for p in pages for f in p.flags],
            )
            cur.execute(
                "INSERT INTO document_text (document_id, text, text_sha256, read_pages, run_id)"
                " VALUES (%s, %s, %s, %s, %s) ON CONFLICT (document_id) DO UPDATE SET"
                " text = EXCLUDED.text, text_sha256 = EXCLUDED.text_sha256,"
                " read_pages = EXCLUDED.read_pages, run_id = EXCLUDED.run_id",
                (doc_id, text.text, text.sha256, text.read_pages, run_id),
            )
            cur.executemany(
                "INSERT INTO text_span (document_id, start, end_, page_number, line_index)"
                " VALUES (%s, %s, %s, %s, %s)",
                [(doc_id, s.start, s.end, s.page_number, s.line_index) for s in text.spans],
            )

        # (4) a changed text makes the results of later stages stale (FR-012, R-9);
        # they are kept until the stage is rerun. The first read changes nothing.
        text_changed = previous is not None and previous[0] != text.sha256
        if text_changed:
            conn.execute(
                "UPDATE stage_status SET state = 'pending', reason = %s, run_id = %s,"
                " updated_at = now()"
                " WHERE document_id = %s AND stage = ANY(%s) AND state <> 'pending'",
                (TEXT_CHANGED_REASON, run_id, doc_id, list(LATER_STAGES)),
            )

        # (5) the reading stage
        conn.execute(
            "UPDATE stage_status SET state = %s, reason = %s, run_id = %s, updated_at = now()"
            " WHERE document_id = %s AND stage = %s",
            (state, reason, run_id, doc_id, READING_STAGE),
        )
    return text_changed


def _mark_failed(conn: psycopg.Connection, run_id: int, doc_id: str, reason: str) -> None:
    conn.rollback()
    with conn.transaction():
        conn.execute(
            "UPDATE stage_status SET state = %s, reason = %s, run_id = %s, updated_at = now()"
            " WHERE document_id = %s AND stage = %s",
            (STATE_FAILED, reason, run_id, doc_id, READING_STAGE),
        )


def _error_reason(exc: Exception) -> str:
    if isinstance(exc, ReadingError):
        return str(exc)
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    text = f"ошибка чтения: {type(exc).__name__}" + (f": {detail}" if detail else "")
    return text[:_MAX_ERROR_LEN]


def _flag_pages(pages: Sequence[PageResult]) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for page in pages:
        for flag in page.flags:
            found.setdefault(flag.code, []).append(page.number)
    return {code: sorted(found[code]) for code in FLAG_ORDER if code in found}


def clean_document_text(
    pages: Sequence[PageResult], settings: Settings, is_known: WordCheck | None
) -> DocumentText:
    """Mark headers, footers and page numbers, then build the clean text (R-4, R-6)."""
    mark_page_furniture(
        [
            PageLines(
                p.number,
                p.height if p.display_height is None else p.display_height,
                p.lines,
            )
            for p in pages
        ], settings.reading
    )
    return build_document_text([(p.number, p.lines) for p in pages], is_known)


def _read_document(
    conn: psycopg.Connection,
    settings: Settings,
    run_id: int,
    doc: dict,
    is_known: WordCheck | None,
) -> dict:
    doc_id = doc["id"]
    entry = {
        "id": doc_id,
        "pages": doc["page_count"],
        "state": STATE_FAILED,
        "reason": None,
        "text_changed": False,
        "flags": {},
    }
    try:
        infos = _page_infos(conn, doc_id)
        conn.commit()
        pages = read_copy(settings.data_dir / doc["copy_path"], infos, doc_id, settings)
        text = clean_document_text(pages, settings, is_known)
        state, reason = document_state({p.number: p.flags for p in pages}, text.read_pages)
        entry["text_changed"] = _write_result(conn, run_id, doc_id, pages, text, state, reason)
        entry.update(state=state, reason=reason, flags=_flag_pages(pages))
    except Exception as exc:  # one document must not stop the others
        reason = _error_reason(exc)
        _mark_failed(conn, run_id, doc_id, reason)
        entry["reason"] = reason
    return entry


# --- command -------------------------------------------------------------------------------


def read_documents(
    conn: psycopg.Connection,
    settings: Settings,
    seqs: Sequence[int] | None,
    *,
    all_documents: bool = False,
    label: str | None = None,
) -> dict:
    """Read the chosen documents; return the result per contracts/cli.md.

    Selection: `seqs` given → those documents in any state; `all_documents` → every
    document; neither → documents whose `reading` stage is `pending` or `failed`.

    Result: `{"run_id": int | None, "documents": [{"id", "pages", "state", "reason",
    "text_changed", "flags": {code: [page, ...]}}], "totals": {"done", "needs_review",
    "failed"}, "interrupted": bool}`. Nothing to read → `run_id = None`, no documents.
    """
    if seqs and all_documents:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    docs = _select_documents(conn, seqs, all_documents)
    conn.commit()

    result: dict = {
        "run_id": None,
        "documents": [],
        "totals": dict.fromkeys(_STATES, 0),
        "interrupted": False,
    }
    if not docs:
        return result

    is_known, dictionary_version = load_dictionary()
    run_settings = settings.settings_for_run()
    run_settings["reading"]["dictionary"] = dictionary_version
    run_id = runs.start_run(conn, READING_STAGE, run_settings, label)
    result["run_id"] = run_id
    try:
        for doc in docs:
            entry = _read_document(conn, settings, run_id, doc, is_known)
            result["documents"].append(entry)
            result["totals"][entry["state"]] += 1
    except KeyboardInterrupt:
        conn.rollback()  # the current document is not written
        result["interrupted"] = True
    runs.finish_run(conn, run_id)
    return result
