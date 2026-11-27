"""The rule-checks survey reads synthetic values and prints counts only (feature 06)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_rule_checks.py"
spec = importlib.util.spec_from_file_location("survey_rule_checks", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey  # @dataclass looks its module up there
spec.loader.exec_module(survey)


@pytest.mark.parametrize(
    ("words", "number"),
    [
        ("один миллион двести тысяч", 1_200_000),
        ("Четыре миллиона семьсот две тысячи четыреста", 4_702_400),
        ("Девятьсот тысяч", 900_000),
        ("Сто сорок тысяч", 140_000),
        ("тысяча", 1_000),
        ("Два миллиарда триста миллионов одиннадцать", 2_300_000_011),
        ("Триста тысяч рублей 00 копеек", 300_000),
        ("Семьсот тысяч рублей двадцать копеек", 700_000),
    ],
)
def test_words_to_int(words: str, number: int) -> None:
    assert survey.words_to_int(words) == number


def test_words_that_are_not_a_number() -> None:
    assert survey.words_to_int("без учёта НДС") is None
    assert survey.words_to_int("") is None


def test_amount_words_classes() -> None:
    assert survey.amount_words_class(
        "1 200 000 (один миллион двести тысяч) рублей", "", "1200000.00"
    ) == ("equal", False)
    assert survey.amount_words_class(
        "1 200 000", " (один миллион триста тысяч) рублей", "1200000.00"
    ) == ("differs", False)
    assert survey.amount_words_class("1 200 000 рублей", " без НДС", "1200000.00") == (
        "no_words", False
    )
    assert survey.amount_words_class(
        "700 000 (Семьсот тысяч рублей двадцать копеек)", "", "700000.20"
    ) == ("equal", True)
    assert survey.amount_words_class("5 000 (пять тысяч штук)", "", "5000.00")[0] == "unparsed"


def test_rates_and_vat_classes() -> None:
    assert survey.rates_in("увеличивается на НДС (20%) — 300 000") == [Decimal(20)]
    assert survey.rates_in("НДС 18 % и НДС 0,5%") == [Decimal(18), Decimal("0.5")]
    assert survey.vat_class(Decimal("1500000"), Decimal("1800000.00"), Decimal(20)) == "exact"
    assert survey.vat_class(Decimal("100.03"), Decimal("120.03"), Decimal(20)) == "kopeck"
    assert survey.vat_class(Decimal("1000"), Decimal("1200.50"), Decimal(20)) == "rouble"
    assert survey.vat_class(Decimal("1000"), Decimal("1180"), Decimal(20)) == "other"
    assert survey.ratio_bucket(Decimal("1000"), Decimal("1180")) == "1.18"
    assert survey.ratio_bucket(Decimal("1000"), Decimal("1000")) == "1.00"


def test_date_buckets() -> None:
    today = date(2026, 11, 27)
    assert survey.year_bucket("2027-09-30") == "2027"
    assert survey.year_bucket("2045-01-01") == "после 2040"
    assert survey.relative_bucket("2027-09-30", today) == "в будущем, до 5 лет"
    assert survey.relative_bucket("2020-01-01", today) == "раньше чем 5 лет назад"


def test_number_in_lines() -> None:
    number = "Р-15/2026 ДП"
    assert survey.number_match(["Договор № Р-15/2026 ДП", "стр. 2"], number) == "full"
    assert survey.number_match(["Договор №Р-15/2026"], number) == "core"
    assert survey.number_match(["Договор № Р-16/2026"], number) == "differs"
    assert survey.number_match(["стр. 2"], number) == "none"


def _doc(**rows: dict) -> object:
    fields = {name: {"result": "not_found"} for name in survey.FIELDS}
    fields.update(rows)
    return survey.Doc(fields, "", ["Договор № Р-15/2026"], ["Номер договора: Р-15/2026"])


def _found(value_text: str, normalized: str, quote: str = "") -> dict:
    return {"result": "found", "value_text": value_text, "value_normalized": normalized,
            "quote": quote, "value_end": None}


def test_summary_counts_and_prints_no_values() -> None:
    doc = _doc(
        contract_number=_found("Р-15/2026", "Р-15/2026"),
        customer_name_short=_found("АО «Гамма»", 'АО "Гамма"'),
        contractor_name_short=_found("акционерное общество «Гамма»",
                                     'акционерное общество "Гамма"'),
        amount_without_vat=_found("1 500 000 (Один миллион пятьсот тысяч) рублей",
                                  "1500000.00", "составляет 1 500 000 рублей без НДС"),
        amount_with_vat=_found("1 800 000 (Один миллион восемьсот тысяч) рублей",
                               "1800000.00", "всего с НДС (20%) 1 800 000 рублей"),
        contract_end_date=_found("30 сентября 2027 г.", "2027-09-30"),
    )
    result = survey.survey_documents([doc], date(2026, 11, 27))
    text = "\n".join(survey.summary_lines(result))
    assert "amount_with_vat: равна рублям 1 (100%)" in text
    assert "ставка в цитатах: 20% 1 (100%)" in text
    assert "точно 1 (100%)" in text and "1.20 1 (100%)" in text
    assert "Краткие наименования сторон: одинаковые 1 (100%)" in text
    assert "в колонтитулах: совпадает целиком 1 (100%)" in text
    assert "на листе подписи («Номер договора»): совпадает целиком 1 (100%)" in text
    for secret in ("Гамма", "1 500 000", "Р-15/2026", "сентября", "миллион"):
        assert secret not in text
