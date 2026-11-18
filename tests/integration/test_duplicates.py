"""Integration tests for duplicate handling in `docreader add` (task T027, US2).

Everything goes through the CLI and the database; no internal functions are called.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tests.synthetic import make_pdfs as mk


def add_json(cli, *paths):
    result = cli("add", *paths, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def by_path(report: dict) -> dict[str, dict]:
    return {f["path"]: f for f in report["files"]}


def count_documents(db) -> int:
    return db.execute("SELECT count(*) FROM document").fetchone()[0]


def count_copies(data_dir: Path) -> int:
    return len([p for p in (data_dir / "originals").iterdir() if p.is_file()])


def make_three(folder: Path) -> list[Path]:
    folder.mkdir(parents=True)
    return [
        mk.make_digital(folder / f"{n}.pdf", pages=2, text_seed=f"seed-{n}") for n in "abc"
    ]


def test_same_folder_twice_changes_nothing(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    paths = make_three(folder)

    first = add_json(cli, folder)
    assert first["totals"]["added"] == 3
    copies_before = count_copies(data_dir)

    second = add_json(cli, folder)

    assert second["totals"] == {"files": 3, "added": 0, "existing": 3, "rejected": 0}
    first_entries, second_entries = by_path(first), by_path(second)
    for p in paths:
        key = str(p.resolve())
        assert second_entries[key]["status"] == "existing"
        assert second_entries[key]["document_id"] == first_entries[key]["document_id"]
    assert count_documents(db) == 3
    assert count_copies(data_dir) == copies_before == 3


def test_same_content_under_another_name_is_existing(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    original = mk.make_digital(folder / "contract.pdf", text_seed="A")
    first = add_json(cli, original)
    original_id = first["files"][0]["document_id"]
    copies_before = count_copies(data_dir)

    renamed = folder / "renamed.pdf"
    shutil.copyfile(original, renamed)
    second = add_json(cli, renamed)

    entry = second["files"][0]
    assert entry["status"] == "existing"
    assert entry["document_id"] == original_id
    assert second["totals"]["added"] == 0
    assert count_documents(db) == 1
    assert count_copies(data_dir) == copies_before == 1


def test_same_name_different_content_is_added_with_name_collision(cli, db, tmp_path):
    x = tmp_path / "x"
    y = tmp_path / "y"
    x.mkdir()
    y.mkdir()
    first_path = mk.make_digital(x / "contract.pdf", text_seed="A")
    second_path = mk.make_digital(y / "contract.pdf", text_seed="B")

    first = add_json(cli, first_path)
    first_id = first["files"][0]["document_id"]
    assert first_id == "D-0001"
    assert first["files"][0]["warnings"] == []

    second = add_json(cli, second_path)

    entry = second["files"][0]
    assert entry["status"] == "added"
    assert entry["document_id"] not in (None, first_id)
    assert len(entry["warnings"]) == 1
    warning = entry["warnings"][0]
    assert warning["code"] == "name_collision"
    assert first_id in warning["document_ids"]
    assert warning["message"] == "имя совпадает с D-0001 (другое содержимое)"
    assert count_documents(db) == 2


def test_name_collision_is_case_insensitive(cli, db, tmp_path):
    x = tmp_path / "x"
    y = tmp_path / "y"
    x.mkdir()
    y.mkdir()
    first_path = mk.make_digital(x / "contract.pdf", text_seed="A")
    second_path = mk.make_digital(y / "CONTRACT.pdf", text_seed="B")

    first_id = add_json(cli, first_path)["files"][0]["document_id"]
    entry = add_json(cli, second_path)["files"][0]

    assert entry["status"] == "added"
    assert [w["code"] for w in entry["warnings"]] == ["name_collision"]
    assert first_id in entry["warnings"][0]["document_ids"]


def test_two_identical_files_in_one_call(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    a = mk.make_digital(folder / "a.pdf", text_seed="same")
    b = mk.make_digital(folder / "b.pdf", text_seed="same")
    assert a.read_bytes() == b.read_bytes()

    report = add_json(cli, folder)

    entries = by_path(report)
    ea, eb = entries[str(a.resolve())], entries[str(b.resolve())]
    assert ea["status"] == "added"
    assert eb["status"] == "existing"
    assert eb["document_id"] == ea["document_id"]
    assert report["totals"] == {"files": 2, "added": 1, "existing": 1, "rejected": 0}
    assert count_documents(db) == 1
    assert count_copies(data_dir) == 1


def test_text_output_of_second_run_lists_existing(cli, db, tmp_path):
    folder = tmp_path / "in"
    make_three(folder)
    add_json(cli, folder)

    result = cli("add", folder)

    assert result.exit_code == 0, result.stderr
    assert "Уже есть: 3" in result.stdout
    assert "→ D-0001" in result.stdout


# --- restoring a lost copy on re-add (T053) ----------------------------------------------


def _only_copy(data_dir: Path) -> Path:
    copies = [p for p in (data_dir / "originals").iterdir() if p.is_file()]
    assert len(copies) == 1
    return copies[0]


def test_missing_copy_is_restored_on_re_add(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    source = mk.make_digital(folder / "a.pdf", pages=2, text_seed="restore-a")
    add_json(cli, folder)
    copy = _only_copy(data_dir)
    copy.unlink()
    assert cli("verify").exit_code == 1

    report = add_json(cli, folder)

    entry = by_path(report)[str(source.resolve())]
    assert entry["status"] == "existing"
    assert [w["code"] for w in entry["warnings"]] == ["copy_restored"]
    assert copy.read_bytes() == source.read_bytes()
    assert cli("verify").exit_code == 0
    assert count_documents(db) == 1


def test_damaged_copy_is_restored_on_re_add(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    source = mk.make_digital(folder / "a.pdf", pages=2, text_seed="restore-b")
    add_json(cli, folder)
    copy = _only_copy(data_dir)
    copy.chmod(0o644)
    copy.write_bytes(b"%PDF-1.7 damaged")

    report = add_json(cli, folder)

    entry = by_path(report)[str(source.resolve())]
    assert [w["code"] for w in entry["warnings"]] == ["copy_restored"]
    assert copy.read_bytes() == source.read_bytes()
    assert cli("verify").exit_code == 0


def test_intact_copy_gives_no_warning(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    source = mk.make_digital(folder / "a.pdf", pages=1, text_seed="restore-c")
    add_json(cli, folder)

    report = add_json(cli, folder)

    assert by_path(report)[str(source.resolve())]["warnings"] == []


def test_restored_copy_is_shown_in_text_report(cli, db, data_dir, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a.pdf", pages=1, text_seed="restore-d")
    add_json(cli, folder)
    _only_copy(data_dir).unlink()

    result = cli("add", folder)

    assert result.exit_code == 0
    assert (
        "! копия отсутствовала или была повреждена — восстановлена из этого файла"
        in result.stdout
    )
