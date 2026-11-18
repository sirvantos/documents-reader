"""Reading results across other commands (tasks T019, T024; FR-012, R-9).

Part «удаление и пересортировка»: `remove` drops every reading row, `reclassify`
that changes page kinds sends the document back to `read` without arguments.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.synthetic import make_pdfs as mk

READING_TABLES = ("page_text", "page_flag", "document_text", "text_span")


def add(cli, folder: Path, makers: list) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    for i, make in enumerate(makers):
        make(folder / f"f{i}.pdf")
    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    return sorted(f["document_id"] for f in json.loads(result.stdout)["files"])


def rows(db, table: str, doc_id: str) -> int:
    return db.execute(
        f"SELECT count(*) FROM {table} WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]


def reading_state(db, doc_id: str) -> str:
    return db.execute(
        "SELECT state FROM stage_status WHERE document_id = %s AND stage = 'reading'",
        (doc_id,),
    ).fetchone()[0]


def flag_codes(db, doc_id: str) -> set[str]:
    return {
        r[0]
        for r in db.execute("SELECT code FROM page_flag WHERE document_id = %s", (doc_id,))
    }


# --- удаление и пересортировка (T019) ------------------------------------------------------


def test_remove_drops_all_reading_rows(cli, db, tmp_path) -> None:
    # D-0002 (mixed: text pages and a picture page) has rows in all four tables.
    assert add(cli, tmp_path / "in", [mk.make_contract_ru, mk.make_mixed]) == ["D-0001", "D-0002"]
    assert cli("read").exit_code == 0
    for table in READING_TABLES:
        assert rows(db, table, "D-0002") > 0, table

    result = cli("remove", "D-0002", "--yes")

    assert result.exit_code == 0, result.stderr
    for table in READING_TABLES:
        assert rows(db, table, "D-0002") == 0, table
    for table in ("page_text", "document_text", "text_span"):
        assert rows(db, table, "D-0001") > 0, table


def test_reclassify_that_changes_kinds_sends_document_back_to_read(
    cli, db, data_dir, tmp_path
) -> None:
    # Strict thresholds: the invisible text layer is too short, the pages are `scan`.
    settings = data_dir / "settings.toml"
    settings.write_text("[page_kinds]\ntext_min_chars = 2000\n", encoding="utf-8")
    add(cli, tmp_path / "in", [mk.make_image_with_invisible_text])
    assert cli("read").exit_code == 0
    assert reading_state(db, "D-0001") == "needs_review"
    assert flag_codes(db, "D-0001") == {"scan_unread"}

    settings.write_text("", encoding="utf-8")
    assert cli("reclassify").exit_code == 0
    assert reading_state(db, "D-0001") == "pending"

    result = cli("read", "--json")

    assert result.exit_code == 0, result.stderr
    assert [d["id"] for d in json.loads(result.stdout)["documents"]] == ["D-0001"]
    pages = db.execute(
        "SELECT lines FROM page_text WHERE document_id = 'D-0001' ORDER BY page_number"
    ).fetchall()
    assert pages and all(lines for (lines,) in pages)
    assert "scan_unread" not in flag_codes(db, "D-0001")
