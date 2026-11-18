"""Reading results across other commands (tasks T019, T024; FR-012, R-9).

Part «удаление и пересортировка»: `remove` drops every reading row, `reclassify`
that changes page kinds sends the document back to `read` without arguments.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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


# --- сброс следующих этапов (T024; US1-8, FR-012, R-9) ------------------------------------

LATER = ("structure", "extraction", "checks", "indexing")


def stages(db, doc_id: str) -> dict[str, tuple]:
    return {
        stage: (state, reason, run_id)
        for stage, state, reason, run_id in db.execute(
            "SELECT stage, state, reason, run_id FROM stage_status WHERE document_id = %s",
            (doc_id,),
        )
    }


def arrange_later_stages(db, doc_id: str) -> None:
    """structure, extraction done; checks needs_review; indexing stays pending."""
    db.execute(
        "UPDATE stage_status SET state = 'done' WHERE document_id = %s"
        " AND stage IN ('structure', 'extraction')",
        (doc_id,),
    )
    db.execute(
        "UPDATE stage_status SET state = 'needs_review', reason = 'нужна проверка'"
        " WHERE document_id = %s AND stage = 'checks'",
        (doc_id,),
    )


def simulate_older_text(db, doc_id: str) -> None:
    db.execute(
        "UPDATE document_text SET text_sha256 = %s WHERE document_id = %s", ("0" * 64, doc_id)
    )


def read_json(cli, *args) -> dict:
    result = cli("read", *args, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def read_doc(cli, tmp_path) -> str:
    add(cli, tmp_path / "in", [mk.make_contract_ru])
    assert read_json(cli)["documents"][0]["text_changed"] is False  # first read
    return "D-0001"


def test_changed_text_resets_later_stages(cli, db, read_doc) -> None:
    arrange_later_stages(db, read_doc)
    simulate_older_text(db, read_doc)
    before = stages(db, read_doc)

    out = read_json(cli, read_doc)

    after = stages(db, read_doc)
    run_id = out["run_id"]
    for stage in ("structure", "extraction", "checks"):
        assert after[stage] == ("pending", "текст изменён", run_id), stage
    assert after["indexing"] == before["indexing"]  # was already pending: untouched
    assert out["documents"][0]["text_changed"] is True


def test_changed_text_is_listed_in_text_output(cli, db, read_doc) -> None:
    simulate_older_text(db, read_doc)
    result = cli("read", read_doc)
    assert result.exit_code == 0, result.stderr
    assert "Текст изменился, следующие этапы сброшены: D-0001" in result.stdout


def test_unchanged_text_keeps_later_stages(cli, db, read_doc) -> None:
    arrange_later_stages(db, read_doc)
    before = {s: v for s, v in stages(db, read_doc).items() if s in LATER}

    out = read_json(cli, read_doc)

    assert {s: v for s, v in stages(db, read_doc).items() if s in LATER} == before
    assert out["documents"][0]["text_changed"] is False
    assert "Текст изменился" not in cli("read", read_doc).stdout


def test_first_read_does_not_touch_later_stages(cli, db, tmp_path) -> None:
    add(cli, tmp_path / "in", [mk.make_contract_ru])
    arrange_later_stages(db, "D-0001")  # artificial: later stages before any reading
    before = {s: v for s, v in stages(db, "D-0001").items() if s in LATER}

    read_json(cli)

    assert {s: v for s, v in stages(db, "D-0001").items() if s in LATER} == before


def test_reset_does_not_delete_other_rows(cli, db, read_doc) -> None:
    arrange_later_stages(db, read_doc)
    simulate_older_text(db, read_doc)
    read_json(cli, read_doc)
    # Results of later stages do not exist yet (features 04+); the stage rows stay.
    assert db.execute(
        "SELECT count(*) FROM stage_status WHERE document_id = %s", (read_doc,)
    ).fetchone()[0] == 5
