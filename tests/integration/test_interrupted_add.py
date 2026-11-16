"""Interrupted `add` (task T020): failure after the copy, Ctrl-C between files and
inside the registration transaction. Plan «Ключевые решения» 1 and 5, research R-4.

The tests patch the internal hooks `docreader.intake._register_document` and
`docreader.intake._process_file`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.synthetic.make_pdfs import make_digital


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _count(db, table: str) -> int:
    return db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608


def _files_by_name(result_stdout: str) -> dict[str, dict]:
    report = json.loads(result_stdout)
    return {Path(f["path"]).name: f for f in report["files"]}


def test_failure_after_copy_leaves_no_rows_and_retry_reuses_copy(
    cli, db, data_dir, tmp_path, monkeypatch
):
    import docreader.intake as intake

    folder = tmp_path / "in"
    folder.mkdir()
    src = make_digital(folder / "a.pdf", pages=3, text_seed="A")
    digest = _sha256(src)

    original = intake._register_document

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("docreader.intake._register_document", boom)
    with pytest.raises(RuntimeError, match="boom"):
        cli("add", folder)

    assert _count(db, "document") == 0
    assert _count(db, "page") == 0
    assert _count(db, "stage_status") == 0
    copy = data_dir / "originals" / f"{digest}.pdf"
    assert copy.is_file()

    monkeypatch.setattr("docreader.intake._register_document", original)
    result = cli("add", folder, "--json")
    assert result.exit_code == 0

    files = json.loads(result.stdout)["files"]
    assert len(files) == 1
    assert files[0]["status"] == "added"
    assert files[0]["document_id"] == "D-0001"

    assert _count(db, "document") == 1
    assert _sha256(copy) == digest
    row = db.execute("SELECT id, sha256, copy_path FROM document").fetchone()
    assert row[0] == "D-0001"
    assert row[1] == digest
    assert (data_dir / row[2]).resolve() == copy.resolve()


def test_ctrl_c_between_files_keeps_committed_documents(
    cli, db, tmp_path, monkeypatch
):
    import docreader.intake as intake

    folder = tmp_path / "in"
    folder.mkdir()
    for name, seed in (("a.pdf", "A"), ("b.pdf", "B"), ("c.pdf", "C")):
        make_digital(folder / name, pages=2, text_seed=seed)

    original = intake._process_file
    calls = {"n": 0}

    def interrupting(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr("docreader.intake._process_file", interrupting)
    result = cli("add", folder)

    assert result.exit_code == 130
    rows = db.execute("SELECT id, original_name FROM document ORDER BY seq").fetchall()
    assert rows == [("D-0001", "a.pdf"), ("D-0002", "b.pdf")]
    runs = db.execute("SELECT finished_at FROM run").fetchall()
    assert len(runs) == 1
    assert runs[0][0] is None
    assert "Добавлено: 2" in result.stdout

    monkeypatch.setattr("docreader.intake._process_file", original)
    result = cli("add", folder, "--json")
    assert result.exit_code == 0
    files = _files_by_name(result.stdout)
    assert files["a.pdf"]["status"] == "existing"
    assert files["b.pdf"]["status"] == "existing"
    assert files["c.pdf"]["status"] == "added"
    assert files["c.pdf"]["document_id"] == "D-0003"
    assert _count(db, "document") == 3


def test_ctrl_c_inside_transaction_rolls_back_only_that_file(
    cli, db, tmp_path, monkeypatch
):
    import docreader.intake as intake

    folder = tmp_path / "in"
    folder.mkdir()
    for name, seed in (("a.pdf", "A"), ("b.pdf", "B"), ("c.pdf", "C")):
        make_digital(folder / name, pages=2, text_seed=seed)

    original = intake._register_document
    calls = {"n": 0}

    def interrupting(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return original(*args, **kwargs)

    monkeypatch.setattr("docreader.intake._register_document", interrupting)
    result = cli("add", folder)

    assert result.exit_code == 130
    assert [r[0] for r in db.execute("SELECT id FROM document").fetchall()] == ["D-0001"]
    pages = db.execute("SELECT DISTINCT document_id FROM page").fetchall()
    assert pages == [("D-0001",)]
    stages = db.execute("SELECT DISTINCT document_id FROM stage_status").fetchall()
    assert stages == [("D-0001",)]
