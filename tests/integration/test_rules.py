"""Rules extraction on synthetic contracts (feature 02, T015, research R-8).

The contracts of `make_rules_contracts` and the `base` extraction contract go through
add → read → parse; the rules run on the stored clean text and parse records.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from docreader import extraction, rules
from tests.synthetic import make_pdfs as mk


def _inputs(db: psycopg.Connection, doc_id: str):  # type: ignore[no-untyped-def]
    index = extraction._build_index(db, doc_id)
    sections = dict(
        db.execute(
            "SELECT key, section_title FROM clause WHERE document_id = %s", (doc_id,)
        ).fetchall()
    )
    return index, sections


@pytest.fixture
def docs(cli, db, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    folder = tmp_path / "in"
    folder.mkdir()
    mk.make_extraction_contract(folder / "base.pdf", "base")
    mk.make_rules_contracts(folder)
    assert cli("add", folder).exit_code == 0
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    return {
        name.removesuffix(".pdf"): doc
        for doc, name in db.execute("SELECT id, original_name FROM document").fetchall()
    }


def found(db: psycopg.Connection, doc_id: str) -> dict[str, list[tuple[str, str | None]]]:
    result = rules.extract_rules(*_inputs(db, doc_id))
    return {
        field: [(r.value_normalized or "", r.clause_key) for r in items]
        for field, items in result.items()
    }


def test_plain_contract_gives_all_six(db, docs) -> None:  # type: ignore[no-untyped-def]
    assert found(db, docs["rules-a"]) == {
        "contract_number": [("Р-11/2026", "преамбула")],
        "customer_name_short": [('ООО "Альфа"', "преамбула")],
        "contractor_name_short": [('ООО "Бета"', "преамбула")],
        "amount_without_vat": [("2400000.00", "2.1")],
        "amount_with_vat": [("2880000.00", "2.1")],
        "contract_end_date": [("2027-12-31", "5.1")],
    }


def test_base_extraction_contract(db, docs) -> None:  # type: ignore[no-untyped-def]
    got = found(db, docs["base"])
    assert got["contract_number"] == [("ДП-17/2026", "преамбула")]
    assert got["amount_without_vat"] == [("1200000.00", "2.1")]
    assert got["amount_with_vat"] == [("1440000.00", "2.1")]
    assert got["contract_end_date"] == [("2027-03-25", "4.1")]
    assert [v for v, _ in got["customer_name_short"]] == ['ООО "Альфа"']
    assert [v for v, _ in got["contractor_name_short"]] == ['ООО "Бета"']


def test_traps_are_not_taken(db, docs) -> None:  # type: ignore[no-untyped-def]
    got = found(db, docs["rules-b"])
    # the protocol and the power of attorney numbers are not the contract number
    assert got["contract_number"] == [("Р-12/2026", "преамбула")]
    # penalty and security amounts outside the price section are not prices; VAT amount neither
    assert got["amount_without_vat"] == [("3600000.00", "2.1")]
    assert len(got["amount_with_vat"]) == 1
    # the other date next to the term clause is not the end date
    assert got["contract_end_date"] == [("2028-06-30", "5.1")]


def test_two_different_values_are_both_returned(db, docs) -> None:  # type: ignore[no-untyped-def]
    got = found(db, docs["rules-c"])
    assert got["amount_without_vat"] == [("900000.00", "2.1"), ("300000.00", "2.2")]


def test_nothing_found_where_nothing_is_written(db, docs) -> None:  # type: ignore[no-untyped-def]
    got = found(db, docs["rules-d"])
    assert got["contract_end_date"] == []
    assert got["amount_without_vat"] == []
    assert got["amount_with_vat"] == [("1200000.00", "2.1")]


def test_spelled_legal_forms_and_a_rate_in_brackets(db, docs) -> None:  # type: ignore[no-untyped-def]
    # analyst's measurement, record 24: names 17/39 and amount with VAT 0/39 on such text
    got = found(db, docs["rules-e"])
    assert got["customer_name_short"] == [('ОАО "Гамма"', "преамбула")]
    assert got["contractor_name_short"] == [('АО "Дельта"', "преамбула")]
    assert got["amount_without_vat"] == [("1500000.00", "2.1")]
    assert got["amount_with_vat"] == [("1800000.00", "2.1")]  # the VAT amount is not taken


def test_an_underscore_for_the_dash_before_the_amount(db, docs) -> None:  # type: ignore[no-untyped-def]
    # analyst's measurement, record 26: «с НДС (20%) _ сумма» on a scan
    got = found(db, docs["rules-f"])
    assert got["amount_without_vat"] == [("700000.00", "2.1")]
    assert got["amount_with_vat"] == [("840000.00", "2.1")]


def test_every_result_has_a_located_quote(db, docs) -> None:  # type: ignore[no-untyped-def]
    for doc in docs.values():
        index, sections = _inputs(db, doc)
        for items in rules.extract_rules(index, sections).values():
            for r in items:
                assert r.quote_start is not None and r.quote_end is not None
                assert index.text[r.quote_start : r.quote_end] == r.quote
                assert r.pages


def test_nothing_outside_the_shown_part(db, docs) -> None:  # type: ignore[no-untyped-def]
    index, sections = _inputs(db, docs["rules-a"])
    cut = index.text.index("5. Срок действия")
    hidden = type(index)(index.text, cut, index.clauses, index.spans, index.text_sha256)
    assert rules.extract_rules(hidden, sections)["contract_end_date"] == []


def test_module_needs_no_database() -> None:
    source = Path(rules.__file__).read_text(encoding="utf-8")
    assert "psycopg" not in source and "openai" not in source
    assert rules.RULES_VERSION == "02.3"
