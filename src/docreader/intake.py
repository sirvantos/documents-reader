"""`docreader add`: walk the input paths and register each file atomically.

Order per file (plan «Ключевые решения» 1, research R-4):
sniff → SHA-256 → lookup by fingerprint → open PDF + page metrics → copy to a temp
file, fsync, re-hash, rename to originals/<sha256>.pdf → one transaction
(counter FOR UPDATE, document, pages, five stage_status rows) → warnings.

The copy is written before the transaction, so a failure in between leaves only a
file named by its hash, which the next run verifies and reuses. A document is never
partially registered.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg

from docreader import db, runs
from docreader.config import Settings
from docreader.errors import EnvironmentProblem, UserError
from docreader.ids import format_document_id
from docreader.pdfpages import KINDS, KIND_SCAN, KIND_SCAN_WITH_TEXT, PageMetrics, PdfOpenError
from docreader.pdfpages import analyse_pdf, classify
from docreader.sniff import sniff

INTAKE_STAGE = "intake"
CHUNK = 1024 * 1024

REASON_CHANGED = "файл изменился во время добавления"
REASON_SYMLINK_DIR = "символическая ссылка на папку не обходится"
REASON_HIDDEN_DIR = "скрытая или служебная папка не обходится"
REASON_SERVICE_DIR = "служебная папка программы не обходится"
REASON_UNREADABLE = "файл не читается"


@dataclass
class IntakeOutcome:
    report: dict
    report_path: Path
    interrupted: bool


@dataclass
class _Input:
    """One entry of the walk: a regular file, or something reported without processing."""

    path: Path
    reject_code: str | None = None
    reject_reason: str | None = None


@dataclass
class _Context:
    conn: psycopg.Connection
    settings: Settings
    run_id: int
    note: str | None
    results: list[dict] = field(default_factory=list)


# --- walking the input ----------------------------------------------------------------


def service_dirs(settings: Settings) -> tuple[Path, ...]:
    """Folders the program writes itself; `add` never takes files from them."""
    return (settings.originals_dir.resolve(), settings.reports_dir.resolve())


def collect_inputs(
    paths: Sequence[str | os.PathLike], skip_dirs: Sequence[Path] = ()
) -> list[_Input]:
    """Expand files and folders (recursively, sorted by path) into input entries.

    `skip_dirs` (resolved paths) are never walked: a folder equal to one of them is
    reported as rejected, and an input path inside one of them is a user error.
    """
    resolved = []
    for raw in paths:
        p = Path(raw).expanduser()
        if not p.exists():
            raise UserError(f"Путь не найден: {raw} — проверьте путь к файлу или папке")
        real = p.resolve()
        for skip in skip_dirs:
            if real == skip or real.is_relative_to(skip):
                raise UserError(
                    f"Путь {raw} — служебная папка программы ({skip}) — "
                    "укажите папку с договорами"
                )
        resolved.append(p.absolute())

    seen: set[Path] = set()
    entries: list[_Input] = []
    for p in resolved:
        for entry in _walk(p, skip_dirs) if p.is_dir() else [_Input(p.resolve())]:
            if entry.path not in seen:
                seen.add(entry.path)
                entries.append(entry)
    return entries


def _walk(root: Path, skip_dirs: Sequence[Path] = ()) -> list[_Input]:
    found: list[_Input] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        for name in list(dirnames):
            sub = base / name
            if sub.is_symlink():
                found.append(_Input(sub.absolute(), "unsupported", REASON_SYMLINK_DIR))
                dirnames.remove(name)
            elif sub.resolve() in skip_dirs:
                found.append(_Input(sub.resolve(), "service_dir", REASON_SERVICE_DIR))
                dirnames.remove(name)
            elif name.startswith("."):
                found.append(_Input(sub.resolve(), "hidden", REASON_HIDDEN_DIR))
                dirnames.remove(name)
        for name in filenames:
            f = base / name
            if f.is_file():  # follows symlinks to files
                found.append(_Input(f.resolve()))
            else:
                found.append(_Input(f.absolute(), "unsupported", REASON_UNREADABLE))
    return sorted(found, key=lambda e: str(e.path))


# --- per-file steps ---------------------------------------------------------------------


def _sha256_of(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _place_copy(source: Path, sha256: str, originals: Path) -> Path | None:
    """Ensure originals/<sha256>.pdf holds the bytes of `source`.

    Returns the copy's path, or None when the source no longer matches `sha256`.
    """
    originals.mkdir(parents=True, exist_ok=True)
    final = originals / f"{sha256}.pdf"
    if _copy_is_intact(final, sha256):
        return final  # left by an earlier interrupted or removed run

    fd, tmp_name = tempfile.mkstemp(dir=originals, prefix=".tmp-", suffix=".pdf")
    tmp = Path(tmp_name)
    try:
        h = hashlib.sha256()
        with os.fdopen(fd, "wb") as out, source.open("rb") as src:
            while chunk := src.read(CHUNK):
                h.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if h.hexdigest() != sha256:
            return None
        tmp.chmod(0o444)
        os.replace(tmp, final)
        _fsync_dir(originals)
        return final
    finally:
        tmp.unlink(missing_ok=True)


def _copy_is_intact(copy: Path, sha256: str) -> bool:
    """True when `copy` exists and holds exactly the bytes with this fingerprint."""
    if not copy.is_file():
        return False
    try:
        return _sha256_of(copy)[0] == sha256
    except OSError:
        return False  # unreadable copy counts as damaged


def _restore_warning(source: Path, sha256: str, originals: Path) -> dict | None:
    """For an already registered file: re-create a missing or damaged copy."""
    if _copy_is_intact(originals / f"{sha256}.pdf", sha256):
        return None
    if _place_copy(source, sha256, originals) is None:
        return {
            "code": "copy_not_restored",
            "message": "копия отсутствует или повреждена; восстановить не удалось: "
                       f"{REASON_CHANGED}",
        }
    return {
        "code": "copy_restored",
        "message": "копия отсутствовала или была повреждена — восстановлена из этого файла",
    }


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _find_existing(conn: psycopg.Connection, sha256: str) -> str | None:
    row = conn.execute("SELECT id FROM document WHERE sha256 = %s", (sha256,)).fetchone()
    return row[0] if row else None


def _name_collisions(conn: psycopg.Connection, name: str, sha256: str) -> list[str]:
    rows = conn.execute(
        "SELECT id FROM document WHERE lower(original_name) = lower(%s) AND sha256 <> %s "
        "ORDER BY seq",
        (name, sha256),
    ).fetchall()
    return [r[0] for r in rows]


def _register_document(
    conn: psycopg.Connection,
    *,
    run_id: int,
    sha256: str,
    original_name: str,
    source_path: str,
    copy_path: str,
    size_bytes: int,
    note: str | None,
    pages: Sequence[tuple[PageMetrics, str]],
) -> str:
    """One transaction: next ID from the counter, document, pages, stage states."""
    with conn.transaction():
        seq = conn.execute(
            "UPDATE document_counter SET last_seq = last_seq + 1 RETURNING last_seq"
        ).fetchone()[0]
        doc_id = format_document_id(seq)
        conn.execute(
            "INSERT INTO document (id, seq, sha256, original_name, source_path, copy_path,"
            " size_bytes, page_count, note, intake_run_id)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (doc_id, seq, sha256, original_name, source_path, copy_path, size_bytes,
             len(pages), note, run_id),
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO page (document_id, page_number, kind, char_count, image_coverage,"
                " invisible_text_share, kind_run_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                [
                    (doc_id, m.page_number, kind, m.char_count, m.image_coverage,
                     m.invisible_text_share, run_id)
                    for m, kind in pages
                ],
            )
            cur.executemany(
                "INSERT INTO stage_status (document_id, stage) VALUES (%s, %s)",
                [(doc_id, stage) for stage in db.STAGES],
            )
    return doc_id


def page_ranges(numbers: Iterable[int]) -> str:
    """[1,2,3,7,9,10] → «1–3, 7, 9, 10»; runs of three or more are collapsed."""
    nums = sorted(set(numbers))
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{nums[i]}–{nums[j]}")
        else:
            parts.extend(str(n) for n in nums[i : j + 1])
        i = j + 1
    return ", ".join(parts)


def page_warnings(kinds: Sequence[str], large_file_pages: int) -> list[dict]:
    warnings = []
    scans = [n for n, k in enumerate(kinds, 1) if k == KIND_SCAN]
    if scans:
        warnings.append({
            "code": "scan_pages",
            "pages": scans,
            "message": f"страницы-сканы на первом этапе не читаются: стр. {page_ranges(scans)}",
        })
    ocr = [n for n, k in enumerate(kinds, 1) if k == KIND_SCAN_WITH_TEXT]
    if ocr:
        warnings.append({
            "code": "scan_with_text_pages",
            "pages": ocr,
            "message": f"текст стр. {page_ranges(ocr)} получен распознаванием "
                       "и может содержать ошибки",
        })
    if len(kinds) > large_file_pages:
        warnings.append({
            "code": "large_file",
            "message": f"{len(kinds)} страниц — больше {large_file_pages}",
        })
    return warnings


def _rejected(path: Path, code: str, reason: str) -> dict:
    return {"path": str(path), "status": "rejected", "reason_code": code, "reason": reason,
            "warnings": []}


def _process_file(ctx: _Context, item: _Input) -> dict:
    path = item.path
    if item.reject_code:
        return _rejected(path, item.reject_code, item.reject_reason or "")

    sniffed = sniff(path)
    if sniffed.kind != "pdf":
        return _rejected(path, sniffed.reason_code, sniffed.reason)

    sha256, size = _sha256_of(path)
    existing = _find_existing(ctx.conn, sha256)
    if existing:
        warning = _restore_warning(path, sha256, ctx.settings.originals_dir)
        return {"path": str(path), "status": "existing", "document_id": existing,
                "warnings": [warning] if warning else []}

    try:
        metrics = analyse_pdf(path)
    except PdfOpenError as exc:
        return _rejected(path, exc.reason_code, exc.reason)
    kinds = [classify(m, ctx.settings) for m in metrics]

    copy = _place_copy(path, sha256, ctx.settings.originals_dir)
    if copy is None:
        return _rejected(path, "changed_during_add", REASON_CHANGED)

    warnings = page_warnings(kinds, ctx.settings.large_file_pages)
    collisions = _name_collisions(ctx.conn, path.name, sha256)
    if collisions:
        warnings.append({
            "code": "name_collision",
            "document_ids": collisions,
            "message": f"имя совпадает с {', '.join(collisions)} (другое содержимое)",
        })

    doc_id = _register_document(
        ctx.conn,
        run_id=ctx.run_id,
        sha256=sha256,
        original_name=path.name,
        source_path=str(path),
        copy_path=copy.relative_to(ctx.settings.data_dir).as_posix(),
        size_bytes=size,
        note=ctx.note,
        pages=list(zip(metrics, kinds)),
    )
    return {
        "path": str(path),
        "status": "added",
        "document_id": doc_id,
        "page_count": len(kinds),
        "page_kinds": {k: kinds.count(k) for k in KINDS},
        "warnings": warnings,
    }


def _process_or_reject(ctx: _Context, item: _Input) -> dict:
    """A source file that cannot be read is rejected; the other files go on (principle VII).

    Any other I/O error (e.g. writing to the data folder) stops the run as an environment
    problem: going on would fail the same way for every file.
    """
    try:
        return _process_file(ctx, item)
    except OSError as exc:
        if exc.filename is not None and os.fsdecode(exc.filename) == str(item.path):
            hint = "нет прав на чтение" if isinstance(exc, PermissionError) else type(exc).__name__
            return _rejected(item.path, "unsupported", f"{REASON_UNREADABLE}: {hint}")
        raise EnvironmentProblem(
            f"Ошибка ввода-вывода ({exc.strerror or type(exc).__name__}: {exc.filename}) — "
            "проверьте папку данных и свободное место"
        ) from exc


# --- the command --------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def _write_report(settings: Settings, report: dict) -> Path:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    target = settings.reports_dir / f"intake-{report['run_id']}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return target


def run_intake(
    conn: psycopg.Connection,
    settings: Settings,
    paths: Sequence[str | os.PathLike],
    *,
    note: str | None = None,
    label: str | None = None,
) -> IntakeOutcome:
    # A missing path or a path inside a service folder fails before a run is created.
    inputs = collect_inputs(paths, service_dirs(settings))

    # Each file commits on its own; reads between files must not hold a transaction.
    conn.autocommit = True
    run_settings = {"command": "add", **settings.settings_for_run()}
    run_id = runs.start_run(conn, INTAKE_STAGE, run_settings, label)
    ctx = _Context(conn=conn, settings=settings, run_id=run_id, note=note)
    started_at = _now_iso()
    started = time.monotonic()

    interrupted = False
    try:
        for item in inputs:
            ctx.results.append(_process_or_reject(ctx, item))
    except KeyboardInterrupt:
        interrupted = True  # the current file is not committed; finished_at stays NULL

    finished_at = None
    if not interrupted:
        runs.finish_run(conn, run_id)
        finished_at = _now_iso()

    totals = {"files": len(ctx.results), "added": 0, "existing": 0, "rejected": 0}
    for r in ctx.results:
        totals[r["status"]] += 1
    report = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "code_version": runs.code_version(),
        "interrupted": interrupted,
        "files": ctx.results,
        "totals": totals,
    }
    return IntakeOutcome(report=report, report_path=_write_report(settings, report),
                         interrupted=interrupted)
