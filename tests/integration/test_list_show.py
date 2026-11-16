"""Integration tests for `docreader list` and `docreader show` (task T038, US4).

Everything goes through the CLI and the database; no internal functions are called.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.synthetic import make_pdfs as mk

STAGES = ["reading", "structure", "extraction", "checks", "indexing"]
HEADER_WORDS = [
    "ID", "Имя", "Стр.", "Текст", "Скан", "Скан+т",
    "Чтение", "Структура", "Извлеч.", "Проверки", "Индекс.",
]
KIND_LABELS = {
    "text": "готовый текст",
    "scan": "скан",
    "scan_with_text": "скан со встроенным текстом",
}


def add(cli, folder: Path) -> dict:
    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def make_set(tmp_path: Path) -> Path:
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_digital(folder / "a_dogovor.pdf", pages=3, text_seed="one")
    mk.make_mixed(folder / "b_mixed.pdf", pages=4)
    mk.make_image_only(folder / "c_scan.pdf", pages=2)
    return folder


def list_json(cli) -> list[dict]:
    result = cli("list", "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def row_of(text: str, doc_id: str) -> str:
    rows = [ln for ln in text.splitlines() if ln.startswith(doc_id)]
    assert len(rows) == 1, text
    return rows[0]


def set_state(db, doc_id: str, stage: str, state: str, reason: str | None) -> None:
    db.execute(
        "UPDATE stage_status SET state=%s, reason=%s WHERE document_id=%s AND stage=%s",
        (state, reason, doc_id, stage),
    )


def test_list_on_empty_registry(cli):
    result = cli("list")
    assert result.exit_code == 0, result.stderr
    assert "Реестр пуст" in result.stdout


def test_list_text_has_header_and_row_per_document(cli, tmp_path):
    add(cli, make_set(tmp_path))

    result = cli("list")

    assert result.exit_code == 0, result.stderr
    header = result.stdout.splitlines()[0]
    for word in HEADER_WORDS:
        assert word in header
    ids = [ln.split()[0] for ln in result.stdout.splitlines() if ln.startswith("D-")]
    assert ids == ["D-0001", "D-0002", "D-0003"]

    # a_dogovor.pdf: 3 text pages; b_mixed.pdf: 3 text + 1 scan; c_scan.pdf: 2 scans
    expected = {
        "D-0001": ("a_dogovor.pdf", ["3", "3", "0", "0"]),
        "D-0002": ("b_mixed.pdf", ["4", "3", "1", "0"]),
        "D-0003": ("c_scan.pdf", ["2", "0", "2", "0"]),
    }
    for doc_id, (name, counts) in expected.items():
        tokens = row_of(result.stdout, doc_id).split()
        assert tokens[1] == name
        assert tokens[2:6] == counts
        assert tokens[6:] == ["ожидает"] * 5


def test_list_truncates_long_name_in_text_but_not_in_json(cli, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    name = "d" * 49 + ".pdf"  # 53 characters
    mk.make_digital(folder / name, pages=1)
    add(cli, folder)

    text = cli("list")

    assert text.exit_code == 0, text.stderr
    row = row_of(text.stdout, "D-0001")
    assert name[:39] + "…" in row
    assert name not in row
    assert list_json(cli)[0]["original_name"] == name


def test_list_json_shape_for_fresh_documents(cli, tmp_path):
    add(cli, make_set(tmp_path))

    docs = list_json(cli)

    assert isinstance(docs, list)
    assert [d["id"] for d in docs] == ["D-0001", "D-0002", "D-0003"]
    second = docs[1]
    assert second["original_name"] == "b_mixed.pdf"
    assert second["page_count"] == 4
    assert second["added_at"]
    assert second["page_kinds"] == {"text": 3, "scan": 1, "scan_with_text": 0}
    for d in docs:
        assert {"id", "original_name", "page_count", "added_at", "page_kinds", "stages"} <= set(d)
        assert list(d["stages"]) == STAGES
        for stage in STAGES:
            assert d["stages"][stage] == {"state": "pending", "reason": None}


def test_stage_states_in_list_and_show(cli, db, tmp_path):
    add(cli, make_set(tmp_path))
    set_state(db, "D-0001", "reading", "needs_review", "проверить вручную")

    listed = cli("list")
    assert "требует просмотра" in row_of(listed.stdout, "D-0001")
    assert "требует просмотра" not in row_of(listed.stdout, "D-0002")

    shown = cli("show", "D-0001")
    assert shown.exit_code == 0, shown.stderr
    assert "требует просмотра" in shown.stdout
    assert "проверить вручную" in shown.stdout

    stages = list_json(cli)[0]["stages"]
    assert stages["reading"] == {"state": "needs_review", "reason": "проверить вручную"}
    assert stages["structure"] == {"state": "pending", "reason": None}


def test_failed_and_done_states_have_russian_names(cli, db, tmp_path):
    add(cli, make_set(tmp_path))
    set_state(db, "D-0001", "extraction", "failed", "сбой чтения")
    set_state(db, "D-0001", "indexing", "done", None)

    row = row_of(cli("list").stdout, "D-0001")
    assert "ошибка" in row
    assert "готово" in row

    shown = cli("show", "D-0001").stdout
    assert "ошибка" in shown
    assert "сбой чтения" in shown
    assert "готово" in shown


def test_show_is_case_and_zero_padding_insensitive(cli, tmp_path):
    add(cli, make_set(tmp_path))

    full = cli("show", "D-0001")
    short = cli("show", "d-1")

    assert full.exit_code == 0, full.stderr
    assert short.exit_code == 0, short.stderr
    assert full.stdout == short.stdout
    assert "D-0001" in full.stdout


def test_show_json_has_all_fields_and_copy_matches_sha(cli, tmp_path):
    folder = make_set(tmp_path)
    add(cli, folder)

    result = cli("show", "D-0002", "--json")

    assert result.exit_code == 0, result.stderr
    doc = json.loads(result.stdout)
    listed = list_json(cli)[1]
    for key, value in listed.items():
        assert doc[key] == value
    source = folder / "b_mixed.pdf"
    assert doc["id"] == "D-0002"
    assert doc["source_path"] == str(source.resolve())
    assert doc["size_bytes"] == source.stat().st_size
    assert "note" in doc
    assert isinstance(doc["intake_run_id"], int)

    copy = Path(doc["copy_path"])
    assert copy.is_absolute()
    assert copy.exists()
    digest = hashlib.sha256(copy.read_bytes()).hexdigest()
    assert doc["sha256"] == digest == hashlib.sha256(source.read_bytes()).hexdigest()

    pages = doc["pages"]
    assert [p["page_number"] for p in pages] == [1, 2, 3, 4]
    assert [p["kind"] for p in pages] == ["text", "text", "text", "scan"]
    for p in pages:
        assert {"page_number", "kind", "char_count", "image_coverage", "invisible_text_share"} <= set(p)
    assert pages[0]["char_count"] > 0
    assert pages[3]["image_coverage"] > 0.5


def test_show_text_prints_sha_paths_and_page_kinds(cli, tmp_path):
    folder = make_set(tmp_path)
    add(cli, folder)
    doc = json.loads(cli("show", "D-0002", "--json").stdout)

    result = cli("show", "D-0002")

    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert doc["sha256"] in out
    assert doc["copy_path"] in out
    assert Path(doc["copy_path"]).is_absolute()
    assert doc["source_path"] in out
    assert "b_mixed.pdf" in out
    for page in doc["pages"]:
        assert str(page["page_number"]) in out
    assert KIND_LABELS["text"] in out
    assert KIND_LABELS["scan"] in out


def test_show_text_labels_scan_with_text_pages(cli, tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_image_with_invisible_text(folder / "ocr.pdf", pages=2)
    add(cli, folder)

    out = cli("show", "D-0001").stdout

    assert KIND_LABELS["scan_with_text"] in out


def test_show_unknown_id_fails(cli, tmp_path):
    add(cli, make_set(tmp_path))

    result = cli("show", "D-0099")

    assert result.exit_code == 1
    assert result.stderr.strip()


def test_show_malformed_id_fails(cli, tmp_path):
    add(cli, make_set(tmp_path))

    result = cli("show", "X-1")

    assert result.exit_code == 1
    assert result.stderr.strip()
