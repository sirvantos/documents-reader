"""Integration tests for `docreader remove` (task T044, US5; FR-011, FR-003).

Everything goes through the CLI and the database; no internal functions are called.
"""

from __future__ import annotations

import json
import os

import pytest

from tests.synthetic import make_pdfs as mk

CANCELLED = "Удаление отменено"


@pytest.fixture
def two_docs(cli, tmp_path):
    """Two registered documents D-0001 (2 pages) and D-0002 (3 pages)."""
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf", pages=2, text_seed="alpha")
    mk.make_digital(folder / "b.pdf", pages=3, text_seed="beta")
    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    return folder


def snapshot(db, doc_id):
    doc = db.execute(
        "SELECT original_name, sha256, copy_path, page_count FROM document WHERE id = %s",
        (doc_id,),
    ).fetchone()
    pages = db.execute(
        "SELECT count(*) FROM page WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]
    stages = db.execute(
        "SELECT count(*) FROM stage_status WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]
    return doc, pages, stages


def count(db, table, where="true", params=()):
    return db.execute(f"SELECT count(*) FROM {table} WHERE {where}", params).fetchone()[0]


def assert_unchanged(db, data_dir, before_doc, before_runs):
    assert snapshot(db, "D-0001") == before_doc
    assert (data_dir / before_doc[0][2]).is_file()
    assert count(db, "deletion_log") == 0
    assert count(db, "run") == before_runs


def test_remove_with_yes_deletes_everything_but_keeps_log(cli, db, data_dir, two_docs):
    (name, sha, copy_path, _), pages, stages = snapshot(db, "D-0001")
    assert pages == 2 and stages == 5
    other_before = snapshot(db, "D-0002")
    runs_before = count(db, "run")
    assert (data_dir / copy_path).is_file()

    result = cli("remove", "D-0001", "--yes")

    assert result.exit_code == 0, result.stderr
    assert count(db, "document", "id = 'D-0001'") == 0
    assert count(db, "page", "document_id = 'D-0001'") == 0
    assert count(db, "stage_status", "document_id = 'D-0001'") == 0
    assert not (data_dir / copy_path).exists()
    assert count(db, "run") == runs_before
    log = db.execute("SELECT document_id, original_name, sha256 FROM deletion_log").fetchall()
    assert log == [("D-0001", name, sha)]
    assert snapshot(db, "D-0002") == other_before
    assert (data_dir / other_before[0][2]).is_file()


@pytest.mark.parametrize("typed", ["D-0001\n", "d-1\n"])
def test_confirmation_by_typing_the_id(cli, db, data_dir, two_docs, typed):
    (_, _, copy_path, _), _, _ = snapshot(db, "D-0001")

    result = cli("remove", "D-0001", input=typed)

    assert result.exit_code == 0, result.stderr
    assert count(db, "document", "id = 'D-0001'") == 0
    assert not (data_dir / copy_path).exists()
    assert count(db, "deletion_log", "document_id = 'D-0001'") == 1


@pytest.mark.parametrize("typed", ["D-0002\n", "\n"])
def test_wrong_or_empty_confirmation_cancels(cli, db, data_dir, two_docs, typed):
    before = snapshot(db, "D-0001")
    runs_before = count(db, "run")

    result = cli("remove", "D-0001", input=typed)

    assert result.exit_code == 1
    assert CANCELLED in result.stdout + result.stderr
    assert_unchanged(db, data_dir, before, runs_before)
    assert count(db, "document") == 2


def test_non_terminal_stdin_without_yes_is_refused(cli, db, data_dir, two_docs):
    before = snapshot(db, "D-0001")
    runs_before = count(db, "run")

    result = cli("remove", "D-0001", input="D-0001\n", tty=False)

    assert result.exit_code == 1
    assert_unchanged(db, data_dir, before, runs_before)
    assert count(db, "document") == 2


def test_prints_what_will_be_deleted_before_confirming(cli, db, two_docs):
    (name, _, copy_path, page_count), _, _ = snapshot(db, "D-0001")

    result = cli("remove", "D-0001", input="D-0002\n")

    assert result.exit_code == 1
    out = result.stdout
    assert "D-0001" in out
    assert name in out
    assert str(page_count) in out
    assert copy_path in out


def test_readding_after_removal_gets_a_new_id_and_ids_are_never_reused(cli, db, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    first = mk.make_digital(folder / "a.pdf", pages=2, text_seed="alpha")
    other = mk.make_digital(tmp_path / "other.pdf", pages=1, text_seed="gamma")

    result = cli("add", first, "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["files"][0]["document_id"] == "D-0001"
    assert cli("remove", "D-0001", "--yes").exit_code == 0

    result = cli("add", first, "--json")
    assert result.exit_code == 0, result.stderr
    entry = json.loads(result.stdout)["files"][0]
    assert entry["status"] == "added"
    assert entry["document_id"] == "D-0002"

    # removing the last document must not free its number
    assert cli("remove", "D-0002", "--yes").exit_code == 0
    assert count(db, "document") == 0
    result = cli("add", other, "--json")
    assert result.exit_code == 0, result.stderr
    entry = json.loads(result.stdout)["files"][0]
    assert entry["status"] == "added"
    assert entry["document_id"] == "D-0003"
    assert count(db, "deletion_log") == 2


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_copy_deletion_failure_is_a_warning(cli, db, data_dir, two_docs):
    (name, sha, copy_path, _), _, _ = snapshot(db, "D-0001")
    originals = data_dir / "originals"
    assert (data_dir / copy_path).parent == originals

    originals.chmod(0o555)
    try:
        result = cli("remove", "D-0001", "--yes")
    finally:
        originals.chmod(0o755)

    assert result.exit_code == 0, result.stderr
    combined = result.stdout + result.stderr
    assert copy_path in combined or (data_dir / copy_path).name in combined
    assert count(db, "document", "id = 'D-0001'") == 0
    assert count(db, "page", "document_id = 'D-0001'") == 0
    assert db.execute("SELECT document_id, original_name, sha256 FROM deletion_log").fetchall() == [
        ("D-0001", name, sha)
    ]
    assert (data_dir / copy_path).is_file()


def test_unknown_id_fails(cli, db, two_docs):
    result = cli("remove", "D-0099", "--yes")

    assert result.exit_code == 1
    assert count(db, "document") == 2
    assert count(db, "deletion_log") == 0
