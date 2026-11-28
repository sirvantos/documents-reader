"""The expected table of `table_fixtures` matches the stored fields and statuses (T005).

Checked directly on `field_value`, `field_status` and `checks.effective_cell`, so the
fixture is right before `load_rows` (T011) is written against it.
"""

from __future__ import annotations

import json
from pathlib import Path

from docreader.checks import CellState, FieldStatus, effective_cell
from tests.integration.table_fixtures import (
    EXPECTED_CELLS,
    FIELDS,
    add_checked_contracts,
    expected_value,
    reply,
)


def test_expected_cells_match_the_database(cli, use_model, db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    ids = add_checked_contracts(cli, use_model, tmp_path / "in")
    assert set(ids) == set(EXPECTED_CELLS)
    for name, doc in ids.items():
        rows = db.execute(
            "SELECT v.field, s.status, s.flags, v.result, v.value_normalized, v.clause_key"
            " FROM field_value v JOIN field_status s USING (document_id, field)"
            " WHERE v.document_id = %s",
            (doc,),
        ).fetchall()
        got = {}
        for field, status, flags, result, value, clause in rows:
            state, cell_value = effective_cell(FieldStatus(status), flags, result, value, None)
            counted = state in (CellState.EFFECTIVE, CellState.UNREVIEWED)
            got[field] = (state.value, cell_value, clause if counted else None)
        assert set(got) == set(FIELDS), name
        assert got == EXPECTED_CELLS[name], name


def test_expected_value_and_reply() -> None:
    assert expected_value("check-vat", "amount_with_vat") is None
    assert expected_value("check-vat", "amount_with_vat", include_unreviewed=True) == "1250000.00"
    assert expected_value("check-exempt", "amount_with_vat", include_unreviewed=True) is None
    data = json.loads(reply(action="count", field="party", op="eq", value="Альфа"))
    assert data == {"kind": "query", "action": "count", "field": "party", "op": "eq",
                    "value": "Альфа", "value_to": None, "reason": None, "other": None}
