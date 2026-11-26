"""Outcomes of pairs «document, field» and their totals (feature 02, T008, research R-7)."""

from __future__ import annotations

import pytest

from docreader import catalog
from docreader.gold import GoldState
from docreader.outcomes import (
    CaseOutcome,
    FieldCase,
    GoldValue,
    Outcome,
    SystemValue,
    field_outcome,
    totals,
)

NUMBER = catalog.field("contract_number")
NAME = catalog.field("customer_name_short")
AMOUNT = catalog.field("amount_with_vat")
FREE = catalog.field("payment_terms")
RECORDS = catalog.field("price_by_year")


def gold(*normalized: str) -> GoldValue:
    return GoldValue(GoldState.VALUE, tuple(normalized))


ABSENT = GoldValue(GoldState.ABSENT, ())


def found(normalized: str) -> SystemValue:
    return SystemValue("found", normalized)


NOT_FOUND = SystemValue("not_found", None)
REJECTED = SystemValue("rejected", None)
FAILED = SystemValue("failed", None)


def outcome(field, g, s, extracted=True) -> CaseOutcome:  # type: ignore[no-untyped-def]
    return field_outcome(field, g, s, extracted=extracted)


# --- the R-7 table, row by row ------------------------------------------------------------


@pytest.mark.parametrize("field", [FREE, RECORDS, catalog.field("appendices")])
@pytest.mark.parametrize("g", [None, gold("x"), ABSENT])
def test_manual_kinds(field, g) -> None:  # type: ignore[no-untyped-def]
    assert outcome(field, g, found("x")).outcome is Outcome.MANUAL


@pytest.mark.parametrize("s", [found("1"), NOT_FOUND, REJECTED, FAILED, None])
def test_unlabeled_with_any_system(s) -> None:  # type: ignore[no-untyped-def]
    assert outcome(NUMBER, None, s) == CaseOutcome(Outcome.UNLABELED, ())


def test_no_row_is_no_result_not_run() -> None:
    assert outcome(NUMBER, gold("1"), None) == CaseOutcome(Outcome.NO_RESULT, ("not_run",))


def test_failed_is_no_result() -> None:
    assert outcome(NUMBER, gold("1"), FAILED) == CaseOutcome(Outcome.NO_RESULT, ("failed",))


def test_stale_is_no_result() -> None:
    stale = SystemValue("found", "1", stale=True)
    assert outcome(NUMBER, gold("1"), stale) == CaseOutcome(Outcome.NO_RESULT, ("stale",))


def test_field_not_extracted_is_no_result() -> None:
    assert outcome(NUMBER, ABSENT, None, extracted=False) == CaseOutcome(
        Outcome.NO_RESULT, ("not_extracted",)
    )


def test_value_found_equal() -> None:
    assert outcome(NUMBER, gold("ДП-1"), found("ДП-1")) == CaseOutcome(Outcome.CORRECT, ())


def test_value_found_equal_to_one_of_variants() -> None:
    assert outcome(AMOUNT, gold("1.00", "2.00"), found("2.00")).outcome is Outcome.CORRECT


def test_value_found_different() -> None:
    assert outcome(AMOUNT, gold("1.00"), found("2.00")) == CaseOutcome(Outcome.WRONG, ())


def test_value_not_found() -> None:
    assert outcome(NUMBER, gold("1"), NOT_FOUND) == CaseOutcome(Outcome.MISSED, ())


def test_value_rejected_is_missed_with_flag() -> None:
    assert outcome(NUMBER, gold("1"), REJECTED) == CaseOutcome(Outcome.MISSED, ("rejected",))


def test_absent_found_is_invented() -> None:
    assert outcome(NUMBER, ABSENT, found("1")) == CaseOutcome(Outcome.INVENTED, ())


def test_absent_not_found_is_correct() -> None:
    assert outcome(NUMBER, ABSENT, NOT_FOUND) == CaseOutcome(Outcome.CORRECT, ())


def test_absent_rejected_is_correct_with_flag() -> None:
    assert outcome(NUMBER, ABSENT, REJECTED) == CaseOutcome(Outcome.CORRECT, ("rejected",))


def test_names_compare_without_case() -> None:
    assert outcome(NAME, gold('ООО "Альфа"'), found('ооо "АЛЬФА"')).outcome is Outcome.CORRECT


def test_identifiers_keep_case() -> None:
    assert outcome(NUMBER, gold("А-1"), found("а-1")).outcome is Outcome.WRONG


# --- totals --------------------------------------------------------------------------------


def case(doc: int, field: str, out: Outcome, extracted: bool = True) -> FieldCase:
    return FieldCase(f"D-{doc:04d}", field, CaseOutcome(out, ()), extracted)


def test_totals_count_every_outcome_and_sum_to_pairs() -> None:
    cases = [
        case(1, "contract_number", Outcome.CORRECT),
        case(2, "contract_number", Outcome.WRONG),
        case(3, "contract_number", Outcome.MISSED),
        case(4, "contract_number", Outcome.INVENTED),
        case(5, "contract_number", Outcome.UNLABELED),
        case(6, "contract_number", Outcome.NO_RESULT),
        case(1, "payment_terms", Outcome.MANUAL),
    ]
    t = totals(cases)
    assert t.overall.total == 7
    assert sum(t.overall.counts.values()) == 7
    assert {o: t.overall.counts[o] for o in Outcome} == {
        Outcome.CORRECT: 1, Outcome.WRONG: 1, Outcome.MISSED: 1, Outcome.INVENTED: 1,
        Outcome.UNLABELED: 1, Outcome.NO_RESULT: 1, Outcome.MANUAL: 1,
    }
    assert t.overall.scored == 4
    assert t.overall.share(Outcome.CORRECT) == pytest.approx(0.25)
    assert t.overall.share(Outcome.INVENTED) == pytest.approx(0.25)


def test_shares_exclude_unlabeled_no_result_manual() -> None:
    t = totals([
        case(1, "contract_number", Outcome.CORRECT),
        case(2, "contract_number", Outcome.UNLABELED),
        case(3, "contract_number", Outcome.NO_RESULT),
    ])
    assert t.overall.scored == 1
    assert t.overall.share(Outcome.CORRECT) == pytest.approx(1.0)


def test_zero_denominator_gives_no_share() -> None:
    t = totals([case(1, "contract_number", Outcome.UNLABELED)])
    assert t.overall.share(Outcome.CORRECT) is None
    assert t.fields[0].counts.share(Outcome.CORRECT) is None


def test_fields_sorted_worst_first_then_invented() -> None:
    cases = [
        # contract_number: 1/2 correct, 1 invented
        case(1, "contract_number", Outcome.CORRECT),
        case(2, "contract_number", Outcome.INVENTED),
        # amount_with_vat: 1/2 correct, 0 invented
        case(1, "amount_with_vat", Outcome.CORRECT),
        case(2, "amount_with_vat", Outcome.WRONG),
        # customer_name_short: 2/2 correct
        case(1, "customer_name_short", Outcome.CORRECT),
        case(2, "customer_name_short", Outcome.CORRECT),
        # contract_end_date: 0/1 correct
        case(1, "contract_end_date", Outcome.MISSED),
    ]
    t = totals(cases)
    assert [f.field for f in t.fields] == [
        "contract_end_date", "contract_number", "amount_with_vat", "customer_name_short",
    ]


def test_fields_without_share_go_last_in_catalog_order() -> None:
    t = totals([
        case(1, "amount_with_vat", Outcome.UNLABELED),
        case(1, "contract_number", Outcome.UNLABELED),
        case(1, "customer_name_short", Outcome.CORRECT),
    ])
    assert [f.field for f in t.fields] == [
        "customer_name_short", "contract_number", "amount_with_vat",
    ]


def test_fields_not_extracted_are_a_separate_block() -> None:
    t = totals([
        case(1, "contract_number", Outcome.CORRECT),
        case(1, "vat_rate", Outcome.NO_RESULT, extracted=False),
    ])
    assert [f.field for f in t.fields] == ["contract_number"]
    assert [f.field for f in t.not_extracted] == ["vat_rate"]
    assert t.overall.total == 2


def test_field_counts_sum_to_overall() -> None:
    cases = [case(d, n, Outcome.CORRECT) for d in (1, 2) for n in ("contract_number", "vat_rate")]
    t = totals(cases)
    assert sum(f.counts.total for f in t.fields + t.not_extracted) == t.overall.total
