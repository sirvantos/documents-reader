"""The rows of the table: every registry document with six cells (feature 10, T011, R-5).

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).

`table_answer.load_rows(conn, settings) -> list[DocRow]` — every document of the registry
in id order; cells by `checks.effective_cell`; a document without extracted fields has all
six cells `no_extraction`, one whose checks are missing or stale (`checks.split_fresh`) all
six `checks_stale` — both without values; clause id `format_clause_id(doc, clause_key)`;
flags of `field_status` carried. Nothing is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docreader import table_answer
from docreader.checks import CellState
from docreader.config import load_settings
from tests.integration.table_fixtures import (
    EXPECTED_CELLS,
    FIELDS,
    add_checked_contracts,
    extract_contract,
)

TABLES = ("document", "field_value", "field_status", "field_decision", "run")


def _counts(db) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


@pytest.fixture
def ids(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return add_checked_contracts(cli, use_model, tmp_path / "in")


def _by_id(db) -> dict[str, table_answer.DocRow]:  # type: ignore[no-untyped-def]
    return {r.document_id: r for r in table_answer.load_rows(db, load_settings())}


def test_every_registry_document_in_id_order(db, ids) -> None:  # type: ignore[no-untyped-def]
    rows = table_answer.load_rows(db, load_settings())
    assert [r.document_id for r in rows] == sorted(ids.values())
    for r in rows:
        assert set(r.cells) == set(FIELDS), r.document_id


def test_cells_of_checked_contracts(db, ids) -> None:  # type: ignore[no-untyped-def]
    rows = _by_id(db)
    for name, doc in ids.items():
        for field, (state, value, clause) in EXPECTED_CELLS[name].items():
            got = rows[doc].cells[field]
            assert (got.state.value, got.value) == (state, value), (name, field)
            if clause is not None:
                assert got.clause_id == f"{doc}/{clause}", (name, field)


def test_flags_carried(db, ids) -> None:  # type: ignore[no-untyped-def]
    db.execute("UPDATE field_status SET flags = ARRAY['document_needs_review']"
               " WHERE document_id = %s AND field = 'amount_with_vat'", (ids["check-clean"],))
    cell = _by_id(db)[ids["check-clean"]].cells["amount_with_vat"]
    assert cell.flags == ("document_needs_review",)
    assert cell.state is CellState.EFFECTIVE


def test_document_without_extraction(cli, use_model, db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    ids = add_checked_contracts(cli, use_model, tmp_path / "in", skip=("check-clean",))
    cells = _by_id(db)[ids["check-clean"]].cells
    for field in FIELDS:
        assert (cells[field].state, cells[field].value) == (CellState.NO_EXTRACTION, None)
    assert _by_id(db)[ids["check-vat"]].cells["amount_with_vat"].state is CellState.UNREVIEWED


def test_document_extracted_but_never_checked(cli, use_model, db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    ids = add_checked_contracts(cli, use_model, tmp_path / "in", skip=("check-clean",))
    extract_contract(cli, use_model, ids["check-clean"], "check-clean")
    cells = _by_id(db)[ids["check-clean"]].cells
    for field in FIELDS:
        assert (cells[field].state, cells[field].value) == (CellState.CHECKS_STALE, None)


def test_document_extracted_again_without_check(cli, use_model, db, ids) -> None:  # type: ignore[no-untyped-def]
    extract_contract(cli, use_model, ids["check-clean"], "check-clean")
    stale = db.execute(
        "SELECT count(*) FROM field_status s JOIN field_value v USING (document_id, field)"
        " WHERE s.document_id = %s AND s.extraction_run_id <> v.run_id",
        (ids["check-clean"],),
    ).fetchone()[0]
    assert stale == 6, "the fixture must leave the checks of the old extraction"
    cells = _by_id(db)[ids["check-clean"]].cells
    for field in FIELDS:
        assert cells[field].state is CellState.CHECKS_STALE
    other = _by_id(db)[ids["check-rate10"]].cells["amount_with_vat"]
    assert (other.state, other.value) == (CellState.EFFECTIVE, "1100000.00")


def test_load_rows_writes_nothing(db, ids) -> None:  # type: ignore[no-untyped-def]
    before = _counts(db)
    table_answer.load_rows(db, load_settings())
    assert _counts(db) == before


def test_empty_registry(cli, db) -> None:  # type: ignore[no-untyped-def]
    assert table_answer.load_rows(db, load_settings()) == []
