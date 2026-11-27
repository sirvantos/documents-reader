"""Metrics of the rule usefulness report (feature 06, T019; research R-10).

Interface in `outcomes`:
- `check_outcome(gold: Outcome, queued: bool) -> CheckOutcome | None` — right = `correct`,
  wrong = `wrong`, `missed`, `invented`; `unlabeled`, `no_result`, `manual` → None (out);
- `CheckCase(document_id, field, outcome: CheckOutcome, fired: tuple[str, ...])`;
- `check_metrics(cases)` → {"rules": {rule: {"fired", "fired_on_wrong"}},
  "fields": [{"field", "wrong", "wrong_in_queue", "right", "right_in_queue"}, …] (catalog
  order, only fields with cases), "overall": {"pairs", "wrong", "wrong_in_queue", "right",
  "right_in_queue"}}.
"""

from __future__ import annotations

import pytest

from docreader.outcomes import CheckCase, CheckOutcome, Outcome, check_metrics, check_outcome

QW, QR = CheckOutcome.QUEUED_WRONG, CheckOutcome.QUEUED_RIGHT
AW, AR = CheckOutcome.ACCEPTED_WRONG, CheckOutcome.ACCEPTED_RIGHT


@pytest.mark.parametrize(
    ("gold", "queued", "expected"),
    [
        (Outcome.CORRECT, True, QR),
        (Outcome.CORRECT, False, AR),
        (Outcome.WRONG, True, QW),
        (Outcome.MISSED, False, AW),
        (Outcome.INVENTED, True, QW),
        (Outcome.UNLABELED, True, None),
        (Outcome.NO_RESULT, False, None),
        (Outcome.MANUAL, True, None),
    ],
)
def test_check_outcome(gold: Outcome, queued: bool, expected: CheckOutcome | None) -> None:
    assert check_outcome(gold, queued) is expected


def test_metrics_per_rule_field_and_overall() -> None:
    cases = [
        CheckCase("D-0001", "amount_with_vat", QW, ("vat_consistent", "amount_words")),
        CheckCase("D-0001", "amount_without_vat", QR, ("vat_consistent",)),
        CheckCase("D-0002", "amount_with_vat", AR, ()),
        CheckCase("D-0002", "contract_number", AW, ()),
        CheckCase("D-0003", "contract_number", AR, ()),
    ]
    m = check_metrics(cases)
    assert m["rules"] == {
        "vat_consistent": {"fired": 2, "fired_on_wrong": 1},
        "amount_words": {"fired": 1, "fired_on_wrong": 1},
    }
    assert m["fields"] == [
        {"field": "contract_number", "wrong": 1, "wrong_in_queue": 0, "right": 1,
         "right_in_queue": 0},
        {"field": "amount_without_vat", "wrong": 0, "wrong_in_queue": 0, "right": 1,
         "right_in_queue": 1},
        {"field": "amount_with_vat", "wrong": 1, "wrong_in_queue": 1, "right": 1,
         "right_in_queue": 0},
    ]
    assert m["overall"] == {"pairs": 5, "wrong": 2, "wrong_in_queue": 1, "right": 3,
                            "right_in_queue": 1}


def test_no_cases() -> None:
    assert check_metrics([]) == {
        "rules": {}, "fields": [],
        "overall": {"pairs": 0, "wrong": 0, "wrong_in_queue": 0, "right": 0,
                    "right_in_queue": 0},
    }
