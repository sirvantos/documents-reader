"""Integration tests for `reclassify`, `page-kinds-check` (T032, US3) and `verify` (T039, US4).

Everything goes through the CLI and the database; no internal functions are called.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.synthetic import make_pdfs as mk

STAGES = ("reading", "structure", "extraction", "checks", "indexing")
KINDS = ("text", "scan", "scan_with_text")


# --- helpers ------------------------------------------------------------------------


def add_files(cli, folder: Path, makers: list) -> list[str]:
    """Create synthetic files with `makers` (callables taking a path) and add them."""
    folder.mkdir(parents=True, exist_ok=True)
    for i, make in enumerate(makers):
        make(folder / f"f{i}.pdf")
    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["totals"]["added"] == len(makers)
    return sorted(f["document_id"] for f in report["files"])


def kinds(db, doc_id: str) -> list[str]:
    return [
        r[0]
        for r in db.execute(
            "SELECT kind FROM page WHERE document_id = %s ORDER BY page_number", (doc_id,)
        ).fetchall()
    ]


def kind_runs(db, doc_id: str) -> set[int]:
    return {
        r[0]
        for r in db.execute("SELECT kind_run_id FROM page WHERE document_id = %s", (doc_id,))
    }


def states(db, doc_id: str) -> dict[str, tuple]:
    rows = db.execute(
        "SELECT stage, state, reason, run_id FROM stage_status WHERE document_id = %s",
        (doc_id,),
    ).fetchall()
    return {s: (st, reason, run_id) for s, st, reason, run_id in rows}


def set_done(db, doc_id: str, stage: str = "reading") -> None:
    db.execute(
        "UPDATE stage_status SET state = 'done' WHERE document_id = %s AND stage = %s",
        (doc_id, stage),
    )


def copy_of(db, data_dir: Path, doc_id: str) -> Path:
    (rel,) = db.execute("SELECT copy_path FROM document WHERE id = %s", (doc_id,)).fetchone()
    return data_dir / rel


def run_count(db) -> int:
    return db.execute("SELECT count(*) FROM run").fetchone()[0]


def write_settings(data_dir: Path, text: str) -> None:
    (data_dir / "settings.toml").write_text(text, encoding="utf-8")


def hide_page_text_threshold(data_dir: Path) -> None:
    """Thresholds under which a ~885-char page with a full-page picture is a plain `scan`."""
    write_settings(data_dir, "[page_kinds]\ntext_min_chars = 2000\n")


def reset_thresholds(data_dir: Path) -> None:
    write_settings(data_dir, "")


# --- reclassify ---------------------------------------------------------------------


@pytest.fixture
def two_docs(cli, db, data_dir, tmp_path):
    """D-0001: image + invisible text (stored as `scan` under strict thresholds);
    D-0002: image-only PDF (`scan` under any thresholds, so it never changes)."""
    hide_page_text_threshold(data_dir)
    ids = add_files(
        cli,
        tmp_path / "in",
        [mk.make_image_with_invisible_text, mk.make_image_only],
    )
    assert ids == ["D-0001", "D-0002"]
    assert kinds(db, "D-0001") == ["scan", "scan"]
    assert kinds(db, "D-0002") == ["scan", "scan"]
    return ids


def test_reclassify_changes_kind_without_reopening_files(cli, db, data_dir, two_docs):
    reset_thresholds(data_dir)
    for doc_id in two_docs:  # files must not be reopened
        copy_of(db, data_dir, doc_id).unlink()

    result = cli("reclassify")

    assert result.exit_code == 0, result.stderr
    assert kinds(db, "D-0001") == ["scan_with_text", "scan_with_text"]
    assert kinds(db, "D-0002") == ["scan", "scan"]
    assert "2" in result.stdout  # number of changed pages


def test_reclassify_records_new_run_and_resets_stage_statuses(cli, db, data_dir, two_docs):
    old_run_1 = kind_runs(db, "D-0001")
    old_run_2 = kind_runs(db, "D-0002")
    set_done(db, "D-0001")
    set_done(db, "D-0002")
    states_2_before = states(db, "D-0002")
    runs_before = run_count(db)
    reset_thresholds(data_dir)

    result = cli("reclassify", "--label", "recheck")

    assert result.exit_code == 0, result.stderr
    assert run_count(db) == runs_before + 1
    new_runs = kind_runs(db, "D-0001")
    assert len(new_runs) == 1 and new_runs.isdisjoint(old_run_1)
    (new_run,) = new_runs
    stage, command, finished, label = db.execute(
        "SELECT stage, settings->>'command', finished_at IS NOT NULL, label FROM run WHERE id = %s",
        (new_run,),
    ).fetchone()
    assert (stage, command, finished, label) == ("intake", "reclassify", True, "recheck")

    changed = states(db, "D-0001")
    assert set(changed) == set(STAGES)
    assert all(v == ("pending", None, None) for v in changed.values())

    # unchanged document is untouched
    assert kind_runs(db, "D-0002") == old_run_2
    assert states(db, "D-0002") == states_2_before
    assert states(db, "D-0002")["reading"][0] == "done"


def test_reclassify_with_id_limits_to_one_document(cli, db, data_dir, tmp_path):
    hide_page_text_threshold(data_dir)
    ids = add_files(
        cli,
        tmp_path / "in",
        [
            mk.make_image_with_invisible_text,
            lambda p: mk.make_image_with_invisible_text(p, pages=3),
        ],
    )
    assert ids == ["D-0001", "D-0002"]
    assert set(kinds(db, "D-0001") + kinds(db, "D-0002")) == {"scan"}
    set_done(db, "D-0002")
    runs_2 = kind_runs(db, "D-0002")
    reset_thresholds(data_dir)

    result = cli("reclassify", "D-0001")

    assert result.exit_code == 0, result.stderr
    assert kinds(db, "D-0001") == ["scan_with_text"] * 2
    assert kinds(db, "D-0002") == ["scan"] * 3
    assert kind_runs(db, "D-0002") == runs_2
    assert states(db, "D-0002")["reading"][0] == "done"


# --- page-kinds-check ---------------------------------------------------------------


def write_labels(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "labels.csv"
    body = "".join(r + "\n" for r in rows)
    path.write_text("document_id,page_number,kind\n" + body, encoding="utf-8")
    return path


@pytest.fixture
def three_pages(cli, db, tmp_path):
    """D-0001 with three `text` pages."""
    ids = add_files(cli, tmp_path / "in", [lambda p: mk.make_digital(p, pages=3, text_seed="L")])
    assert ids == ["D-0001"]
    return ids


def test_page_kinds_check_all_correct(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, [f"D-0001,{n},text" for n in (1, 2, 3)])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 0, result.stderr
    assert "100" in result.stdout
    for kind in KINDS:
        assert kind in result.stdout


def test_page_kinds_check_accepts_lowercase_short_id(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, [f"d-1,{n},text" for n in (1, 2, 3)])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 0, result.stderr
    assert "100" in result.stdout


def test_page_kinds_check_low_accuracy_exits_1(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, ["D-0001,1,text", "D-0001,2,text", "D-0001,3,scan"])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 1
    assert "66" in result.stdout + result.stderr  # 2 of 3 correct
    for kind in KINDS:
        assert kind in result.stdout


def test_page_kinds_check_unknown_document_names_line(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, ["D-0001,1,text", "D-0099,1,text"])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 1
    assert "3" in result.stderr  # header is line 1, the bad row is line 3
    assert "D-0099" in result.stderr


def test_page_kinds_check_unknown_page_names_line(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, ["D-0001,1,text", "D-0001,2,text", "D-0001,9,text"])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 1
    assert "4" in result.stderr


def test_page_kinds_check_bad_kind_names_line(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, ["D-0001,1,text", "D-0001,2,foo"])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 1
    assert "3" in result.stderr
    assert "foo" in result.stderr


def test_page_kinds_check_repeated_row_names_both_lines(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, ["D-0001,1,text", "D-0001,2,text", "D-0001,1,text"])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 1
    assert "строка 4" in result.stderr  # the repeat
    assert "строке 2" in result.stderr  # the first occurrence


def test_page_kinds_check_repeated_row_with_other_id_spelling(cli, tmp_path, three_pages):
    labels = write_labels(tmp_path, ["D-0001,1,text", "d-1,1,scan"])

    result = cli("page-kinds-check", labels)

    assert result.exit_code == 1
    assert "строка 3" in result.stderr
    assert "строке 2" in result.stderr


# --- verify (US4) ---------------------------------------------------------------------


@pytest.fixture
def verify_docs(cli, db, tmp_path):
    ids = add_files(
        cli,
        tmp_path / "in",
        [
            lambda p: mk.make_digital(p, pages=1, text_seed="V1"),
            lambda p: mk.make_digital(p, pages=2, text_seed="V2"),
        ],
    )
    assert ids == ["D-0001", "D-0002"]
    return ids


def test_verify_all_intact(cli, db, verify_docs):
    runs_before = run_count(db)

    result = cli("verify")

    assert result.exit_code == 0, result.stderr
    assert "Копии в порядке: 2" in result.stdout
    assert run_count(db) == runs_before


def test_verify_modified_copy_is_listed(cli, db, data_dir, verify_docs):
    copy = copy_of(db, data_dir, "D-0001")
    os.chmod(copy, 0o644)
    with copy.open("ab") as f:
        f.write(b"\x00tampered")

    result = cli("verify")

    assert result.exit_code == 1
    assert "D-0001" in result.stdout + result.stderr
    assert "D-0002" not in result.stdout + result.stderr


def test_verify_deleted_copy_is_listed(cli, db, data_dir, verify_docs):
    copy_of(db, data_dir, "D-0002").unlink()

    result = cli("verify")

    assert result.exit_code == 1
    assert "D-0002" in result.stdout + result.stderr


def test_verify_with_id_checks_only_that_document(cli, db, data_dir, verify_docs):
    copy = copy_of(db, data_dir, "D-0001")
    os.chmod(copy, 0o644)
    copy.write_bytes(copy.read_bytes() + b"x")

    ok = cli("verify", "D-0002")
    bad = cli("verify", "D-0001")

    assert ok.exit_code == 0, ok.stderr
    assert "Копии в порядке: 1" in ok.stdout
    assert bad.exit_code == 1
    assert "D-0001" in bad.stdout + bad.stderr


def test_verify_creates_no_run(cli, db, data_dir, verify_docs):
    copy_of(db, data_dir, "D-0001").unlink()
    runs_before = run_count(db)

    assert cli("verify").exit_code == 1
    assert cli("verify", "D-0002").exit_code == 0

    assert run_count(db) == runs_before
