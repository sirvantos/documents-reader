"""Integration tests for page layout in `docreader read` (task T042, feature 03, US1-5..7, US4).

Columns, ruled tables, signature sheet, page rotation. Everything goes through the CLI
and the database; no internal functions are called.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.synthetic import make_pdfs as mk

REORDER_REASON = "порядок чтения не определён"


# --- helpers ------------------------------------------------------------------------


def read_doc(cli, tmp_path: Path, make) -> str:
    folder = tmp_path / "in"
    folder.mkdir(parents=True, exist_ok=True)
    make(folder / "f0.pdf")
    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    (entry,) = json.loads(result.stdout)["files"]
    doc_id = entry["document_id"]
    result = cli("read", doc_id)
    assert result.exit_code == 0, result.stderr
    return doc_id


def page_rows(db, doc_id: str) -> dict[int, dict]:
    return {
        page: {"lines": lines, "has_table": has_table, "rotation": rotation,
               "width": width, "height": height}
        for page, lines, has_table, rotation, width, height in db.execute(
            "SELECT page_number, lines, has_table, rotation, width, height FROM page_text"
            " WHERE document_id = %s ORDER BY page_number",
            (doc_id,),
        )
    }


def flags(db, doc_id: str, page: int) -> list[str]:
    return [
        code
        for (code,) in db.execute(
            "SELECT code FROM page_flag WHERE document_id = %s AND page_number = %s"
            " ORDER BY code",
            (doc_id, page),
        )
    ]


def clean_text(db, doc_id: str) -> str:
    return db.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]


def texts(lines: list[dict]) -> list[str]:
    return [ln["text"] for ln in lines]


def assert_bboxes_inside(row: dict) -> None:
    for ln in row["lines"]:
        left, bottom, right, top = ln["bbox"]
        assert 0 <= left < right <= row["width"], ln
        assert 0 <= bottom < top <= row["height"], ln


# --- US1-5: two columns -------------------------------------------------------------


def test_two_columns_are_read_column_by_column(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_requisites_columns_ru)

    row = page_rows(db, doc)[1]
    lines = row["lines"]
    assert texts(lines) == list(mk.REQUISITES_COLUMNS_PAGES[0])
    assert flags(db, doc, 1) == []
    assert not any(ln["table"] for ln in lines)
    assert not row["has_table"]

    customer = [i for i, ln in enumerate(lines) if ln["text"] in mk._REQUISITES_CUSTOMER]
    contractor = [i for i, ln in enumerate(lines) if ln["text"] in mk._REQUISITES_CONTRACTOR]
    assert customer == list(range(customer[0], customer[0] + len(mk._REQUISITES_CUSTOMER)))
    assert contractor == list(range(contractor[0], contractor[0] + len(mk._REQUISITES_CONTRACTOR)))
    assert max(customer) < min(contractor)
    assert {lines[i]["column"] for i in customer} == {1}
    assert {lines[i]["column"] for i in contractor} == {2}

    text = clean_text(db, doc)
    left_block = "\n".join(mk._REQUISITES_CUSTOMER)
    assert left_block in text
    assert text.index(left_block) < text.index(mk._REQUISITES_CONTRACTOR[0])


def test_ruled_two_cell_table_is_read_cell_by_cell(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_requisites_table_ru)

    row = page_rows(db, doc)[1]
    lines = row["lines"]
    assert texts(lines) == list(mk.REQUISITES_TABLE_PAGES[0])
    assert row["has_table"] is True
    assert flags(db, doc, 1) == []

    customer = [ln for ln in lines if ln["text"] in mk._REQUISITES_CUSTOMER]
    contractor = [ln for ln in lines if ln["text"] in mk._REQUISITES_CONTRACTOR]
    assert all(ln["table"] is not None for ln in customer + contractor)
    assert {ln["table"]["cell"] for ln in customer} == {0}
    assert {ln["table"]["cell"] for ln in contractor} == {1}
    assert {ln["table"]["row"] for ln in customer + contractor} == {0}
    assert lines.index(customer[-1]) < lines.index(contractor[0])
    assert lines[0]["table"] is None  # the heading is outside the table


# --- US1-6: continuation on the next page -------------------------------------------


def test_columns_continue_on_the_next_page(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_requisites_columns_ru)

    lines = page_rows(db, doc)[2]["lines"]
    assert flags(db, doc, 2) == []
    assert texts(lines) == list(mk.REQUISITES_COLUMNS_PAGES[1])
    by_text = {ln["text"]: ln["column"] for ln in lines}
    for line in mk._REQUISITES_CUSTOMER_NEXT:
        assert by_text[line] == 1
    for line in mk._REQUISITES_CONTRACTOR_NEXT:
        assert by_text[line] == 2
    for line in mk._REQUISITES_SIGN:
        assert by_text[line] is None


# --- US1-7, FR-016: signature sheet -------------------------------------------------


def test_signature_sheet_stays_in_text_with_positions(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_signature_sheet_ru)

    pages = page_rows(db, doc)
    last = pages[3]["lines"]
    assert flags(db, doc, 3) == []
    text = clean_text(db, doc)
    for line in mk.SIGNATURE_SHEET_LINES:
        assert line in text
    for line in mk.SIGNATURE_SHEET_LINES:
        (found,) = [ln for ln in last if ln["text"] == line]
        assert found["role"] == "body"
        assert len(found["bbox"]) == 4

    for page in (1, 2):
        roles = {ln["role"] for ln in pages[page]["lines"]}
        assert "header" in roles
    header = next(ln["text"] for ln in pages[1]["lines"] if ln["role"] == "header")
    assert header not in text


# --- US4-1, FR-007: price table -----------------------------------------------------


def test_price_table_is_stored_row_by_row(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_price_table_ru)

    row = page_rows(db, doc)[1]
    lines = row["lines"]
    assert row["has_table"] is True
    assert flags(db, doc, 1) == []
    assert texts(lines) == list(mk.PRICE_TABLE_PAGES[0])
    cells = [ln["table"] for ln in lines if ln["table"] is not None]
    assert len(cells) == 12
    assert [(c["row"], c["cell"]) for c in cells] == [
        (r, c) for r in range(4) for c in range(3)
    ]
    assert len({c["t"] for c in cells}) == 1

    result = cli("text", doc, "--page", "1")
    assert result.exit_code == 0, result.stderr
    assert "табл." in result.stdout
    assert "Таблица: есть" in result.stdout


# --- FR-018: rotation ---------------------------------------------------------------


def test_page_rotated_as_a_whole_reads_in_normal_order(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_rotated_page_ru)

    row = page_rows(db, doc)[1]
    assert row["rotation"] == 90
    assert texts(row["lines"]) == list(mk.ROTATED_PAGE_PAGES[0])
    assert all(ln["role"] == "body" for ln in row["lines"])
    assert flags(db, doc, 1) == []


def test_text_turned_inside_the_page_gets_order_flag(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_rotated_text_ru)

    lines = page_rows(db, doc)[1]["lines"]
    assert flags(db, doc, 1) == ["reading_order_unknown"]
    turned = len(mk.ROTATED_TEXT_TURNED_LINES)
    assert [ln["role"] for ln in lines[-turned:]] == ["rotated"] * turned
    assert all(ln["role"] == "body" for ln in lines[:-turned])
    assert sorted(texts(lines[-turned:])) == sorted(mk.ROTATED_TEXT_TURNED_LINES)
    state, reason = db.execute(
        "SELECT state, reason FROM stage_status WHERE document_id = %s AND stage = 'reading'",
        (doc,),
    ).fetchone()
    assert state == "needs_review"
    assert REORDER_REASON in reason


def test_spaced_table_is_read_row_by_row_without_order_flag(cli, db, tmp_path):
    # T058 (2026-11-22): rows of a table without rules whose cells line up are read row
    # by row and no longer raise reading_order_unknown (was: flag, research R-8)
    doc = read_doc(cli, tmp_path, mk.make_spaced_table_ru)

    row = page_rows(db, doc)[1]
    assert flags(db, doc, 1) == []
    assert texts(row["lines"]) == [" ".join(cells) for cells in mk.SPACED_TABLE_PAGES[0]]
    assert row["has_table"] is False
    assert not any(ln["table"] for ln in row["lines"])


# --- bbox space ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "make",
    [
        mk.make_requisites_columns_ru,
        mk.make_requisites_table_ru,
        mk.make_price_table_ru,
        mk.make_rotated_page_ru,
        mk.make_rotated_text_ru,
        mk.make_spaced_table_ru,
        mk.make_signature_sheet_ru,
    ],
    ids=lambda f: f.__name__,
)
def test_bboxes_lie_inside_the_unrotated_page_box(cli, db, tmp_path, make):
    doc = read_doc(cli, tmp_path, make)

    pages = page_rows(db, doc)
    assert pages
    for row in pages.values():
        assert row["lines"]
        assert_bboxes_inside(row)
