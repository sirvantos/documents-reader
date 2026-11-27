"""Normalizing values of every catalog kind (feature 02, T006, research R-4).

`values.normalize_field` is the one normalization for the gold set, the review page,
the blind control and the comparison; the four kinds of feature 05 keep exactly the
behaviour of `values.normalize` (FR-011).
"""

from __future__ import annotations

import pytest

from docreader import catalog, values
from docreader.fields import Kind


def f(name: str) -> catalog.CatalogField:
    return catalog.field(name)


# --- requisites ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("customer_inn", "7708 503 727", "7708503727"),
        ("customer_inn", " 7708503727 ", "7708503727"),
        ("contractor_inn", "ИНН 6163218533", "6163218533"),
    ],
)
def test_requisite_keeps_digits(name: str, value: str, expected: str) -> None:
    assert values.normalize_field(f(name), value) == expected


def test_requisite_wrong_length() -> None:
    with pytest.raises(ValueError, match=r"значение не приводится к ИНН \(10 цифр\)"):
        values.normalize_field(f("customer_inn"), "770850372")


def test_requisite_letters() -> None:
    with pytest.raises(ValueError, match="ИНН"):
        values.normalize_field(f("customer_inn"), "77085O3727")


def test_requisite_lengths_of_other_kinds() -> None:
    kpp = next(x for x in catalog.CATALOG if x.requisite_length == 9)
    assert values.normalize_field(kpp, "997 650 001") == "997650001"
    with pytest.raises(ValueError, match=r"\(9 цифр\)"):
        values.normalize_field(kpp, "99765000")


# --- percent and number -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("0,1%", "0.1"), ("20 %", "20"), ("20", "20"), ("2,50", "2.5"), ("0.1 %", "0.1")],
)
def test_percent(value: str, expected: str) -> None:
    assert values.normalize_field(f("vat_rate"), value) == expected


@pytest.mark.parametrize("value", ["две", "", "20%%", "1,2,3"])
def test_percent_errors(value: str) -> None:
    with pytest.raises(ValueError, match="значение не приводится к проценту"):
        values.normalize_field(f("vat_rate"), value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("60 (шестьдесят) месяцев", "60"), ("7", "7"), (" 30 дней", "30")],
)
def test_number(value: str, expected: str) -> None:
    assert values.normalize_field(f("payment_days"), value) == expected


@pytest.mark.parametrize("value", ["7,5", "семь", ""])
def test_number_errors(value: str) -> None:
    with pytest.raises(ValueError, match="значение не приводится к целому числу"):
        values.normalize_field(f("payment_days"), value)


# --- choice ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value", "expected"),
    [
        ("contract_type", "смр", "СМР"),
        ("contract_type", " ПИР ", "ПИР"),
        ("price_type", "твердая", "твёрдая"),
        ("price_type", "ТВЁРДАЯ", "твёрдая"),
        ("currency", "rub", "RUB"),
    ],
)
def test_choice_returns_the_catalog_variant(name: str, value: str, expected: str) -> None:
    assert values.normalize_field(f(name), value) == expected


def test_choice_unknown_lists_variants() -> None:
    with pytest.raises(ValueError, match="значение не из вариантов: СМР, ПИР, иное"):
        values.normalize_field(f("contract_type"), "ремонт")


# --- free text, list, records -------------------------------------------------------------


@pytest.mark.parametrize("name", ["payment_terms", "appendices", "price_by_year"])
def test_manual_kinds_are_kept(name: str) -> None:
    assert values.normalize_field(f(name), "  как есть  ") == "как есть"


# --- the four kinds of feature 05 are unchanged --------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind", "value"),
    [
        ("contract_number", Kind.IDENTIFIER, "№ ДП-17/2026"),
        ("customer_name_short", Kind.NAME, "ООО «Альфа»"),
        ("amount_without_vat", Kind.AMOUNT, "1 200 000 рублей 00 копеек"),
        ("amount_with_vat", Kind.AMOUNT, "1440000,00"),
        ("contract_end_date", Kind.DATE, "25 марта 2027 г."),
        ("contract_end_date", Kind.DATE, "25.03.2027"),
        ("signing_date", Kind.DATE, "2026-01-15"),
    ],
)
def test_extraction_kinds_equal_normalize(name: str, kind: Kind, value: str) -> None:
    assert values.normalize_field(f(name), value) == values.normalize(kind, value)


def test_extraction_kind_errors_keep_their_message() -> None:
    with pytest.raises(ValueError, match="значение не приводится к дате"):
        values.normalize_field(f("contract_end_date"), "скоро")
    with pytest.raises(ValueError, match="значение не приводится к сумме"):
        values.normalize_field(f("amount_with_vat"), "много")


def test_gold_amount_written_without_currency_word() -> None:
    # the analyst writes «1 000 000,00» or «1000000» in the template
    assert values.normalize_field(f("amount_with_vat"), "1 000 000,00") == "1000000.00"
    assert values.normalize_field(f("amount_with_vat"), "1000000") == "1000000.00"


# --- same_value ---------------------------------------------------------------------------


def test_same_value_names_ignore_case() -> None:
    assert values.same_value(f("customer_name_short"), 'ООО "Альфа"', 'ооо "альфа"')
    assert not values.same_value(f("customer_name_short"), 'ООО "Альфа"', 'ООО "Бета"')


def test_same_value_other_kinds_by_equality() -> None:
    assert values.same_value(f("amount_with_vat"), "1000.00", "1000.00")
    assert not values.same_value(f("amount_with_vat"), "1000.00", "1000.01")
    assert not values.same_value(f("contract_number"), "А-1", "а-1")
