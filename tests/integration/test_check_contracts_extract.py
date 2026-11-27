"""Extraction of the synthetic check contracts (feature 06, T006).

Each check contract goes through add, read and parse, then `extract` with the model answer
written in `check_fixtures.CHECK_ANSWERS`. Every field the answer gives as found must be
stored as found (its quote confirmed by the program check of feature 05); the fields the
answer gives as NOT_FOUND must be stored as not_found.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts
from tests.integration.extraction_fixtures import field_rows

FIELDS = (
    "contract_number",
    "customer_name_short",
    "contractor_name_short",
    "amount_without_vat",
    "amount_with_vat",
    "contract_end_date",
)


@pytest.fixture
def checks(cli, tmp_path: Path) -> dict[str, str]:
    return add_check_contracts(cli, tmp_path / "in")


@pytest.mark.parametrize("name", sorted(CHECK_ANSWERS))
def test_answer_is_stored_as_checked(cli, db, checks, use_model, name: str) -> None:
    model = use_model(ScriptedModel(CHECK_ANSWERS[name]))
    result = cli("extract", checks[name], "--json")
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert [d["document_id"] for d in report["documents"]] == [checks[name]]
    assert len(model.requests) == 1

    expected = json.loads(CHECK_ANSWERS[name])
    rows = field_rows(db, checks[name])
    for field in FIELDS:
        given = expected[field]
        row = rows[field]
        if given["found"]:
            assert row["result"] == "found", (name, field, row["reason"])
        else:
            assert row["result"] == "not_found", (name, field)
