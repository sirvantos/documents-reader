"""Synthetic gold files of tests/synthetic/gold (feature 02, T022).

The files are fictional. They must parse with the parsers of `gold.py`
(template and blind CSV) and have the shape of contracts/files.md (results JSON).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docreader import gold

GOLD_DIR = Path(__file__).resolve().parents[1] / "synthetic" / "gold"
REGISTRY = {"D-0001", "D-0002"}
RESULTS = {"found", "not_found", "rejected", "failed"}


def test_template_filled_has_one_error_one_absent_one_variant_cell() -> None:
    data = (GOLD_DIR / "template-filled.csv").read_bytes()
    parsed = gold.parse_template(data, REGISTRY)

    assert parsed.kind is gold.LoadKind.TEMPLATE
    assert len(parsed.errors) == 1
    assert "amount_with_vat" in parsed.errors[0].where
    absent = [k for k, v in parsed.values.items() if v.state is gold.GoldState.ABSENT]
    assert absent == [("D-0002", "contractor_name_short")]
    variants = [k for k, v in parsed.values.items() if len(v.values_text) > 1]
    assert variants == [("D-0002", "customer_name_short")]
    assert parsed.skipped_rows == []


def test_template_filled_leaves_empty_cell_unlabeled() -> None:
    data = (GOLD_DIR / "template-filled.csv").read_bytes()
    parsed = gold.parse_template(data, REGISTRY)

    assert ("D-0002", "contract_end_date") not in parsed.values
    assert ("D-0002", "contract_end_date") in parsed.coverage


def test_blind_filled_parses_without_errors() -> None:
    data = (GOLD_DIR / "blind-filled.csv").read_bytes()
    parsed = gold.parse_template(data, REGISTRY, kind=gold.LoadKind.BLIND)

    assert parsed.kind is gold.LoadKind.BLIND
    assert parsed.errors == []
    assert parsed.skipped_rows == []
    assert ("D-0001", "contract_end_date") in parsed.values


def test_field_results_has_shape_of_contract() -> None:
    doc: Any = json.loads((GOLD_DIR / "field-results.json").read_bytes().decode("utf-8-sig"))

    assert doc["format"] == "docreader-field-results/1"
    assert isinstance(doc["source"], str)
    assert isinstance(doc["values"], list)
    documents = set()
    results = set()
    for item in doc["values"]:
        assert item["document"] in REGISTRY
        assert isinstance(item["field"], str)
        assert item["result"] in RESULTS
        documents.add(item["document"])
        results.add(item["result"])
        if item["result"] == "found":
            assert isinstance(item["value"], str)
            assert item["value"]
        else:
            assert "value" not in item
    assert documents == REGISTRY
    assert results == RESULTS
