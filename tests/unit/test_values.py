"""Normalizing values and finding a value inside its quote (feature 05, research R-6, R-7).

Task T009. Critical rules (CLAUDE.md «Model routing»): the program, not the model,
normalizes a value and decides whether the quote holds it.
"""

from __future__ import annotations

import pytest

from docreader.fields import Kind
from docreader.values import (
    ValueNotNormalized,
    contract_number_core,
    find_in_quote,
    normalize,
    short_name_after,
    spelled_legal_form,
)

# --- amounts -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("64 270 348 (шестьдесят четыре миллиона двести семьдесят тысяч триста сорок восемь) "
         "рублей 83 копейки", "64270348.83"),
        ("1 200 000 рублей", "1200000.00"),
        ("1 200 000 (один миллион двести тысяч) рублей 00 копеек", "1200000.00"),
        ("64 270 348,83 руб.", "64270348.83"),
        ("64 270 348.83 руб", "64270348.83"),
        ("64270348.83", "64270348.83"),
        ("64 270 348,83", "64270348.83"),
        ("1 200 000", "1200000.00"),
        ("38 064 418 рублей 61 копейка", "38064418.61"),
        ("77 124 418 руб. 60 коп.", "77124418.60"),
        ("500 рубля", "500.00"),
        ("1 рубль", "1.00"),
        ("  1 440 000 рублей  ", "1440000.00"),
    ],
)
def test_amount_normalized(written: str, expected: str) -> None:
    assert normalize(Kind.AMOUNT, written) == expected


@pytest.mark.parametrize(
    "written",
    [
        "двести рублей", "", "рублей", "1 2345 рублей", "12,345 рублей",
        "64 270 348 рублей 830 копеек",
    ],
)
def test_amount_not_normalized(written: str) -> None:
    with pytest.raises(ValueNotNormalized) as exc:
        normalize(Kind.AMOUNT, written)
    assert str(exc.value) == "значение не приводится к сумме"


def test_amount_found_among_several_sums() -> None:
    quote = ("Цена договора составляет 1 200 000 (один миллион двести тысяч) рублей 00 копеек "
             "без НДС, НДС 20% — 240 000 рублей, всего с НДС 1 440 000 рублей 00 копеек.")
    span = find_in_quote(Kind.AMOUNT, "1440000.00", quote)
    assert span is not None
    assert quote[span[0]:span[1]] == "1 440 000 рублей 00 копеек"
    span = find_in_quote(Kind.AMOUNT, "1200000.00", quote)
    assert span is not None
    assert quote[span[0]:span[1]] == "1 200 000 (один миллион двести тысяч) рублей 00 копеек"


def test_amount_with_comma_kopecks_found() -> None:
    quote = "Цена договора без НДС — 1 200 000,50 руб., с НДС — 1 440 000,60 руб."
    span = find_in_quote(Kind.AMOUNT, "1440000.60", quote)
    assert span is not None and quote[span[0]:span[1]] == "1 440 000,60 руб"


def test_number_without_roubles_is_not_an_amount() -> None:
    assert find_in_quote(Kind.AMOUNT, "2026.00", "Договор действует по 25 марта 2026 г.") is None
    assert find_in_quote(Kind.AMOUNT, "20.00", "НДС 20% начисляется") is None


def test_different_amount_not_found() -> None:
    assert find_in_quote(Kind.AMOUNT, "1440000.00", "Цена 1 200 000 рублей без НДС.") is None


def test_amount_across_a_line_break() -> None:
    quote = "всего с\nНДС 1 440 000 (один миллион четыреста\nсорок тысяч) рублей 00 копеек."
    assert find_in_quote(Kind.AMOUNT, "1440000.00", quote) is not None


# --- dates -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written",
    [
        "25 марта 2026 г.",
        '"25" Марта 2026 года',
        "«25» марта 2026 г.",
        "25 МАРТА 2026",
        "25.03.2026",
        "2026-03-25",
        "по 25 марта 2026 г.",
    ],
)
def test_date_normalized(written: str) -> None:
    assert normalize(Kind.DATE, written) == "2026-03-25"


def test_single_digit_day() -> None:
    assert normalize(Kind.DATE, "1 марта 2026 г.") == "2026-03-01"


@pytest.mark.parametrize(
    "written", ["31.02.2026", "до полного исполнения обязательств", "марта 2026", "", "2026"]
)
def test_date_not_normalized(written: str) -> None:
    with pytest.raises(ValueNotNormalized) as exc:
        normalize(Kind.DATE, written)
    assert str(exc.value) == "значение не приводится к дате"


def test_date_found_among_two_dates() -> None:
    quote = "Работы выполняются до 31 декабря 2026 г., договор действует по 25 марта 2027 г."
    span = find_in_quote(Kind.DATE, "2027-03-25", quote)
    assert span is not None and quote[span[0]:span[1]] == "25 марта 2027"


def test_numeric_date_found() -> None:
    quote = "Договор действует до 25.03.2027"
    span = find_in_quote(Kind.DATE, "2027-03-25", quote)
    assert span is not None and quote[span[0]:span[1]] == "25.03.2027"


def test_other_date_not_found() -> None:
    assert find_in_quote(Kind.DATE, "2027-03-25", "по 26 марта 2027 г.") is None


# --- identifiers -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("№ ДП-17/2026", "ДП-17/2026"),
        ("№ДП-17/2026", "ДП-17/2026"),
        ("N ДП‐17/2026", "ДП-17/2026"),  # hyphen U+2010
        ("ДП–17/2026", "ДП-17/2026"),  # en dash
        ("  ДП-17/2026  ", "ДП-17/2026"),
        ("08.0308-1369/ОКЭ ДИ", "08.0308-1369/ОКЭ ДИ"),  # an inner space is kept
        ("634/OKЭ-ЦДИ/24/6/1", "634/ОКЭ-ЦДИ/24/6/1"),  # Latin O, K inside a Cyrillic word
        ("№ 123/ABC", "123/ABC"),  # a Latin word stays Latin
        ("Nº ДП-17/2026", "ДП-17/2026"),  # N + masculine ordinal U+00BA, as in some titles
        ("N° ДП-17/2026", "ДП-17/2026"),  # N + degree sign
        ("Nº12/3", "12/3"),
    ],
)
def test_identifier_normalized(written: str, expected: str) -> None:
    assert normalize(Kind.IDENTIFIER, written) == expected


# --- the contract number without a letter suffix (analyst's rule, 2026-11-26) -------------


@pytest.mark.parametrize(
    ("normalized", "expected"),
    [
        ("ДП-17/2026 АБ-ВГД", "ДП-17/2026"),  # a letter code after a space is not the number
        ("ДП-17/2026 АБ ВГ", "ДП-17/2026"),  # several letter words
        ("08.0308-1369/ОКЭ ДИ", "08.0308-1369/ОКЭ"),
        ("ДП-17/2026", "ДП-17/2026"),
        ("12 / 34", "12 / 34"),  # a part with digits after the space stays
        ("ДП 17", "ДП 17"),
        ("АБВ", "АБВ"),  # a number of letters only is not cut to nothing
    ],
)
def test_contract_number_core(normalized: str, expected: str) -> None:
    assert contract_number_core(normalized) == expected


@pytest.mark.parametrize("written", ["", "№", "  №  "])
def test_identifier_not_normalized(written: str) -> None:
    with pytest.raises(ValueNotNormalized) as exc:
        normalize(Kind.IDENTIFIER, written)
    assert str(exc.value) == "значение не приводится к номеру"


def test_identifier_found_across_the_title_break() -> None:
    quote = "ДОГОВОР ПОДРЯДА\n№ ДП-17/2026"
    span = find_in_quote(Kind.IDENTIFIER, "ДП-17/2026", quote)
    assert span is not None and quote[span[0]:span[1]] == "ДП-17/2026"


def test_identifier_part_of_a_longer_number_not_found() -> None:
    assert find_in_quote(Kind.IDENTIFIER, "ДП-17/2026", "№ ДП-17/20261") is None
    assert find_in_quote(Kind.IDENTIFIER, "17/2026", "№ ДП-17/2026") is None


def test_other_identifier_not_found() -> None:
    assert find_in_quote(Kind.IDENTIFIER, "ДП-17/2026", "протокол № 722") is None


# --- names -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("ООО «Бёта–Строй»", 'ООО "Бета-Строй"'),
        ("ООО «Альфа»", 'ООО "Альфа"'),
        ('  ООО  "Альфа" ', 'ООО "Альфа"'),
        ("ОАО «РЖД»", 'ОАО "РЖД"'),
    ],
)
def test_name_normalized_keeping_case(written: str, expected: str) -> None:
    assert normalize(Kind.NAME, written) == expected


@pytest.mark.parametrize("written", ["", "  ", "«»"])
def test_name_not_normalized(written: str) -> None:
    with pytest.raises(ValueNotNormalized) as exc:
        normalize(Kind.NAME, written)
    assert str(exc.value) == "значение не приводится к наименованию"


def test_name_found_in_brackets() -> None:
    quote = "Общество с ограниченной ответственностью «Альфа» (ООО «Альфа»), именуемое"
    span = find_in_quote(Kind.NAME, 'ООО "Альфа"', quote)
    assert span is not None and quote[span[0]:span[1]] == "ООО «Альфа»"


def test_name_found_in_another_case() -> None:
    quote = "договор заключён с ООО «Альфы» сроком на год"
    span = find_in_quote(Kind.NAME, 'ООО "Альфа"', quote)
    assert span is not None and quote[span[0]:span[1]] == "ООО «Альфы»"


def test_name_found_with_yo_and_dash() -> None:
    quote = "и ООО «Бёта–Строй», именуемое в дальнейшем Подрядчик"
    span = find_in_quote(Kind.NAME, 'ООО "Бета-Строй"', quote)
    assert span is not None and quote[span[0]:span[1]] == "ООО «Бёта–Строй»"


def test_name_words_out_of_order_not_found() -> None:
    assert find_in_quote(Kind.NAME, 'ООО "Альфа"', "«Альфа» ООО") is None


def test_other_name_not_found() -> None:
    assert find_in_quote(Kind.NAME, 'ООО "Бета"', "ООО «Альфа», именуемое Заказчиком") is None


def test_name_words_must_be_adjacent() -> None:
    assert find_in_quote(Kind.NAME, 'ООО "Бета"', "ООО «Альфа» и «Бета»") is None


def test_latin_name_compared_without_case() -> None:
    quote = "и ООО «Alpha Systems», именуемое Подрядчиком"
    span = find_in_quote(Kind.NAME, 'ООО "ALPHA SYSTEMS"', quote)
    assert span is not None and quote[span[0]:span[1]] == "ООО «Alpha Systems»"


def test_name_with_case_difference() -> None:
    assert find_in_quote(Kind.NAME, 'ооо "альфа"', "с ООО «Альфа»") is not None


# --- a full name given for the short one (analyst's finding, 2026-11-26) -------------------


@pytest.mark.parametrize(
    "name",
    [
        "Открытое акционерное общество «Альфа Дельта Строй»",
        "акционерное общество «Бета»",
        "Общество с ограниченной ответственностью «Гамма»",
        "Публичное акционерное общество «Дельта»",
        "Федеральное государственное унитарное предприятие «Эпсилон»",
    ],
)
def test_spelled_legal_form_is_detected(name: str) -> None:
    assert spelled_legal_form(normalize(Kind.NAME, name))


@pytest.mark.parametrize(
    "name", ["ООО «Альфа»", "ОАО «АДС»", "АО «Бета»", "Филиал ООО «Альфа»", "«Акционер»"]
)
def test_short_name_is_not_spelled(name: str) -> None:
    assert not spelled_legal_form(normalize(Kind.NAME, name))


@pytest.mark.parametrize(
    ("quote", "short"),
    [
        ("Открытое акционерное общество «Альфа Дельта Строй» (ОАО «АДС»), именуемое",
         "ОАО «АДС»"),
        ("и Акционерное общество «Бета» (АО «Бета»), именуемое в дальнейшем Подрядчик",
         "АО «Бета»"),
        ("Акционерное общество «Бета» (далее — АО «Бета»), именуемое", "АО «Бета»"),
        ('Акционерное общество "Бета" (сокращённо: АО "Бета")', 'АО "Бета"'),
        ("Общество с ограниченной ответственностью «Гамма «Юг»» (ООО «Гамма «Юг»»)",
         "ООО «Гамма «Юг»»"),
    ],
)
def test_short_name_found_in_brackets_after_the_full_one(quote: str, short: str) -> None:
    found = short_name_after(quote, quote.index(" ("))  # the full name ends before « («
    assert found is not None
    start, end = found
    assert quote[start:end] == short


@pytest.mark.parametrize(
    "quote",
    [
        "Акционерное общество «Бета», именуемое в дальнейшем Подрядчик",  # no brackets
        "Акционерное общество «Бета» (Подрядчик), в лице директора",  # brackets without a form
        "Акционерное общество «Бета», именуемое Подрядчик (ООО «Гамма» — Поручитель)",
    ],
)
def test_no_short_name_in_brackets(quote: str) -> None:
    end = quote.index("»") + 1
    assert short_name_after(quote, end) is None
