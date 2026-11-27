"""Queue cards order and the parse of the queue page answers (feature 06, T015; R-9).

Interface of `check_queue`:
- `sort_cards(cards)` — cards (dicts per contracts/files.md) in queue order: the five
  required fields first, then the end date; within each group by document, then by catalog
  order of the field; a card flagged `system_changed` first in its group;
- `parse_answers(data, cards)` → `ParsedAnswers(decisions, errors, skipped)`:
  `decisions[(document_id, field)] = Decision(kind, value_text, value_normalized, clause_key)`;
  `errors` — `(card key, reason code)`; a bad file (not JSON, wrong format) → `UserError`.
"""

from __future__ import annotations

import json

import pytest

from docreader.check_queue import ANSWERS_FORMAT, Decision, parse_answers, sort_cards
from docreader.checks import DecisionKind
from docreader.errors import UserError


def card(doc: str, field: str, result: str = "found", flags: tuple[str, ...] = ()) -> dict:
    return {
        "key": f"{doc}/{field}", "document_id": doc, "field": field, "status": "needs_review",
        "reasons": [], "flags": list(flags),
        "system": {"result": result, "value": "x", "normalized": "x", "quote": "q",
                   "clause": "2.1", "pages": [1], "image": None},
        "decision": None,
    }


def test_order_required_fields_then_end_date_by_document() -> None:
    cards = [
        card("D-0002", "contract_end_date"),
        card("D-0002", "amount_with_vat"),
        card("D-0001", "contract_end_date"),
        card("D-0001", "amount_with_vat"),
        card("D-0001", "contract_number"),
        card("D-0002", "customer_name_short"),
    ]
    got = [c["key"] for c in sort_cards(cards)]
    assert got == [
        "D-0001/contract_number", "D-0001/amount_with_vat",
        "D-0002/customer_name_short", "D-0002/amount_with_vat",
        "D-0001/contract_end_date", "D-0002/contract_end_date",
    ]


def test_system_changed_first_in_its_group() -> None:
    cards = [
        card("D-0001", "contract_number"),
        card("D-0003", "amount_with_vat", flags=("system_changed",)),
        card("D-0002", "contract_end_date"),
        card("D-0004", "contract_end_date", flags=("system_changed",)),
    ]
    got = [c["key"] for c in sort_cards(cards)]
    assert got == ["D-0003/amount_with_vat", "D-0001/contract_number",
                   "D-0004/contract_end_date", "D-0002/contract_end_date"]


CARDS = [
    card("D-0001", "amount_with_vat"),
    card("D-0001", "contract_number", result="rejected"),
    card("D-0002", "amount_without_vat", result="not_found"),
    card("D-0002", "contract_end_date"),
    card("D-0003", "customer_name_short", result="failed"),
]


def answers(*items: dict, fmt: str = ANSWERS_FORMAT) -> bytes:
    return json.dumps({"format": fmt, "build": "b1", "cards": list(items)},
                      ensure_ascii=False).encode("utf-8")


def test_answers_of_the_three_kinds_and_skip() -> None:
    parsed = parse_answers(answers(
        {"key": "D-0001/amount_with_vat", "answer": "agree"},
        {"key": "D-0002/amount_without_vat", "answer": "typed", "value": "1 000 000,00",
         "clause": "D-0002/2.1"},
        {"key": "D-0002/contract_end_date", "answer": "absent"},
        {"key": "D-0003/customer_name_short", "answer": "skip"},
    ), CARDS)
    assert parsed.decisions == {
        ("D-0001", "amount_with_vat"): Decision(DecisionKind.CONFIRM, None, None, None),
        ("D-0002", "amount_without_vat"): Decision(
            DecisionKind.CORRECT, "1 000 000,00", "1000000.00", "2.1"),
        ("D-0002", "contract_end_date"): Decision(DecisionKind.ABSENT, None, None, None),
    }
    assert parsed.errors == [] and parsed.skipped == 1


@pytest.mark.parametrize("key", ["D-0001/contract_number", "D-0002/amount_without_vat",
                                 "D-0003/customer_name_short"])
def test_agree_only_on_a_found_value(key: str) -> None:
    # analyze U1, principle III: no «confirm» without a found, quote-checked value
    parsed = parse_answers(answers({"key": key, "answer": "agree"}), CARDS)
    assert parsed.decisions == {}
    assert parsed.errors == [(key, "agree_without_value")]


def test_typed_value_is_normalized_by_the_field_kind() -> None:
    parsed = parse_answers(answers(
        {"key": "D-0001/contract_number", "answer": "typed", "value": "№ Р-9/2026"},
        {"key": "D-0002/contract_end_date", "answer": "typed", "value": "тридцатого"},
    ), CARDS)
    assert parsed.decisions[("D-0001", "contract_number")].kind is DecisionKind.CORRECT
    assert parsed.errors == [("D-0002/contract_end_date", "kind_invalid")]


def test_unknown_key_and_unknown_answer_are_errors() -> None:
    parsed = parse_answers(answers(
        {"key": "D-0009/amount_with_vat", "answer": "agree"},
        {"key": "D-0001/amount_with_vat", "answer": "maybe"},
        {"key": "D-0002/contract_end_date", "answer": "typed", "value": ""},
    ), CARDS)
    assert parsed.decisions == {}
    assert parsed.errors == [("D-0009/amount_with_vat", "unknown_card"),
                             ("D-0001/amount_with_vat", "unknown_answer"),
                             ("D-0002/contract_end_date", "kind_invalid")]


@pytest.mark.parametrize("data", [b"not json", answers(fmt="docreader-gold-review/1"), b"[]"])
def test_bad_file_is_refused(data: bytes) -> None:
    with pytest.raises(UserError):
        parse_answers(data, CARDS)
