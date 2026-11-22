"""Prototype fields and results equal the CHECKs of `0005_extraction.sql` (feature 05, T006)."""

from __future__ import annotations

import re

import pytest

from docreader.db import MIGRATIONS_DIR
from docreader.fields import FIELD_NAMES, PROTOTYPE_FIELDS, Kind, Result, spec
from docreader.stages import RunStage


def _migration_check_values(column: str) -> list[str]:
    """Values of `CHECK (column IN (...))` in the feature 05 migration, in order."""
    sql = (MIGRATIONS_DIR / "0005_extraction.sql").read_text(encoding="utf-8")
    match = re.search(rf"CHECK \({column} IN \(([^)]*)\)\)", sql)
    assert match, f"no CHECK on {column} in 0005_extraction.sql"
    return re.findall(r"'([a-z_]+)'", match.group(1))


def test_field_names_equal_the_schema_check_in_order():
    assert list(FIELD_NAMES) == _migration_check_values("field")


def test_field_names_equal_the_schema_check_as_sets_and_counts():
    checked = _migration_check_values("field")
    assert len(FIELD_NAMES) == len(checked) == 6
    assert set(FIELD_NAMES) == set(checked)


def test_results_equal_the_schema_check():
    assert [r.value for r in Result] == _migration_check_values("result")


def test_prototype_fields_in_catalog_order_with_labels_and_kinds():
    assert [(f.name, f.label, f.kind) for f in PROTOTYPE_FIELDS] == [
        ("contract_number", "номер договора", Kind.IDENTIFIER),
        ("customer_name_short", "заказчик", Kind.NAME),
        ("contractor_name_short", "подрядчик", Kind.NAME),
        ("amount_without_vat", "цена без НДС", Kind.AMOUNT),
        ("amount_with_vat", "цена с НДС", Kind.AMOUNT),
        ("contract_end_date", "дата окончания", Kind.DATE),
    ]


def test_spec_returns_the_field_by_name():
    assert spec("amount_with_vat").label == "цена с НДС"
    assert spec("contract_end_date").kind is Kind.DATE


def test_spec_raises_key_error_for_an_unknown_name():
    with pytest.raises(KeyError):
        spec("unknown_field")


def test_kind_values():
    assert [k.value for k in Kind] == ["identifier", "name", "amount", "date"]


def test_extraction_run_stage():
    assert RunStage.EXTRACTION == "extraction"
