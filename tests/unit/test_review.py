"""Review cards: marks, order, carried answers, blind hiding (feature 02, T017, research R-9)."""

from __future__ import annotations

from docreader.gold import GoldPath, GoldState
from docreader.review import (
    Card,
    GoldRow,
    Mark,
    Shown,
    SystemField,
    build_cards,
)

DOCS = ["D-0001", "D-0002"]


def shown(normalized: str, value: str | None = None, clause: str = "2.1") -> Shown:
    return Shown(value or normalized, normalized, clause, f"цитата {value or normalized}", 0, 1,
                 (1,))


def found(normalized: str, value: str | None = None) -> SystemField:
    return SystemField("found", shown(normalized, value), None, None)


NOT_FOUND = SystemField("not_found", None, None, None)
REJECTED = SystemField("rejected", None, "цитата не найдена", "1 000")


def gold(path: GoldPath, *normalized: str, system: str | None = None,
         clause: str | None = None) -> GoldRow:
    state = GoldState.VALUE if normalized else GoldState.ABSENT
    return GoldRow(state, tuple(normalized), tuple(normalized), path, system, clause)


def cards(system=None, rules=None, gold_rows=None, blind=frozenset(),  # type: ignore[no-untyped-def]
          docs=("D-0001",), fields=("amount_with_vat",)) -> list[Card]:
    return build_cards(list(docs), list(fields), system or {}, rules or {}, gold_rows or {},
                       set(blind))


P = ("D-0001", "amount_with_vat")


def one(**kw) -> Card:  # type: ignore[no-untyped-def]
    [card] = cards(**kw)
    return card


# --- marks ----------------------------------------------------------------------------------


def test_agree() -> None:
    c = one(system={P: found("100.00")}, rules={P: [shown("100.00")]})
    assert c.mark is Mark.AGREE
    assert c.key == "D-0001/amount_with_vat"


def test_names_agree_without_case() -> None:
    p = ("D-0001", "customer_name_short")
    c = one(system={p: found('ООО "Альфа"')}, rules={p: [shown('ооо "альфа"')]},
            fields=("customer_name_short",))
    assert c.mark is Mark.AGREE


def test_disagree() -> None:
    assert one(system={P: found("100.00")}, rules={P: [shown("200.00")]}).mark is Mark.DISAGREE


def test_several_rules_values_disagree_whatever_the_model() -> None:
    rules = {P: [shown("100.00"), shown("200.00")]}
    assert one(system={P: found("100.00")}, rules=rules).mark is Mark.DISAGREE
    assert one(system={P: NOT_FOUND}, rules=rules).mark is Mark.DISAGREE


def test_model_only() -> None:
    assert one(system={P: found("100.00")}).mark is Mark.MODEL_ONLY


def test_rules_only() -> None:
    assert one(system={P: NOT_FOUND}, rules={P: [shown("100.00")]}).mark is Mark.RULES_ONLY


def test_none() -> None:
    assert one(system={P: NOT_FOUND}).mark is Mark.NONE
    assert one().mark is Mark.NONE  # no extraction row at all


def test_rejected_counts_as_no_model_value_and_keeps_its_reason() -> None:
    c = one(system={P: REJECTED})
    assert c.mark is Mark.NONE
    assert c.model is None
    assert c.system is not None and c.system.reason == "цитата не найдена"
    assert one(system={P: REJECTED}, rules={P: [shown("1.00")]}).mark is Mark.RULES_ONLY


# --- changed --------------------------------------------------------------------------------


def test_changed_when_the_model_value_differs_from_the_one_shown() -> None:
    c = one(system={P: found("200.00")}, rules={P: [shown("200.00")]},
            gold_rows={P: gold(GoldPath.AGREE, "100.00", system="100.00")})
    assert c.mark is Mark.CHANGED
    assert c.carried is None


def test_corrected_answers_are_not_changed_while_the_system_shows_the_same() -> None:
    sys = {P: found("100.00")}
    for g in (
        gold(GoldPath.TYPED, "150.00", system="100.00"),
        gold(GoldPath.ABSENT_MARKED, system="100.00"),
        gold(GoldPath.CHOSEN, "200.00", system="100.00"),
    ):
        c = one(system=sys, rules={P: [shown("200.00")]}, gold_rows={P: g})
        assert c.mark is not Mark.CHANGED, g.path


def test_typed_without_a_model_value_becomes_changed_when_one_appears() -> None:
    g = gold(GoldPath.TYPED, "150.00", system=None)
    assert one(system={P: NOT_FOUND}, gold_rows={P: g}).mark is Mark.NONE
    assert one(system={P: found("150.00")}, gold_rows={P: g}).mark is Mark.CHANGED


def test_template_gold_is_never_changed() -> None:
    g = gold(GoldPath.TEMPLATE, "100.00")
    assert one(system={P: found("999.00")}, gold_rows={P: g}).mark is Mark.MODEL_ONLY


# --- carried answers ------------------------------------------------------------------------


def test_carried_agree() -> None:
    c = one(system={P: found("100.00")}, rules={P: [shown("100.00")]},
            gold_rows={P: gold(GoldPath.AGREE, "100.00", system="100.00")})
    assert c.carried == {"answer": "agree"}


def test_carried_chosen_rules() -> None:
    c = one(system={P: found("100.00")}, rules={P: [shown("150.00"), shown("200.00")]},
            gold_rows={P: gold(GoldPath.CHOSEN, "200.00", system="100.00")})
    assert c.carried == {"answer": "chosen", "choice": "rules:2"}


def test_carried_chosen_model() -> None:
    c = one(system={P: found("100.00")}, rules={P: [shown("200.00")]},
            gold_rows={P: gold(GoldPath.CHOSEN, "100.00", system="100.00")})
    assert c.carried == {"answer": "chosen", "choice": "model"}


def test_carried_typed_and_absent() -> None:
    typed = one(system={P: found("100.00")},
                gold_rows={P: gold(GoldPath.TYPED, "150.00", system="100.00", clause="2.2")})
    assert typed.carried == {"answer": "typed", "value": "150.00", "clause": "D-0001/2.2"}
    absent = one(system={P: found("100.00")},
                 gold_rows={P: gold(GoldPath.ABSENT_MARKED, system="100.00")})
    assert absent.carried == {"answer": "absent"}


def test_no_gold_no_carried_answer() -> None:
    assert one(system={P: found("100.00")}).carried is None


# --- order and blind ------------------------------------------------------------------------


def test_order_by_mark_then_document_then_catalog() -> None:
    fields = ("contract_number", "amount_with_vat")
    sys = {
        ("D-0001", "contract_number"): found("А-1"),
        ("D-0001", "amount_with_vat"): found("1.00"),
        ("D-0002", "contract_number"): found("А-2"),
        ("D-0002", "amount_with_vat"): NOT_FOUND,
    }
    rules = {
        ("D-0001", "contract_number"): [shown("А-1")],
        ("D-0001", "amount_with_vat"): [shown("2.00")],
        ("D-0002", "contract_number"): [shown("А-2")],
    }
    got = cards(system=sys, rules=rules, docs=DOCS, fields=fields)
    assert [(c.key, c.mark) for c in got] == [
        ("D-0001/amount_with_vat", Mark.DISAGREE),
        ("D-0002/amount_with_vat", Mark.NONE),
        ("D-0001/contract_number", Mark.AGREE),
        ("D-0002/contract_number", Mark.AGREE),
    ]


def test_full_mark_order() -> None:
    assert list(Mark) == [Mark.CHANGED, Mark.DISAGREE, Mark.RULES_ONLY, Mark.NONE,
                          Mark.MODEL_ONLY, Mark.AGREE]


def test_blind_waiting_documents_give_no_cards() -> None:
    got = cards(system={("D-0002", "amount_with_vat"): found("1.00")}, docs=DOCS,
                blind={"D-0002"})
    assert [c.document_id for c in got] == ["D-0001"]
