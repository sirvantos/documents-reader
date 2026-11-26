"""Outcomes of pairs «document, field» and their totals (feature 02, T008, research R-7)."""

from __future__ import annotations

import pytest

from docreader import catalog
from docreader.gold import GoldState
from docreader.outcomes import (
    CaseChange,
    CaseOutcome,
    EvalStage,
    FieldCase,
    GoldValue,
    Outcome,
    RecordView,
    StoredCase,
    SystemValue,
    compare,
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


# --- comparison of two records (T029, research R-13) ---------------------------------------

def rec(stage: EvalStage, cases: dict[str, tuple[str | None, int | None]],
        metrics: dict | None = None, gold: str = "g1",  # type: ignore[type-arg]
        gold_sha: dict[str, str] | None = None) -> RecordView:
    shas = gold_sha or {}
    return RecordView(
        stage, metrics or {}, gold,
        {k: StoredCase(k, o, p, shas.get(k, "0" * 16)) for k, (o, p) in cases.items()},
    )


F = EvalStage.FIELDS


def test_different_stages_cannot_be_compared() -> None:
    with pytest.raises(ValueError, match="этап"):
        compare(rec(F, {}), rec(EvalStage.RULES, {}))


def test_better_and_worse_by_rank() -> None:
    a = rec(F, {"k1": ("missed", None), "k2": ("correct", None), "k3": ("wrong", None),
                "k4": ("missed", None), "k5": ("correct", None)})
    b = rec(F, {"k1": ("correct", None), "k2": ("invented", None), "k3": ("missed", None),
                "k4": ("invented", None), "k5": ("correct", None)})
    c = compare(a, b)
    assert c.better == [CaseChange("k1", "missed", "correct"), CaseChange("k3", "wrong", "missed")]
    assert c.worse == [CaseChange("k2", "correct", "invented"),
                       CaseChange("k4", "missed", "invented")]
    assert c.outside == [] and c.by_gold == []


@pytest.mark.parametrize("pair", [("correct", "no_result"), ("unlabeled", "correct"),
                                  ("manual", "unlabeled"), ("no_result", "wrong")])
def test_unscored_transitions_are_outside(pair: tuple[str, str]) -> None:
    c = compare(rec(F, {"k": (pair[0], None)}), rec(F, {"k": (pair[1], None)}))
    assert c.outside == [CaseChange("k", pair[0], pair[1])]
    assert c.better == c.worse == []


def test_case_in_one_record_only_is_outside() -> None:
    c = compare(rec(F, {"k": ("correct", None)}), rec(F, {"j": ("correct", None)}))
    assert c.outside == [CaseChange("j", "—", "correct"), CaseChange("k", "correct", "—")]


def test_changed_gold_goes_to_its_own_group() -> None:
    a = rec(F, {"k": ("wrong", None), "j": ("wrong", None)}, gold="g1",
            gold_sha={"k": "a" * 16, "j": "b" * 16})
    b = rec(F, {"k": ("correct", None), "j": ("correct", None)}, gold="g2",
            gold_sha={"k": "c" * 16, "j": "b" * 16})
    c = compare(a, b)
    assert c.gold_differs
    assert c.by_gold == [CaseChange("k", "wrong", "correct")]
    assert c.better == [CaseChange("j", "wrong", "correct")]


def test_unchanged_cases_never_appear() -> None:
    cases = {f"k{i}": ("correct", None) for i in range(5)}
    c = compare(rec(F, cases), rec(F, dict(cases)))
    assert (c.better, c.worse, c.outside, c.by_gold) == ([], [], [], [])
    assert not c.gold_differs


def test_every_changed_case_appears_exactly_once() -> None:
    outcomes = ["correct", "wrong", "missed", "invented", "unlabeled", "no_result", "manual"]
    a = {f"{x}>{y}": (x, None) for x in outcomes for y in outcomes}
    b = {f"{x}>{y}": (y, None) for x in outcomes for y in outcomes}
    c = compare(rec(F, a), rec(F, b))
    listed = [ch.case_key for ch in c.better + c.worse + c.outside + c.by_gold]
    assert sorted(listed) == sorted(k for k in a if k.split(">")[0] != k.split(">")[1])


def test_search_places() -> None:
    s = EvalStage.SEARCH_RERANK
    a = rec(s, {"q1": (None, 3), "q2": (None, 1), "q3": (None, None), "q4": (None, 2)})
    b = rec(s, {"q1": (None, 1), "q2": (None, None), "q3": (None, 7), "q4": (None, 2)})
    c = compare(a, b)
    assert c.better == [CaseChange("q1", "3", "1"), CaseChange("q3", "не найден", "7")]
    assert c.worse == [CaseChange("q2", "1", "не найден")]


def test_excluded_search_questions_are_outside() -> None:
    s = EvalStage.SEARCH_PLAIN
    a = RecordView(s, {}, "g", {"q": StoredCase("q", None, None, "0" * 16, ("excluded",))})
    b = RecordView(s, {}, "g", {"q": StoredCase("q", None, 2, "0" * 16)})
    assert compare(a, b).outside == [CaseChange("q", "вне метрик", "2")]


def test_metric_differences() -> None:
    a = rec(F, {}, metrics={"overall": {"correct": 10, "share": {"correct": 0.5}}, "note": "x"})
    b = rec(F, {}, metrics={"overall": {"correct": 12, "share": {"correct": 0.6}}, "note": "y"})
    c = compare(a, b)
    assert c.metrics["overall.correct"] == (10, 12)
    assert c.metrics["overall.share.correct"] == (0.5, 0.6)
    assert "note" not in c.metrics


def test_blind_outcomes_rank() -> None:
    g = EvalStage.GOLD_BLIND
    c = compare(rec(g, {"k": ("differs", None)}), rec(g, {"k": ("same", None)}))
    assert c.better == [CaseChange("k", "differs", "same")]


# --- search places and metrics (T035, research R-12) ----------------------------------------


def test_search_place_first_of_several_correct() -> None:
    from docreader.outcomes import search_place

    found = ["D-0001/1.1", "D-0001/2.2", "D-0001/2.1"]
    assert search_place(found, ("2.1", "2.2")) == 2
    assert search_place(found, ("9.9",)) is None
    assert search_place(found, ("2",)) is None  # exact match only, no parent clause
    assert search_place(["D-0001/2.2.1"], ("2.2",)) is None  # nor a subclause


def test_search_metrics() -> None:
    from docreader.outcomes import SearchCase, search_metrics

    cases = [
        SearchCase("q1", 1, False), SearchCase("q2", 3, False), SearchCase("q3", 7, False),
        SearchCase("q4", None, False), SearchCase("q5", None, True), SearchCase("q6", 1, True),
    ]
    m = search_metrics(cases)
    assert m.participating == 4 and m.excluded == 2
    assert m.first == 1 and m.top5 == 2 and m.not_found == 1
    assert m.share_first == pytest.approx(0.25)
    assert m.share_top5 == pytest.approx(0.5)
    assert m.median_place == 3


def test_search_metrics_without_participants() -> None:
    from docreader.outcomes import SearchCase, search_metrics

    m = search_metrics([SearchCase("q", None, True)])
    assert m.participating == 0 and m.share_first is None and m.median_place is None
