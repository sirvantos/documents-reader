"""Integration tests for `docreader add` (task T019, US1).

Everything goes through the CLI and the database; no internal functions are called.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest

from tests.synthetic import make_pdfs as mk

STAGES = {"reading", "structure", "extraction", "checks", "indexing"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_json(cli, *paths, extra=()):
    result = cli("add", *paths, *extra, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def by_path(report: dict) -> dict[str, dict]:
    return {f["path"]: f for f in report["files"]}


def make_five(folder: Path) -> list[Path]:
    (folder / "sub").mkdir(parents=True)
    names = ["a.pdf", "b.pdf", "c.pdf", "sub/d.pdf", "sub/e.pdf"]
    paths = []
    for i, name in enumerate(names):
        paths.append(mk.make_digital(folder / name, pages=i + 1, text_seed=f"seed{i}"))
    return paths


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")
def test_unreadable_file_is_rejected_and_the_others_are_added(cli, db, tmp_path):
    folder = tmp_path / "in"
    paths = make_five(folder)
    locked = paths[1]
    locked.chmod(0)
    try:
        report = add_json(cli, folder)
    finally:
        locked.chmod(0o644)

    assert report["totals"] == {"files": 5, "added": 4, "existing": 0, "rejected": 1}
    entry = by_path(report)[str(locked.resolve())]
    assert entry["status"] == "rejected"
    assert entry["reason_code"] == "unsupported"
    assert entry["reason"] == "файл не читается: нет прав на чтение"
    assert report["finished_at"] is not None


def test_folder_with_subfolder_adds_five_documents_in_sorted_order(cli, db, tmp_path):
    folder = tmp_path / "in"
    paths = make_five(folder)

    report = add_json(cli, folder)

    assert report["totals"] == {"files": 5, "added": 5, "existing": 0, "rejected": 0}
    expected = sorted(paths, key=lambda p: str(p.relative_to(folder)))
    entries = by_path(report)
    for n, p in enumerate(expected, start=1):
        entry = entries[str(p.resolve())]
        assert entry["status"] == "added"
        assert entry["document_id"] == f"D-{n:04d}"

    for n, p in enumerate(expected, start=1):
        doc_id = f"D-{n:04d}"
        pages = paths.index(p) + 1
        row = db.execute(
            "SELECT original_name, page_count, size_bytes, source_path FROM document WHERE id = %s",
            (doc_id,),
        ).fetchone()
        assert row == (p.name, pages, p.stat().st_size, str(p.resolve()))
        stages = db.execute(
            "SELECT stage, state FROM stage_status WHERE document_id = %s", (doc_id,)
        ).fetchall()
        assert len(stages) == 5
        assert {s for s, _ in stages} == STAGES
        assert {st for _, st in stages} == {"pending"}
        page_rows = db.execute(
            "SELECT page_number, kind FROM page WHERE document_id = %s ORDER BY page_number",
            (doc_id,),
        ).fetchall()
        assert page_rows == [(i, "text") for i in range(1, pages + 1)]


def test_single_file_path(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    p = mk.make_digital(folder / "one.pdf", pages=2, text_seed="one")

    report = add_json(cli, p)

    assert report["totals"]["added"] == 1
    assert report["files"][0]["path"] == str(p.resolve())
    assert report["files"][0]["document_id"] == "D-0001"
    assert db.execute("SELECT count(*) FROM document").fetchone()[0] == 1


def test_several_paths_in_one_call(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    p1 = mk.make_digital(folder / "x.pdf", text_seed="x")
    p2 = mk.make_digital(folder / "y.pdf", text_seed="y")

    report = add_json(cli, p1, p2)

    assert report["totals"] == {"files": 2, "added": 2, "existing": 0, "rejected": 0}
    assert {f["path"] for f in report["files"]} == {str(p1.resolve()), str(p2.resolve())}
    assert db.execute("SELECT count(*) FROM document").fetchone()[0] == 2


REJECTIONS = [
    (mk.make_fake_docx, "contract.docx", "word"),
    (mk.make_fake_doc, "old.doc", "word"),
    (mk.make_jpeg, "photo.jpg", "image"),
    (mk.make_png, "photo.png", "image"),
    (mk.make_unknown, "note.txt", "unsupported"),
    (lambda p: mk.make_unknown(p), ".DS_Store", "hidden"),
    (mk.make_encrypted, "secret.pdf", "encrypted"),
    (mk.make_damaged, "broken.pdf", "damaged"),
    (mk.make_empty, "empty.pdf", "empty"),
]


@pytest.mark.parametrize(
    ("generator", "name", "reason_code"), REJECTIONS, ids=[r[2] + ":" + r[1] for r in REJECTIONS]
)
def test_bad_file_is_rejected_and_good_one_added(cli, db, tmp_path, generator, name, reason_code):
    folder = tmp_path / "in"
    folder.mkdir()
    good = mk.make_digital(folder / "good.pdf", text_seed="good")
    bad = generator(folder / name)

    report = add_json(cli, folder)

    entries = by_path(report)
    assert entries[str(good.resolve())]["status"] == "added"
    entry = entries[str(Path(bad).resolve())]
    assert entry["status"] == "rejected"
    assert entry["reason_code"] == reason_code
    assert entry["reason"]
    assert "document_id" not in entry
    assert report["totals"] == {"files": 2, "added": 1, "existing": 0, "rejected": 1}
    assert db.execute("SELECT count(*) FROM document").fetchone()[0] == 1


def test_all_bad_files_in_one_folder(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "g1.pdf", text_seed="g1")
    mk.make_digital(folder / "g2.pdf", text_seed="g2")
    for generator, name, _ in REJECTIONS:
        generator(folder / name)

    report = add_json(cli, folder)

    assert report["totals"] == {
        "files": 2 + len(REJECTIONS),
        "added": 2,
        "existing": 0,
        "rejected": len(REJECTIONS),
    }
    codes = {
        Path(f["path"]).name: f["reason_code"]
        for f in report["files"]
        if f["status"] == "rejected"
    }
    assert codes == {name: code for _, name, code in REJECTIONS}


def test_pdf_without_pages_is_rejected(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    p = mk.make_no_pages(folder / "nopages.pdf")

    report = add_json(cli, p)

    entry = report["files"][0]
    assert entry["status"] == "rejected"
    # pdfium may refuse to open a 0-page file at all, then the reason is "damaged".
    assert entry["reason_code"] in {"no_pages", "damaged"}
    assert db.execute("SELECT count(*) FROM document").fetchone()[0] == 0


def test_copies_are_read_only_and_identical_after_source_deleted(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    paths = make_five(folder)
    original_hashes = {p.name: sha256(p) for p in paths}

    report = add_json(cli, folder)
    assert report["totals"]["added"] == 5
    for p in paths:
        p.unlink()

    rows = db.execute("SELECT original_name, copy_path, sha256 FROM document").fetchall()
    assert len(rows) == 5
    for name, copy_path, doc_sha in rows:
        assert not Path(copy_path).is_absolute()
        assert copy_path == f"originals/{doc_sha}.pdf"
        copy = data_dir / copy_path
        assert copy.is_file()
        assert stat.S_IMODE(copy.stat().st_mode) == 0o444
        assert sha256(copy) == original_hashes[name] == doc_sha


def test_report_invariants_and_saved_file(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf", text_seed="a")
    mk.make_digital(folder / "b.pdf", text_seed="b")
    mk.make_png(folder / "c.png")
    mk.make_fake_docx(folder / "d.docx")
    mk.make_empty(folder / "e.pdf")

    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)

    assert report["totals"]["files"] == 5
    assert len(report["files"]) == 5
    for f in report["files"]:
        assert f["status"] in {"added", "existing", "rejected"}
        assert f["warnings"] == []
    totals = report["totals"]
    assert totals["added"] + totals["existing"] + totals["rejected"] == totals["files"]
    for status in ("added", "existing", "rejected"):
        assert totals[status] == sum(1 for f in report["files"] if f["status"] == status)
    for f in report["files"]:
        if f["status"] == "added":
            assert f["page_count"] == 3
            assert f["page_kinds"] == {"text": 3, "scan": 0, "scan_with_text": 0}
    assert report["code_version"]
    assert report["started_at"] and report["finished_at"]

    saved = data_dir / "reports" / f"intake-{report['run_id']}.json"
    assert saved.is_file()
    assert json.loads(saved.read_text(encoding="utf-8")) == report


def test_run_row_is_recorded(cli, db, tmp_path):
    folder = tmp_path / "in"
    make_five(folder)

    report = add_json(cli, folder)

    runs = db.execute(
        "SELECT id, stage, code_version, settings, finished_at FROM run"
    ).fetchall()
    assert len(runs) == 1
    run_id, stage, code_version, settings, finished_at = runs[0]
    assert run_id == report["run_id"]
    assert stage == "intake"
    assert code_version
    assert settings["command"] == "add"
    assert settings["page_kinds"]["text_min_chars"] == 20
    assert settings["page_kinds"]["full_image_coverage"] == 0.85
    assert settings["intake"]["large_file_pages"] == 200
    assert finished_at is not None
    assert (
        db.execute(
            "SELECT count(*) FROM document WHERE intake_run_id <> %s", (run_id,)
        ).fetchone()[0]
        == 0
    )
    stale = db.execute("SELECT count(*) FROM page WHERE kind_run_id <> %s", (run_id,)).fetchone()
    assert stale[0] == 0
    assert db.execute("SELECT count(*) FROM page").fetchone()[0] == 1 + 2 + 3 + 4 + 5


def test_label_is_stored_in_run(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf")

    add_json(cli, folder, extra=("--label", "x"))

    assert db.execute("SELECT label FROM run").fetchone()[0] == "x"


def test_nonexistent_path_is_a_user_error(cli, db, tmp_path):
    result = cli("add", tmp_path / "missing.pdf", "--json")

    assert result.exit_code == 1
    assert result.stderr.strip()
    assert db.execute("SELECT count(*) FROM document").fetchone()[0] == 0


def test_text_output_lists_added_and_rejected(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf", text_seed="a")
    mk.make_digital(folder / "b.pdf", text_seed="b")
    mk.make_fake_docx(folder / "c.docx")

    result = cli("add", folder)

    assert result.exit_code == 0, result.stderr
    assert "Добавлено: 2" in result.stdout
    assert "D-0001" in result.stdout
    assert "D-0002" in result.stdout
    assert "Не добавлено: 1" in result.stdout


def test_note_is_stored_for_every_added_document(cli, db, tmp_path):
    """T047, FR-006: `--note` is written to each document added by that call."""
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf", text_seed="note-a")
    mk.make_digital(folder / "b.pdf", text_seed="note-b")
    add_json(cli, folder, extra=("--note", "пакет от юристов"))

    notes = db.execute("SELECT id, note FROM document ORDER BY seq").fetchall()
    assert notes == [("D-0001", "пакет от юристов"), ("D-0002", "пакет от юристов")]


def test_without_note_the_note_is_empty(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf", text_seed="no-note")
    add_json(cli, folder)
    assert db.execute("SELECT note FROM document").fetchone() == (None,)


# --- service folders of the data folder (T052) -------------------------------------------


def test_data_folder_service_dirs_are_skipped(cli, db, data_dir):
    """Contracts kept inside the data folder: adding the whole folder twice must not
    pick up the program's own copies or reports."""
    contracts = data_dir / "contracts"
    contracts.mkdir()
    mk.make_digital(contracts / "a.pdf", pages=1, text_seed="svc-a")
    mk.make_digital(contracts / "b.pdf", pages=1, text_seed="svc-b")

    first = add_json(cli, data_dir)
    assert first["totals"]["added"] == 2

    second = add_json(cli, data_dir)

    assert second["totals"]["added"] == 0
    assert second["totals"]["existing"] == 2
    skipped = {Path(f["path"]).name: f for f in second["files"] if f["status"] == "rejected"}
    assert set(skipped) == {"originals", "reports"}
    for entry in skipped.values():
        assert entry["reason_code"] == "service_dir"
        assert entry["reason"] == "служебная папка программы не обходится"
    assert db.execute("SELECT count(*) FROM document").fetchone()[0] == 2


@pytest.mark.parametrize("inside", ["originals", "reports"])
def test_path_inside_service_dir_is_a_user_error(cli, db, data_dir, tmp_path, inside):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf", pages=1, text_seed="svc-c")
    add_json(cli, folder)  # creates originals/ and reports/
    runs_before = db.execute("SELECT count(*) FROM run").fetchone()[0]

    result = cli("add", data_dir / inside, "--json")

    assert result.exit_code == 1
    assert "служебная папка программы" in result.stderr
    assert db.execute("SELECT count(*) FROM run").fetchone()[0] == runs_before
