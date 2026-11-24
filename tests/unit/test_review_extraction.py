"""scripts/review_extraction.py, pure parts (feature 05, quickstart Б5).

The page for the manual check stays on the analyst's Mac; only the summary of the answers
is sent to the agent, so the summary must hold counts, ids, field labels and error kinds
only (Constitution I). Written by the main session; the implementer must not edit, weaken,
skip or delete these tests.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "review_extraction", ROOT / "scripts" / "review_extraction.py"
)
assert _spec is not None and _spec.loader is not None
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)

FIELDS = [
    "contract_number", "customer_name_short", "contractor_name_short",
    "amount_without_vat", "amount_with_vat", "contract_end_date",
]


# --- PDF box → image pixels --------------------------------------------------------------


def test_pixel_box_upright_page() -> None:
    box = rv.pixel_box((100, 700, 200, 720), crop=(0, 0, 600, 800), rotation=0, scale=2)
    assert box == pytest.approx((200, 160, 400, 200))


def test_pixel_box_subtracts_the_crop_origin() -> None:
    box = rv.pixel_box((110, 720, 210, 740), crop=(10, 20, 610, 820), rotation=0, scale=2)
    assert box == pytest.approx((200, 160, 400, 200))


def test_pixel_box_rotated_page() -> None:
    # /Rotate 90: the displayed page is 800 wide and 600 high
    box = rv.pixel_box((100, 700, 200, 720), crop=(0, 0, 600, 800), rotation=90, scale=2)
    assert box == pytest.approx((1400, 200, 1440, 400))


# --- hints (never verdicts) --------------------------------------------------------------


def test_vat_hint_silent_when_the_rate_fits() -> None:
    assert rv.vat_hint("1200000.00", "1440000.00") is None  # 20%
    assert rv.vat_hint("1000000.00", "1220000.00") is None  # 22%
    assert rv.vat_hint("1000000.00", "1220000.40") is None  # rounding by year


def test_vat_hint_when_the_rate_does_not_fit() -> None:
    hint = rv.vat_hint("1200000.00", "1500000.00")
    assert hint is not None and "НДС" in hint
    assert "1200000" not in hint and "1500000" not in hint  # no values in a hint


def test_vat_hint_needs_both_amounts() -> None:
    assert rv.vat_hint(None, "1440000.00") is None
    assert rv.vat_hint("1200000.00", None) is None


def test_party_hints() -> None:
    majority = {
        "customer_name_short": ("ооо альфа", 0.9),
        "contractor_name_short": ("ооо бета", 0.3),
    }
    same = rv.party_hints(
        {"customer_name_short": "ооо гамма", "contractor_name_short": "ооо гамма"}, majority
    )
    assert any("совпадают" in h for h in same)
    assert any("большинств" in h for h in same)  # the customer differs from 90% of the set
    assert all("гамма" not in h and "альфа" not in h for h in same)
    usual = rv.party_hints(
        {"customer_name_short": "ооо альфа", "contractor_name_short": "ооо дельта"}, majority
    )
    assert usual == []  # no clear majority for the contractor


# --- the choices of a card ---------------------------------------------------------------


def test_choices_follow_the_result() -> None:
    assert [c for c, _ in rv.CHOICES["found"]] == ["correct", "wrong", "invented"]
    assert [c for c, _ in rv.CHOICES["not_found"]] == ["correct_absent", "missed"]
    assert [c for c, _ in rv.CHOICES["rejected"]] == ["right_reject", "wrong_reject"]


# --- the summary of the answers ----------------------------------------------------------


def _items() -> list[dict]:
    return [
        {"document_id": f"D-{n:04d}", "field": f, "result": "found", "answer": "correct"}
        for n in range(1, 11)
        for f in FIELDS
    ]


def test_summary_all_correct() -> None:
    out = "\n".join(rv.summarize({"version": 1, "items": _items()}))
    assert "договоров: 10, полей: 60, отмечено: 60" in out
    assert "SC-002: верных результатов 60 из 60 (100%)" in out and "выполнен" in out
    assert "SC-003: придуманных значений 0" in out


def test_summary_counts_by_kind_and_lists_errors() -> None:
    items = _items()
    for i in items:
        key = (i["document_id"], i["field"])
        if key == ("D-0003", "contract_end_date"):
            i.update(answer="wrong", error_kind="other_date")
        elif key == ("D-0005", "amount_with_vat"):
            i.update(result="rejected", answer="right_reject")
        elif key == ("D-0006", "amount_with_vat"):
            i.update(result="not_found", answer="missed", error_kind="recognition")
        elif key == ("D-0007", "customer_name_short"):
            i.update(answer="invented", error_kind="other")
    out = "\n".join(rv.summarize({"version": 1, "items": items}))
    # correct = right value or right «not found»; a right rejection is not a value (SC-002)
    assert "SC-002: верных результатов 56 из 60 (93%)" in out
    assert "SC-003: придуманных значений 1 — не выполнен" in out
    assert "дата окончания: 9 / 0 / 1 / 0 / 0 / 0 / 0" in out
    assert "цена с НДС: 8 / 0 / 0 / 1 / 0 / 1 / 0" in out
    assert "D-0003, дата окончания: дата другого события" in out
    assert "D-0006, цена с НДС: ошибка распознавания" in out
    assert "D-0007, заказчик: другое" in out


def test_summary_threshold_not_met_and_unmarked() -> None:
    items = _items()
    for i in items[:7]:
        i.update(answer="wrong", error_kind="other_value")
    items[-1]["answer"] = None
    out = "\n".join(rv.summarize({"version": 1, "items": items}))
    assert "отмечено: 59" in out
    assert "не отмечено: 1" in out
    assert "не посчитан" in out  # SC-002 waits for all 60 answers


def test_summary_never_prints_foreign_text() -> None:
    secret = "ООО «Ромашка» 1 234 567 рублей"
    items = _items()
    items[0].update(answer="wrong", error_kind=secret, note=secret, value=secret)
    items[1].update(document_id=secret)
    items[2].update(field=secret)
    items[3].update(answer=secret)
    out = "\n".join(rv.summarize({"version": 1, "items": items}))
    assert "Ромашка" not in out and "1 234 567" not in out
    assert "отброшено записей: 3" in out  # bad id, bad field, bad answer
