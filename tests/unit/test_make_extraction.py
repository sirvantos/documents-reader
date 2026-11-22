"""Tests of the synthetic extraction contracts (feature 05, task T002, research R-14).

The generator writes only under pytest tmp_path. Each variant has a PDF and a truth file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from tests.synthetic.make_pdfs import GENERATOR_VERSION, make_extraction_contracts

VARIANTS = ("base", "missing", "injection", "forms", "no_tail", "three_parties")
FIELDS = (
    "contract_number",
    "customer_name_short",
    "contractor_name_short",
    "amount_without_vat",
    "amount_with_vat",
    "contract_end_date",
)


@pytest.fixture(scope="module")
def contracts(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("extraction")
    make_extraction_contracts(folder)
    return folder


def _page_text(path: Path, index: int) -> str:
    document = pdfium.PdfDocument(str(path))
    try:
        return str(document[index].get_textpage().get_text_range())
    finally:
        document.close()


def _page_count(path: Path) -> int:
    document = pdfium.PdfDocument(str(path))
    try:
        return len(document)
    finally:
        document.close()


def test_writes_six_pdfs(contracts: Path) -> None:
    for variant in VARIANTS:
        assert (contracts / f"{variant}.pdf").is_file()


def test_truth_files_are_valid(contracts: Path) -> None:
    for variant in VARIANTS:
        truth = json.loads(
            (contracts / f"{variant}.truth.json").read_text(encoding="utf-8")
        )
        assert truth["variant"] == variant
        assert truth["generator_version"] == GENERATOR_VERSION
        assert set(truth["fields"]) == set(FIELDS)
        assert "other_party" in truth
        for field in FIELDS:
            assert truth["fields"][field]["result"] in {"found", "not_found"}


def test_three_parties_has_other_party(contracts: Path) -> None:
    truth = json.loads((contracts / "three_parties.truth.json").read_text("utf-8"))
    assert truth["other_party"] == {"found": True, "clause_key": "преамбула", "page": 1}


def test_base_pages_and_header(contracts: Path) -> None:
    base = contracts / "base.pdf"
    assert _page_count(base) == 3
    assert "№ ДП-17/2026" in _page_text(base, 0)


def test_no_tail_has_two_pages(contracts: Path) -> None:
    assert _page_count(contracts / "no_tail.pdf") == 2
