"""Normalizing values and finding a value inside its quote (feature 05, research R-6, R-7).

Task T009. Critical rules (CLAUDE.md «Model routing»): the program, not the model,
normalizes a value and decides whether the quote holds it.
"""

from __future__ import annotations

import pytest

from docreader import catalog
from docreader.fields import Kind
from docreader.values import (
    ValueNotNormalized,
    canonical_short_name,
    contract_number_core,
    find_in_quote,
    normalize,
    same_value,
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


def test_amount_with_a_missing_space_in_the_first_group() -> None:
    # the contract text lost the space after the millions (analyst's measurement, record 15,
    # 2026-11-26): the whole number, not its last group
    quote = ("и составляет всего с НДС (20%) — 4560 789 (Четыре миллиона пятьсот шестьдесят "
             "тысяч семьсот восемьдесят девять) рублей 20 копеек.")
    span = find_in_quote(Kind.AMOUNT, "4560789.20", quote)
    assert span is not None
    assert quote[span[0]:span[1]].startswith("4560 789 (")
    assert find_in_quote(Kind.AMOUNT, "789.20", quote) is None
    assert normalize(Kind.AMOUNT, "4560 789 рублей 20 копеек") == "4560789.20"


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


# A zero among letters is the letter О: the contract text has «0БВ» for «ОБВ» (analyst's
# measurement, record 19, 2026-11-27). Only a group of letters and zeros with a Cyrillic
# letter in it; the text keeps the zero, the normalized value gets the letter.
@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("12/0БВ-ГД/3", "12/ОБВ-ГД/3"),
        ("12/ОБВ-ГД/3", "12/ОБВ-ГД/3"),
        ("12/Б0В-ГД/3", "12/БОВ-ГД/3"),
        ("12/10БВ-ГД/3", "12/10БВ-ГД/3"),  # a digit other than zero: a number, not a letter
        ("12/0-БВ/3", "12/0-БВ/3"),  # a zero on its own
        ("120/34", "120/34"),
        ("12/0AB-3", "12/0AB-3"),  # Latin letters only
    ],
)
def test_zero_among_letters_is_the_letter(written: str, expected: str) -> None:
    assert normalize(Kind.IDENTIFIER, written) == expected


def test_identifier_with_a_zero_for_the_letter_found_in_the_quote() -> None:
    quote = "Договор № 12/0БВ-ГД/3 на выполнение работ"
    for value in ("12/0БВ-ГД/3", "12/ОБВ-ГД/3"):
        span = find_in_quote(Kind.IDENTIFIER, normalize(Kind.IDENTIFIER, value), quote)
        assert span is not None and quote[span[0]:span[1]] == "12/0БВ-ГД/3"


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


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ('акционерное общество "Бета"', 'АО "Бета"'),
        ('Открытое акционерное общество "Альфа Дельта Строй"', 'ОАО "Альфа Дельта Строй"'),
        ('Общество с ограниченной ответственностью "Гамма"', 'ООО "Гамма"'),
        ('Публичное акционерное общество "Дельта"', 'ПАО "Дельта"'),
        ('Федеральное государственное унитарное предприятие "Эпсилон"', 'ФГУП "Эпсилон"'),
        ('АО "Бета"', 'АО "Бета"'),
        ('ОАО " АДС "', 'ОАО "АДС"'),  # spaces inside the quotes, as recognised scans give
        ('Филиал АО "Бета"', 'Филиал АО "Бета"'),  # a form inside the name is not touched
    ],
)
def test_canonical_short_name(name: str, expected: str) -> None:
    assert canonical_short_name(name) == expected


def _field(name: str) -> catalog.CatalogField:
    return next(f for f in catalog.CATALOG if f.name == name)


def test_short_names_equal_with_the_form_written_out_or_abbreviated() -> None:
    field = _field("contractor_name_short")
    a = normalize(Kind.NAME, "акционерное общество «Бета»")
    b = normalize(Kind.NAME, "АО «Бета»")
    assert same_value(field, a, b)
    assert not same_value(field, a, normalize(Kind.NAME, "ООО «Бета»"))


# The name in quotes abbreviated to the initials of its words is the same organization when
# the legal form is the same (analyst, 2026-11-26, record 10 of the gold set: the model gave
# the full name, the gold set the abbreviation, six contracts). Comparison only.
@pytest.mark.parametrize(
    ("short", "full"),
    [
        ("ОАО «АДС»", "Открытое акционерное общество «Альфа Дельта Строй»"),
        ("ОАО «АДС»", "ОАО «Альфа Дельта Строй»"),
        ("ОАО «АДС»", "открытое акционерное общество «альфа дельта строй»"),
        ("ООО «СЗГ»", "Общество с ограниченной ответственностью «Северо-Западная Гамма»"),
        ("ООО «СЗГ»", "ООО «Северо Западная Гамма»"),
    ],
)
def test_short_names_equal_when_quotes_hold_the_initials(short: str, full: str) -> None:
    field = _field("customer_name_short")
    a, b = normalize(Kind.NAME, short), normalize(Kind.NAME, full)
    assert same_value(field, a, b)
    assert same_value(field, b, a)


@pytest.mark.parametrize(
    ("short", "full"),
    [
        ("АО «АДС»", "Открытое акционерное общество «Альфа Дельта Строй»"),  # other form
        ("ОАО «АДК»", "Открытое акционерное общество «Альфа Дельта Строй»"),  # other letters
        ("ОАО «АД»", "Открытое акционерное общество «Альфа Дельта Строй»"),  # a word short
        ("ОАО «Альфа»", "Открытое акционерное общество «Альфа Дельта Строй»"),  # not initials
        ("«АДС»", "«Альфа Дельта Строй»"),  # no legal form on either side
        ("ОАО «А»", "ОАО «Альфа»"),  # one word: too weak to tell organizations apart
    ],
)
def test_short_names_differ_when_the_initials_do_not_match(short: str, full: str) -> None:
    field = _field("customer_name_short")
    assert not same_value(field, normalize(Kind.NAME, short), normalize(Kind.NAME, full))


def test_initials_rule_is_only_for_short_names() -> None:
    field = _field("customer_name_full")
    assert not same_value(field, normalize(Kind.NAME, "ОАО «АДС»"),
                          normalize(Kind.NAME, "ОАО «Альфа Дельта Строй»"))


def test_full_names_keep_their_form_when_compared() -> None:
    field = _field("customer_name_full")
    assert not same_value(field, normalize(Kind.NAME, "акционерное общество «Бета»"),
                          normalize(Kind.NAME, "АО «Бета»"))
