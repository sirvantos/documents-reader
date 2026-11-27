"""The rules of feature 06 on values built in the test, no database (T008, T010).

Interface (research R-2): `checks.DocFields(rows, text)` — the six `FieldRow`s of a
contract (`result`, `value_text`, `value_normalized`, `quote`, `after`: the text right
after the value) and its clean text; `checks.apply(code, doc, settings)` runs one rule of
`checks.RULES` and returns `{field: RuleCheck(outcome, reason)}` for each field of the rule;
`checks.RULES` holds every rule once, in order.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from docreader.checks import RULES, DocFields, FieldRow, RuleCheck, RuleOutcome, apply
from docreader.config import CheckSettings

PASSED, VIOLATED, NOT_APPLIED = RuleOutcome.PASSED, RuleOutcome.VIOLATED, RuleOutcome.NOT_APPLIED
SETTINGS = CheckSettings()


def found(value_text: str, normalized: str, quote: str = "", after: str = "") -> FieldRow:
    return FieldRow("found", value_text, normalized, quote or value_text, after)


NOT_FOUND = FieldRow("not_found", None, None, None, "")

CLEAN = {
    "contract_number": found("№ Р-1/2026", "Р-1/2026"),
    "customer_name_short": found("ООО «Альфа»", 'ООО "Альфа"'),
    "contractor_name_short": found("ООО «Бета»", 'ООО "Бета"'),
    "amount_without_vat": found(
        "1 000 000 (один миллион) рублей 00 копеек", "1000000.00",
        "Цена составляет 1 000 000 (один миллион) рублей 00 копеек без учёта НДС, НДС (20%)",
    ),
    "amount_with_vat": found(
        "1 200 000 (один миллион двести тысяч) рублей 00 копеек", "1200000.00",
        "всего с учётом НДС 1 200 000 (один миллион двести тысяч) рублей 00 копеек",
    ),
    "contract_end_date": found("«31» декабря 2027 г.", "2027-12-31"),
}


def doc(text: str = "", **rows: FieldRow) -> DocFields:
    return DocFields({**CLEAN, **rows}, text)


def check(code: str, d: DocFields, settings: CheckSettings = SETTINGS) -> dict[str, RuleCheck]:
    return apply(code, d, settings)


def test_registry_has_each_rule_once() -> None:
    codes = [r.code for r in RULES]
    assert len(codes) == len(set(codes))
    assert {"amount_positive", "amount_words", "vat_consistent", "end_date_range",
            "parties_differ", "required", "kind_valid"} <= set(codes)


def test_clean_contract_passes_every_rule() -> None:
    for rule in RULES:
        for field, result in apply(rule.code, doc(), SETTINGS).items():
            assert result.outcome is PASSED, (rule.code, field, result)
            assert result.reason is None


# --- amount_positive -----------------------------------------------------------------------


def test_amount_not_above_zero_is_violated() -> None:
    got = check("amount_positive", doc(amount_without_vat=found("0 рублей", "0.00")))
    assert got["amount_without_vat"] == RuleCheck(VIOLATED, "not_positive")
    assert got["amount_with_vat"].outcome is PASSED


def test_amount_positive_not_applied_without_a_value() -> None:
    got = check("amount_positive", doc(amount_with_vat=NOT_FOUND))
    assert got["amount_with_vat"] == RuleCheck(NOT_APPLIED, "no_value")


# --- parties_differ -----------------------------------------------------------------------


def test_same_parties_are_violated_on_both() -> None:
    got = check("parties_differ", doc(contractor_name_short=found("ООО «Альфа»", 'ООО "Альфа"')))
    assert got == {
        "customer_name_short": RuleCheck(VIOLATED, "same_parties"),
        "contractor_name_short": RuleCheck(VIOLATED, "same_parties"),
    }


def test_same_party_by_the_feature_02_name_rule() -> None:
    # a spelled-out legal form is the same party as its abbreviation (values.same_value)
    spelled = found("общество с ограниченной ответственностью «Альфа»",
                    'общество с ограниченной ответственностью "Альфа"')
    got = check("parties_differ", doc(contractor_name_short=spelled))
    assert got["contractor_name_short"].outcome is VIOLATED


def test_parties_differ_not_applied_with_one_party() -> None:
    got = check("parties_differ", doc(contractor_name_short=NOT_FOUND))
    assert got["customer_name_short"] == RuleCheck(NOT_APPLIED, "one_party")
    assert got["contractor_name_short"] == RuleCheck(NOT_APPLIED, "one_party")


# --- required --------------------------------------------------------------------------------


def test_required_fields_are_the_five() -> None:
    got = check("required", doc())
    assert set(got) == {"contract_number", "customer_name_short", "contractor_name_short",
                        "amount_without_vat", "amount_with_vat"}


@pytest.mark.parametrize("field", ["contract_number", "customer_name_short", "amount_with_vat"])
def test_required_field_not_found_is_violated(field: str) -> None:
    got = check("required", doc(**{field: NOT_FOUND}))
    assert got[field] == RuleCheck(VIOLATED, "required_missing")


def test_required_ignores_rejected_and_failed() -> None:
    # their status comes from the extraction (research R-6), not from this rule
    rejected = replace(NOT_FOUND, result="rejected")
    got = check("required", doc(amount_with_vat=rejected))
    assert got["amount_with_vat"].outcome is PASSED


# --- kind_valid ------------------------------------------------------------------------------


def test_value_that_does_not_fit_its_kind_is_violated() -> None:
    got = check("kind_valid", doc(contract_end_date=found("тридцатое", "2027-13-45")))
    assert got["contract_end_date"] == RuleCheck(VIOLATED, "kind_invalid")
    assert got["amount_with_vat"].outcome is PASSED


def test_kind_valid_not_applied_without_a_value() -> None:
    got = check("kind_valid", doc(contract_end_date=NOT_FOUND))
    assert got["contract_end_date"] == RuleCheck(NOT_APPLIED, "no_value")
    assert len(got) == 6


# --- end_date_range --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "outcome"),
    [
        ("2027-12-31", PASSED),
        ("2015-01-01", PASSED),  # bounds are inclusive
        ("2040-12-31", PASSED),
        ("2020-06-30", PASSED),  # in the past is not a violation
        ("2014-12-31", VIOLATED),
        ("2045-12-31", VIOLATED),
    ],
)
def test_end_date_range(value: str, outcome: RuleOutcome) -> None:
    got = check("end_date_range", doc(contract_end_date=found("дата", value)))
    assert got["contract_end_date"].outcome is outcome
    if outcome is VIOLATED:
        assert got["contract_end_date"].reason == "date_out_of_range"


def test_end_date_bounds_come_from_the_settings() -> None:
    narrow = CheckSettings(end_date_min="2028-01-01", end_date_max="2030-12-31")
    got = check("end_date_range", doc(), narrow)
    assert got["contract_end_date"] == RuleCheck(VIOLATED, "date_out_of_range")


def test_end_date_range_not_applied_without_a_date() -> None:
    got = check("end_date_range", doc(contract_end_date=NOT_FOUND))
    assert got["contract_end_date"] == RuleCheck(NOT_APPLIED, "no_value")


# --- amount_words (T010, research R-3) ------------------------------------------------------


def test_words_equal_to_the_roubles_pass() -> None:
    got = check("amount_words", doc())
    assert got == {"amount_without_vat": RuleCheck(PASSED, None),
                   "amount_with_vat": RuleCheck(PASSED, None)}


def test_words_that_differ_are_violated() -> None:
    wrong = found("1 000 000 (один миллион сто тысяч) рублей 00 копеек", "1000000.00")
    got = check("amount_words", doc(amount_without_vat=wrong))
    assert got["amount_without_vat"] == RuleCheck(VIOLATED, "words_differ")
    assert got["amount_with_vat"].outcome is PASSED


def test_words_right_after_the_value_are_read() -> None:
    row = found("1 000 000", "1000000.00", after=" (один миллион сто тысяч) рублей")
    assert check("amount_words", doc(amount_without_vat=row))["amount_without_vat"] == (
        RuleCheck(VIOLATED, "words_differ")
    )


def test_words_with_kopecks_and_abbreviations_compare_the_roubles() -> None:
    kopecks = found("1 000 000,20 (один миллион рублей двадцать копеек)", "1000000.20")
    short = found("1 200 000 (один миллион двести тысяч руб. 00 коп.)", "1200000.00")
    got = check("amount_words", doc(amount_without_vat=kopecks, amount_with_vat=short))
    assert got["amount_without_vat"].outcome is PASSED
    assert got["amount_with_vat"].outcome is PASSED


def test_words_of_another_amount_are_not_taken() -> None:
    # the bracket after «НДС (20%) — 200 000» belongs to the VAT amount, not to this one
    after = " без учёта НДС, НДС (20%) — 200 000 (двести тысяч)"
    row = found("1 000 000 рублей", "1000000.00", after=after)
    assert check("amount_words", doc(amount_without_vat=row))["amount_without_vat"] == (
        RuleCheck(NOT_APPLIED, "no_words")
    )


def test_unreadable_words_are_violated() -> None:
    row = found("1 000 000 (один мильон) рублей", "1000000.00")
    assert check("amount_words", doc(amount_without_vat=row))["amount_without_vat"] == (
        RuleCheck(VIOLATED, "words_unreadable")
    )


def test_amount_words_not_applied_without_a_value() -> None:
    got = check("amount_words", doc(amount_with_vat=NOT_FOUND))
    assert got["amount_with_vat"] == RuleCheck(NOT_APPLIED, "no_value")


# --- vat_consistent (T010, research R-4) ----------------------------------------------------


def test_vat_consistent_to_the_kopeck() -> None:
    assert check("vat_consistent", doc()) == {
        "amount_without_vat": RuleCheck(PASSED, None),
        "amount_with_vat": RuleCheck(PASSED, None),
    }


def test_vat_mismatch_is_violated_on_both() -> None:
    got = check("vat_consistent", doc(amount_with_vat=found("1 250 000", "1250000.00")))
    assert got == {
        "amount_without_vat": RuleCheck(VIOLATED, "vat_mismatch"),
        "amount_with_vat": RuleCheck(VIOLATED, "vat_mismatch"),
    }


def test_one_kopeck_off_is_a_mismatch() -> None:
    got = check("vat_consistent", doc(amount_with_vat=found("1 200 000,01", "1200000.01")))
    assert got["amount_with_vat"] == RuleCheck(VIOLATED, "vat_mismatch")


def test_rounding_half_up_to_the_kopeck() -> None:
    # 100.03 × 1.2 = 120.036 → 120.04
    rows = {"amount_without_vat": found("100,03", "100.03", "100,03 без НДС, НДС (20%)"),
            "amount_with_vat": found("120,04", "120.04")}
    assert check("vat_consistent", doc(**rows))["amount_with_vat"].outcome is PASSED


def test_the_rate_written_in_the_quotes_is_used() -> None:
    rows = {
        "amount_without_vat": found("1 000 000", "1000000.00", "1 000 000 без НДС, НДС (10%)"),
        "amount_with_vat": found("1 100 000", "1100000.00", "всего с НДС 1 100 000"),
    }
    assert check("vat_consistent", doc(**rows))["amount_with_vat"].outcome is PASSED


def test_the_default_rate_comes_from_the_settings() -> None:
    rows = {
        "amount_without_vat": found("1 000 000", "1000000.00", "1 000 000 без НДС"),
        "amount_with_vat": found("1 180 000", "1180000.00", "всего 1 180 000"),
    }
    assert check("vat_consistent", doc(**rows))["amount_with_vat"].outcome is VIOLATED
    eighteen = CheckSettings(vat_rate=18.0)
    assert check("vat_consistent", doc(**rows), eighteen)["amount_with_vat"].outcome is PASSED


def test_one_amount_and_exempt_are_not_applied() -> None:
    got = check("vat_consistent", doc(amount_with_vat=NOT_FOUND))
    assert got["amount_without_vat"] == RuleCheck(NOT_APPLIED, "one_amount")
    exempt = doc("Цена составляет 900 000 рублей, НДС не облагается.", amount_with_vat=NOT_FOUND)
    got = check("vat_consistent", exempt)
    assert got == {"amount_without_vat": RuleCheck(NOT_APPLIED, "exempt"),
                   "amount_with_vat": RuleCheck(NOT_APPLIED, "exempt")}
