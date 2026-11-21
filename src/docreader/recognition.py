"""`docreader recognize`: recognise scan pages, one transaction per page (feature 13).

Per document: choose the scan pages to recognise (research R-11) → load the engine once
per run, only when a page needs it → for every page: render in memory → dark-pixel share
→ engine → boxes to PDF space → quality and fingerprint → one transaction that upserts
`page_recognition` and, if the result changed, sends `reading` back to `pending`. The
document state is written after its last page. Ctrl-C loses only the current page.
"""

from __future__ import annotations

import platform
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psycopg
from PIL import Image
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from docreader import ocr_engines, runs, stages
from docreader.config import RecognitionSettings, Settings
from docreader.errors import EnvironmentProblem, UserError
from docreader.ids import format_document_id
from docreader.ocr import (
    RecognitionEngine,
    image_box_to_pdf,
    ink_share,
    orientation_score,
    page_quality,
    render_page,
    result_sha256,
)
from docreader.pdfpages import KIND_SCAN, PdfOpenError, open_pdf
from docreader.quality import recognition_flags
from docreader.render import KIND_LABELS
from docreader.stages import Stage, State

READING_RESET_REASON = "распознанный текст изменён"
_MAX_ERROR_LEN = 500

EngineFactory = Callable[[RecognitionSettings, Path], RecognitionEngine]
# doc id, page number, place of the page in this run, pages in this run, seconds
Progress = Callable[[str, int, int, int, float], None]


class DocumentError(Exception):
    """The document cannot be recognised at all; the message is the `failed` reason."""


# --- results (contracts/cli.md, `recognize --json`) ------------------------------------


@dataclass
class PageEntry:
    page: int
    turn: int
    quality: float | None
    ink_share: float | None
    lines: int
    seconds: float
    result_sha256: str
    changed: bool
    error: str | None


@dataclass
class DocumentEntry:
    id: str
    scan_pages: int
    recognized: int = 0
    errors: int = 0
    state: str = State.FAILED
    reason: str | None = None
    reading_reset: bool = False
    seconds: float = 0.0
    flags: dict[str, list[int]] = field(default_factory=dict)
    pages: list[PageEntry] = field(default_factory=list)


@dataclass
class RecognizeResult:
    run_id: int | None = None
    engine: str | None = None
    engine_version: str | None = None
    dpi: int | None = None
    interrupted: bool = False
    documents: list[DocumentEntry] = field(default_factory=list)

    @property
    def totals(self) -> dict:
        flags: dict[str, int] = {}
        for doc in self.documents:
            for code, pages in doc.flags.items():
                flags[code] = flags.get(code, 0) + len(pages)
        return {
            "pages": sum(len(d.pages) for d in self.documents),
            "recognized": sum(d.recognized for d in self.documents),
            "errors": sum(d.errors for d in self.documents),
            "seconds": round(sum(d.seconds for d in self.documents), 3),
            "flags": flags,
        }

    def to_json(self) -> dict:
        data = asdict(self)
        data["totals"] = self.totals
        return data


# --- selection ----------------------------------------------------------------------------


@dataclass
class _Plan:
    """What to do with one document."""

    id: str
    seq: int
    copy_path: str
    page_count: int
    scan_pages: list[int]
    todo: list[int]  # pages to recognise in this run
    stale: list[int]  # rows of pages that are no longer scans
    state: str  # current state of the recognition stage
    reason: str | None


def _load_plan(
    conn: psycopg.Connection, doc: dict, force: bool, pages: Sequence[int] | None
) -> _Plan:
    doc_id = doc["id"]
    scan = [
        row[0]
        for row in conn.execute(
            "SELECT page_number FROM page WHERE document_id = %s AND kind = %s"
            " AND image_coverage > 0 ORDER BY page_number",
            (doc_id, KIND_SCAN),
        )
    ]
    saved = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT page_number, error IS NULL FROM page_recognition WHERE document_id = %s",
            (doc_id,),
        )
    }
    if pages is not None:
        todo = list(pages)
    elif force:
        todo = list(scan)
    else:
        todo = [n for n in scan if not saved.get(n, False)]
    state, reason = conn.execute(
        "SELECT state, reason FROM stage_status WHERE document_id = %s AND stage = %s",
        (doc_id, Stage.RECOGNITION),
    ).fetchone() or (State.PENDING, None)
    return _Plan(
        id=doc_id,
        seq=doc["seq"],
        copy_path=doc["copy_path"],
        page_count=doc["page_count"],
        scan_pages=scan,
        todo=todo,
        stale=sorted(n for n in saved if n not in set(scan)),
        state=state,
        reason=reason,
    )


def _check_pages(conn: psycopg.Connection, plan: _Plan, pages: Sequence[int]) -> None:
    kinds: dict[int, str] = dict(
        conn.execute(
            "SELECT page_number, kind FROM page WHERE document_id = %s", (plan.id,)
        ).fetchall()
    )
    for number in pages:
        if number not in kinds:
            raise UserError(
                f"В документе {plan.id} нет страницы {number} (страниц: {plan.page_count})"
            )
        if number not in plan.scan_pages:
            raise UserError(
                f"Стр. {number} документа {plan.id} — не скан "
                f"(вид: {KIND_LABELS.get(kinds[number], kinds[number])}); "
                "распознаются только страницы-сканы"
            )


def _select(
    conn: psycopg.Connection,
    seqs: Sequence[int] | None,
    all_documents: bool,
    force: bool,
    pages: Sequence[int] | None,
) -> list[_Plan]:
    if pages is not None and (not seqs or len(set(seqs)) != 1):
        raise UserError("--pages указывается для одного документа")
    if seqs and all_documents:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    base = "SELECT id, seq, copy_path, page_count FROM document"
    with conn.cursor(row_factory=dict_row) as cur:
        if seqs:
            found = {r["seq"]: r for r in cur.execute(base + " WHERE seq = ANY(%s)", (list(seqs),))}
            missing = [s for s in seqs if s not in found]
            if missing:
                raise UserError(
                    f"Документ {format_document_id(missing[0])} не найден — "
                    "список документов: docreader list"
                )
            docs = [found[s] for s in dict.fromkeys(seqs)]
        else:
            docs = cur.execute(base + " ORDER BY seq").fetchall()
    plans = [_load_plan(conn, doc, force, pages) for doc in docs]
    if pages is not None:
        _check_pages(conn, plans[0], pages)
    if seqs or all_documents:
        return [p for p in plans if _needs_action(conn, p)]
    return [p for p in plans if p.state != State.DONE or p.todo or p.stale]


def _needs_action(conn: psycopg.Connection, plan: _Plan) -> bool:
    if plan.todo or plan.stale:
        return True
    state, reason = _state_from_rows(conn, plan)
    return (state, reason) != (plan.state, plan.reason)


# --- one page -------------------------------------------------------------------------------


@dataclass
class _PageResult:
    lines: list[dict]
    turn: int
    orientation_unknown: bool
    quality: float | None
    ink_share: float | None
    seconds: float
    error: str | None

    @property
    def sha256(self) -> str:
        return result_sha256(
            self.lines, self.turn, self.orientation_unknown, self.quality, self.ink_share
        )


def _error_text(exc: Exception) -> str:
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    return (f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__)[:_MAX_ERROR_LEN]


def _clockwise(image: Image.Image, turn: int) -> Image.Image:
    """The image turned `turn` degrees clockwise (0, 90, 180 or 270)."""
    if turn == 0:
        return image
    method = {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }[turn]
    return image.transpose(method)


def _recognize_page(
    pdf, number: int, engine: RecognitionEngine, dpi: int, settings: RecognitionSettings
) -> _PageResult:
    started = time.monotonic()
    page = pdf[number - 1]
    try:
        crop = tuple(page.get_cropbox())
        rotation = page.get_rotation() % 360
        image = render_page(page, dpi)
    finally:
        page.close()
    share = ink_share(image)
    try:
        output = engine.recognize(image)
        turn = 0
        orientation_unknown = False
        if output.orientation in (90, 180, 270):
            turn = (360 - output.orientation) % 360
            output = engine.recognize(_clockwise(image, turn))
        elif output.orientation is None and settings.try_rotations:
            # R-6: the trial only when the engine gave no orientation (0° is an answer)
            first_quality = page_quality(output.lines)
            # a page without scored lines is judged by ink (blank or no text), not turned
            if first_quality is not None and first_quality < settings.page_min_quality:
                attempts = [(0, output)]
                for trial in (90, 180, 270):
                    attempts.append((trial, engine.recognize(_clockwise(image, trial))))
                turn, output = attempts[0]
                best = orientation_score(output.lines)
                for trial, candidate in attempts[1:]:
                    score = orientation_score(candidate.lines)
                    if score > best:
                        turn, output, best = trial, candidate, score
                reached = any(
                    (q := page_quality(o.lines)) is not None and q >= settings.page_min_quality
                    for _, o in attempts
                )
                if not reached:
                    turn, output = attempts[0]
                    orientation_unknown = True
    except (KeyboardInterrupt, EnvironmentProblem):
        raise
    except Exception as exc:  # one page must not stop the others (FR-016)
        return _PageResult([], 0, False, None, share, time.monotonic() - started, _error_text(exc))
    scale = dpi / 72
    lines = [
        {
            "i": i,
            "text": line.text,
            "bbox": [
                round(v, 2)
                for v in image_box_to_pdf(
                    line.box, scale=scale, turn=turn, rotation=rotation, crop=crop
                )
            ],
            "confidence": round(float(line.confidence), 4),
        }
        for i, line in enumerate(output.lines)
    ]
    return _PageResult(
        lines=lines,
        turn=turn,
        orientation_unknown=orientation_unknown,
        quality=page_quality(output.lines),
        ink_share=share,
        seconds=time.monotonic() - started,
        error=None,
    )


def _write_page(
    conn: psycopg.Connection,
    run_id: int,
    doc_id: str,
    number: int,
    engine: RecognitionEngine,
    dpi: int,
    result: _PageResult,
) -> tuple[bool, bool]:
    """Upsert one page in its own transaction; (fingerprint changed, reading was reset)."""
    sha = result.sha256
    with conn.transaction():
        stages.lock(conn, doc_id, Stage.RECOGNITION)
        previous = conn.execute(
            "SELECT result_sha256 FROM page_recognition"
            " WHERE document_id = %s AND page_number = %s FOR UPDATE",
            (doc_id, number),
        ).fetchone()
        conn.execute(
            "INSERT INTO page_recognition (document_id, page_number, engine, engine_version,"
            " dpi, turn, orientation_unknown, lines, quality, ink_share, result_sha256,"
            " seconds, error, run_id) VALUES"
            " (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
            " ON CONFLICT (document_id, page_number) DO UPDATE SET"
            " engine = EXCLUDED.engine, engine_version = EXCLUDED.engine_version,"
            " dpi = EXCLUDED.dpi, turn = EXCLUDED.turn,"
            " orientation_unknown = EXCLUDED.orientation_unknown, lines = EXCLUDED.lines,"
            " quality = EXCLUDED.quality, ink_share = EXCLUDED.ink_share,"
            " result_sha256 = EXCLUDED.result_sha256, seconds = EXCLUDED.seconds,"
            " error = EXCLUDED.error, run_id = EXCLUDED.run_id, recognized_at = now()",
            (
                doc_id,
                number,
                engine.name,
                engine.version,
                dpi,
                result.turn,
                result.orientation_unknown,
                Jsonb(result.lines),
                result.quality,
                result.ink_share,
                sha,
                round(result.seconds, 3),
                result.error,
                run_id,
            ),
        )
        changed = previous is None or previous[0] != sha
        reset = changed and stages.reset_stage(
            conn, doc_id, Stage.READING, READING_RESET_REASON, run_id
        )
    return changed, reset


# --- document state -------------------------------------------------------------------------


def _state_from_rows(conn: psycopg.Connection, plan: _Plan) -> tuple[State, str | None]:
    """State of the recognition stage from the stored rows of the document's scan pages."""
    rows: dict[int, str | None] = dict(
        conn.execute(
            "SELECT page_number, error FROM page_recognition WHERE document_id = %s",
            (plan.id,),
        ).fetchall()
    )
    missing = [n for n in plan.scan_pages if n not in rows]
    if missing:
        return State.PENDING, None
    by_error: dict[str, list[int]] = {}
    for number in plan.scan_pages:
        error = rows[number]
        if error is not None:
            by_error.setdefault(error, []).append(number)
    if not by_error:
        return State.DONE, None
    parts = [
        f"стр. {', '.join(map(str, pages))}: ошибка распознавания — {error}"
        for error, pages in by_error.items()
    ]
    return State.NEEDS_REVIEW, "; ".join(parts)


def _finish_document(
    conn: psycopg.Connection, run_id: int, plan: _Plan
) -> tuple[State, str | None]:
    with conn.transaction():
        stages.lock(conn, plan.id, Stage.RECOGNITION)
        if plan.stale:
            conn.execute(
                "DELETE FROM page_recognition WHERE document_id = %s AND page_number = ANY(%s)",
                (plan.id, plan.stale),
            )
        state, reason = _state_from_rows(conn, plan)
        stages.set_state(conn, plan.id, Stage.RECOGNITION, state, reason, run_id)
    return state, reason


def _mark_failed(conn: psycopg.Connection, run_id: int, doc_id: str, reason: str) -> None:
    with conn.transaction():
        stages.set_state(conn, doc_id, Stage.RECOGNITION, State.FAILED, reason, run_id)


# --- command --------------------------------------------------------------------------------


class _Run:
    """The run record and the engine, loaded at the first page that needs it."""

    def __init__(
        self,
        conn: psycopg.Connection,
        settings: Settings,
        factory: EngineFactory,
        label: str | None,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self.factory = factory
        self.engine: RecognitionEngine | None = None
        self.run_settings = settings.settings_for_run()
        self.run_settings["recognition"]["engine_version"] = None
        self.run_settings["recognition"]["platform"] = {
            "system": sys.platform,
            "machine": platform.machine(),
        }
        self.run_id = runs.start_run(conn, stages.RunStage.RECOGNITION, self.run_settings, label)

    def get_engine(self) -> RecognitionEngine:
        if self.engine is None:
            self.engine = self.factory(self.settings.recognition, self.settings.data_dir)
            self.run_settings["recognition"]["engine_version"] = self.engine.version
            self.conn.execute(
                "UPDATE run SET model = %s, settings = %s WHERE id = %s",
                (
                    f"{self.engine.name} {self.engine.version}",
                    Jsonb(self.run_settings),
                    self.run_id,
                ),
            )
        return self.engine


def _recognize_document(run: _Run, plan: _Plan, progress: Progress | None) -> DocumentEntry:
    conn, settings = run.conn, run.settings
    dpi = settings.recognition.dpi
    entry = DocumentEntry(id=plan.id, scan_pages=len(plan.scan_pages))
    if plan.todo:
        path = settings.data_dir / plan.copy_path
        if not path.is_file():
            raise DocumentError(f"файл копии не найден — проверьте docreader verify {plan.id}")
        try:
            pdf = open_pdf(path)
        except PdfOpenError as exc:
            raise DocumentError(f"копия не открывается: {exc.reason}") from exc
        try:
            if len(pdf) != plan.page_count:
                raise DocumentError(
                    f"в копии {len(pdf)} стр., в реестре {plan.page_count} — "
                    f"проверьте docreader verify {plan.id}"
                )
            engine = run.get_engine()
            for done, number in enumerate(plan.todo, 1):
                result = _recognize_page(pdf, number, engine, dpi, settings.recognition)
                changed, reset = _write_page(
                    conn, run.run_id, plan.id, number, engine, dpi, result
                )
                entry.reading_reset = entry.reading_reset or reset
                entry.seconds += result.seconds
                if result.error is None:
                    entry.recognized += 1
                    for flag in recognition_flags(
                        result.lines,
                        result.quality,
                        result.ink_share,
                        result.orientation_unknown,
                        settings.recognition,
                    ):
                        entry.flags.setdefault(flag.code, []).append(number)
                else:
                    entry.errors += 1
                entry.pages.append(
                    PageEntry(
                        page=number,
                        turn=result.turn,
                        quality=result.quality,
                        ink_share=result.ink_share,
                        lines=len(result.lines),
                        seconds=round(result.seconds, 3),
                        result_sha256=result.sha256,
                        changed=changed,
                        error=result.error,
                    )
                )
                if progress is not None:
                    progress(plan.id, number, done, len(plan.todo), result.seconds)
        finally:
            pdf.close()
    entry.seconds = round(entry.seconds, 3)
    entry.state, entry.reason = _finish_document(conn, run.run_id, plan)
    return entry


def recognize_documents(
    conn: psycopg.Connection,
    settings: Settings,
    seqs: Sequence[int] | None,
    *,
    all_documents: bool = False,
    force: bool = False,
    pages: Sequence[int] | None = None,
    label: str | None = None,
    engine_factory: EngineFactory | None = None,
    progress: Progress | None = None,
) -> RecognizeResult:
    """Recognise the chosen documents (contracts/cli.md, `recognize`).

    Selection: `seqs` → those documents; `all_documents` → every document; neither →
    documents whose stage is not `done` or that have a scan page without a successful
    result. Pages: without a successful result; all scan pages with `force`; exactly
    `pages` (one document only). Nothing to do → a result without a run.
    """
    plans = _select(conn, seqs, all_documents, force, pages)
    result = RecognizeResult()
    if not plans:
        return result
    factory = engine_factory if engine_factory is not None else ocr_engines.load_engine
    run = _Run(conn, settings, factory, label)
    result.run_id = run.run_id
    try:
        for plan in plans:
            try:
                entry = _recognize_document(run, plan, progress)
            except (KeyboardInterrupt, EnvironmentProblem):
                raise
            except Exception as exc:  # one document must not stop the others (FR-016)
                reason = (
                    str(exc)
                    if isinstance(exc, DocumentError)
                    else f"ошибка распознавания документа: {_error_text(exc)}"
                )
                _mark_failed(conn, run.run_id, plan.id, reason)
                entry = DocumentEntry(id=plan.id, scan_pages=len(plan.scan_pages), reason=reason)
            result.documents.append(entry)
    except KeyboardInterrupt:
        # the current page was not written: its transaction() block rolled back
        result.interrupted = True
    finally:
        runs.finish_run(conn, run.run_id)
        if run.engine is not None:
            result.engine, result.engine_version = run.engine.name, run.engine.version
            result.dpi = settings.recognition.dpi
    return result
