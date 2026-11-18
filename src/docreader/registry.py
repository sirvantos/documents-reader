"""Registry commands: list, show, remove, verify, reclassify, page-kinds-check."""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from docreader import runs
from docreader.config import Settings
from docreader.errors import UserError
from docreader.ids import format_document_id, parse_document_id
from docreader.pdfpages import KINDS, PageMetrics, classify
from docreader.stages import STAGES, RunStage, reset_all


def _not_found(seq: int) -> UserError:
    return UserError(
        f"Документ {format_document_id(seq)} не найден — список документов: docreader list"
    )


def find_document(conn: psycopg.Connection, seq: int) -> dict | None:
    """The document row by its number, or None."""
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute("SELECT * FROM document WHERE seq = %s", (seq,)).fetchone()


def _require_documents(conn: psycopg.Connection, seqs: Sequence[int]) -> list[str]:
    ids = []
    for seq in seqs:
        row = find_document(conn, seq)
        if row is None:
            raise _not_found(seq)
        ids.append(row["id"])
    return ids


# --- reclassify (research R-2, contracts/cli.md) -------------------------------------


def reclassify(
    conn: psycopg.Connection,
    settings: Settings,
    seqs: Sequence[int] | None = None,
    label: str | None = None,
) -> dict:
    """Recompute page kinds from stored metrics and the current thresholds.

    Files are not reopened. Documents with at least one changed page get all their
    stage states reset to pending, since every later stage depends on page kinds.
    """
    doc_ids = _require_documents(conn, seqs) if seqs else None

    run_settings = {"command": "reclassify", **settings.settings_for_run()}
    run_id = runs.start_run(conn, RunStage.INTAKE, run_settings, label)

    changed: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    with conn.transaction():
        query = (
            "SELECT p.document_id, p.page_number, p.kind, p.char_count, p.image_coverage,"
            " p.invisible_text_share FROM page p JOIN document d ON d.id = p.document_id"
        )
        params: tuple = ()
        if doc_ids is not None:
            query += " WHERE p.document_id = ANY(%s)"
            params = (doc_ids,)
        query += " ORDER BY d.seq, p.page_number"
        rows = conn.execute(query, params).fetchall()

        for doc_id, page_number, old_kind, chars, coverage, invisible in rows:
            metrics = PageMetrics(page_number, chars, coverage, invisible)
            new_kind = classify(metrics, settings)
            if new_kind != old_kind:
                changed[doc_id].append((page_number, old_kind, new_kind))

        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE page SET kind = %s, kind_run_id = %s"
                " WHERE document_id = %s AND page_number = %s",
                [
                    (new, run_id, doc_id, page)
                    for doc_id, pages in changed.items()
                    for page, _old, new in pages
                ],
            )
        if changed:
            reset_all(conn, list(changed))
    runs.finish_run(conn, run_id)

    checked = sorted({r[0] for r in rows}, key=lambda i: int(i[2:]))
    return {
        "run_id": run_id,
        "documents_checked": len(checked),
        "pages_checked": len(rows),
        "pages_changed": sum(len(p) for p in changed.values()),
        "documents": [
            {
                "document_id": doc_id,
                "pages": [
                    {"page_number": page, "old_kind": old, "new_kind": new}
                    for page, old, new in changed[doc_id]
                ],
            }
            for doc_id in checked
            if doc_id in changed
        ],
    }


# --- remove (FR-011, contracts/cli.md) ---------------------------------------------------


def remove(conn: psycopg.Connection, settings: Settings, seq: int) -> dict:
    """Delete a document and everything about it; keep runs; log the deletion.

    The rows go in one transaction; the copy file is removed after the commit.
    Failing to remove the file is a warning: the file stays and is reused when the
    same content is added again.
    """
    row = find_document(conn, seq)
    if row is None:
        raise _not_found(seq)

    with conn.transaction():
        conn.execute(
            "INSERT INTO deletion_log (document_id, original_name, sha256) VALUES (%s, %s, %s)",
            (row["id"], row["original_name"], row["sha256"]),
        )
        # Pages, stage states and per-document results of later features cascade.
        conn.execute("DELETE FROM document WHERE id = %s", (row["id"],))

    copy = settings.data_dir / row["copy_path"]
    warning = None
    try:
        copy.unlink()
    except FileNotFoundError:
        warning = f"копия {copy} уже отсутствовала"
    except OSError as exc:
        warning = (
            f"не удалось удалить копию {copy}: {exc.strerror} — файл остаётся и будет "
            "использован при повторном добавлении того же содержимого"
        )
    return {
        "document_id": row["id"],
        "original_name": row["original_name"],
        "copy_path": str(copy),
        "warning": warning,
    }


# --- list / show (FR-009, contracts/cli.md) ------------------------------------------------


def _page_kind_counts(rows: Sequence[tuple[str, str]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(KINDS, 0))
    for doc_id, kind in rows:
        counts[doc_id][kind] += 1
    return counts


def _stages_by_document(conn: psycopg.Connection, doc_ids: list[str]) -> dict[str, dict]:
    by_doc: dict[str, dict] = {doc_id: {} for doc_id in doc_ids}
    rows = conn.execute(
        "SELECT document_id, stage, state, reason FROM stage_status WHERE document_id = ANY(%s)",
        (doc_ids,),
    ).fetchall()
    for doc_id, stage, state, reason in rows:
        by_doc[doc_id][stage] = {"state": state, "reason": reason}
    return {
        doc_id: {stage: found[stage] for stage in STAGES if stage in found}
        for doc_id, found in by_doc.items()
    }


def _summaries(conn: psycopg.Connection, docs: list[dict]) -> list[dict]:
    doc_ids = [d["id"] for d in docs]
    kinds = _page_kind_counts(
        conn.execute(
            "SELECT document_id, kind FROM page WHERE document_id = ANY(%s)", (doc_ids,)
        ).fetchall()
    )
    stages = _stages_by_document(conn, doc_ids)
    empty_kinds = dict.fromkeys(KINDS, 0)
    return [
        {
            "id": d["id"],
            "original_name": d["original_name"],
            "page_count": d["page_count"],
            "added_at": d["added_at"].isoformat(),
            "page_kinds": kinds.get(d["id"], dict(empty_kinds)),
            "stages": stages[d["id"]],
        }
        for d in docs
    ]


def list_documents(conn: psycopg.Connection) -> list[dict]:
    """All documents in ascending ID order."""
    with conn.cursor(row_factory=dict_row) as cur:
        docs = cur.execute("SELECT * FROM document ORDER BY seq").fetchall()
    return _summaries(conn, docs) if docs else []


def show_document(conn: psycopg.Connection, settings: Settings, seq: int) -> dict:
    """One document with its pages and per-page metrics."""
    doc = find_document(conn, seq)
    if doc is None:
        raise _not_found(seq)
    result = _summaries(conn, [doc])[0]
    pages = conn.execute(
        "SELECT page_number, kind, char_count, image_coverage, invisible_text_share"
        " FROM page WHERE document_id = %s ORDER BY page_number",
        (doc["id"],),
    ).fetchall()
    result.update(
        sha256=doc["sha256"],
        copy_path=str(settings.data_dir / doc["copy_path"]),
        source_path=doc["source_path"],
        size_bytes=doc["size_bytes"],
        note=doc["note"],
        intake_run_id=doc["intake_run_id"],
        pages=[
            {
                "page_number": n,
                "kind": kind,
                "char_count": chars,
                "image_coverage": coverage,
                "invisible_text_share": invisible,
            }
            for n, kind, chars, coverage, invisible in pages
        ],
    )
    return result


# --- verify (FR-010) -----------------------------------------------------------------------


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify(
    conn: psycopg.Connection, settings: Settings, seqs: Sequence[int] | None = None
) -> dict:
    """Re-hash the stored copies. Creates no run."""
    with conn.cursor(row_factory=dict_row) as cur:
        if seqs:
            _require_documents(conn, seqs)
            docs = cur.execute(
                "SELECT id, sha256, copy_path FROM document WHERE seq = ANY(%s) ORDER BY seq",
                (list(seqs),),
            ).fetchall()
        else:
            docs = cur.execute("SELECT id, sha256, copy_path FROM document ORDER BY seq").fetchall()

    problems = []
    for doc in docs:
        copy = settings.data_dir / doc["copy_path"]
        problem: str | None
        try:
            ok = _file_sha256(copy) == doc["sha256"]
        except OSError:
            problem = "missing"
        else:
            problem = None if ok else "mismatch"
        if problem:
            problems.append(
                {"document_id": doc["id"], "copy_path": str(copy), "problem": problem}
            )
    return {"checked": len(docs), "problems": problems}


# --- page-kinds-check (SC-004, contracts/cli.md) ---------------------------------------------

_LABELS_HEADER = ["document_id", "page_number", "kind"]


def _read_labels(csv_path: Path) -> list[tuple[int, int, int, str]]:
    """Rows as (line number, seq, page_number, kind), validated for syntax only."""
    try:
        text = Path(csv_path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise UserError(f"Файл разметки {csv_path} не найден — укажите путь к CSV") from None
    except UnicodeDecodeError:
        raise UserError(f"Файл разметки {csv_path} не в кодировке UTF-8") from None
    except OSError as exc:
        raise UserError(f"Не удалось прочитать файл разметки {csv_path}: {exc.strerror}") from None

    reader = csv.reader(text.splitlines())
    header = next(reader, None)
    if header is None or [h.strip() for h in header] != _LABELS_HEADER:
        raise UserError(
            "Неверный заголовок файла разметки — ожидается: " + ",".join(_LABELS_HEADER)
        )
    rows = []
    first_seen: dict[tuple[int, int], int] = {}
    for row in reader:
        line = reader.line_num
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) != 3:
            raise UserError(f"Файл разметки, строка {line}: ожидается 3 столбца")
        raw_id, raw_page, raw_kind = (cell.strip() for cell in row)
        try:
            seq = parse_document_id(raw_id)
        except UserError as exc:
            raise UserError(f"Файл разметки, строка {line}: {exc}") from None
        if not (raw_page.isascii() and raw_page.isdigit()):
            raise UserError(
                f"Файл разметки, строка {line}: номер страницы «{raw_page}» не число"
            )
        if raw_kind not in KINDS:
            raise UserError(
                f"Файл разметки, строка {line}: неизвестный вид «{raw_kind}» — "
                f"допустимо: {', '.join(KINDS)}"
            )
        page = int(raw_page)
        if (seq, page) in first_seen:
            raise UserError(
                f"Файл разметки, строка {line}: страница {page} документа "
                f"{format_document_id(seq)} уже размечена в строке {first_seen[(seq, page)]}"
            )
        first_seen[(seq, page)] = line
        rows.append((line, seq, page, raw_kind))
    return rows


def page_kinds_check(conn: psycopg.Connection, csv_path: Path) -> dict:
    """Compare stored page kinds with a hand-labelled CSV."""
    rows = _read_labels(csv_path)
    seqs = sorted({seq for _, seq, _, _ in rows})
    stored: dict[tuple[int, int], tuple] = {}
    if seqs:
        for seq, page, kind, chars, coverage, invisible in conn.execute(
            "SELECT d.seq, p.page_number, p.kind, p.char_count, p.image_coverage,"
            " p.invisible_text_share FROM page p JOIN document d ON d.id = p.document_id"
            " WHERE d.seq = ANY(%s)",
            (seqs,),
        ):
            stored[(seq, page)] = (kind, chars, coverage, invisible)
    known_docs = (
        {r[0] for r in conn.execute("SELECT seq FROM document WHERE seq = ANY(%s)", (seqs,))}
        if seqs
        else set()
    )

    matrix = {lab: dict.fromkeys(KINDS, 0) for lab in KINDS}
    mismatches = []
    correct = 0
    for line, seq, page, labelled in rows:
        doc_id = format_document_id(seq)
        if seq not in known_docs:
            raise UserError(f"Файл разметки, строка {line}: документ {doc_id} не найден")
        found = stored.get((seq, page))
        if found is None:
            raise UserError(
                f"Файл разметки, строка {line}: у документа {doc_id} нет страницы {page}"
            )
        kind, chars, coverage, invisible = found
        matrix[labelled][kind] += 1
        if kind == labelled:
            correct += 1
        else:
            mismatches.append(
                {
                    "document_id": doc_id,
                    "page_number": page,
                    "labelled": labelled,
                    "stored": kind,
                    "char_count": chars,
                    "image_coverage": coverage,
                    "invisible_text_share": invisible,
                }
            )
    total = len(rows)
    return {
        "total": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "matrix": matrix,
        "mismatches": mismatches,
    }
