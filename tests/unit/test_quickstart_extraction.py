"""Pure helpers of scripts/quickstart_extraction.py (feature 05, quickstart Б4–Б5; T028).

The script prints counts and shares only — never values, quotes, names or file names.
Written by the main session; the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import importlib.util
from itertools import pairwise
from pathlib import Path

from docreader.fields import Kind

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_extraction", ROOT / "scripts" / "quickstart_extraction.py"
)
assert _spec is not None and _spec.loader is not None
qs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qs)


# --- reason kinds ------------------------------------------------------------------------


def test_reason_kinds() -> None:
    assert qs.reason_kind("нет цитаты") == "нет цитаты"
    assert qs.reason_kind("цитата не найдена") == "цитата не найдена"
    assert qs.reason_kind("значение не подтверждено цитатой") == (
        "значение не подтверждено цитатой"
    )
    assert qs.reason_kind("значение не приводится к сумме") == "значение не приводится к виду"
    assert qs.reason_kind("значение не приводится к дате") == "значение не приводится к виду"
    assert qs.reason_kind("что-то новое") == "другое"


# --- per field counts --------------------------------------------------------------------


def test_field_counts() -> None:
    rows = [
        ("contract_number", "found"), ("contract_number", "found"),
        ("amount_with_vat", "not_found"), ("amount_with_vat", "rejected"),
        ("contract_end_date", "failed"),
    ]
    counts = qs.field_counts(rows)
    assert list(counts) == [
        "contract_number", "customer_name_short", "contractor_name_short",
        "amount_without_vat", "amount_with_vat", "contract_end_date",
    ]
    assert counts["contract_number"] == {"found": 2, "not_found": 0, "rejected": 0, "failed": 0}
    assert counts["amount_with_vat"] == {"found": 0, "not_found": 1, "rejected": 1, "failed": 0}
    assert counts["contract_end_date"]["failed"] == 1
    assert counts["customer_name_short"] == {
        "found": 0, "not_found": 0, "rejected": 0, "failed": 0
    }


# --- SC-001 re-check ---------------------------------------------------------------------

TEXT = "ДОГОВОР ПОДРЯДА\n№ ДП-17/2026\nЦена 1 440 000 рублей.\nПриложение № 1\n"
SHOWN = TEXT.index("Приложение")


def _quote(fragment: str) -> tuple[str, int, int]:
    start = TEXT.index(fragment)
    return fragment, start, start + len(fragment)


def test_recheck_passes_a_good_row() -> None:
    quote, start, end = _quote("№ ДП-17/2026")
    assert qs.recheck(Kind.IDENTIFIER, "ДП-17/2026", quote, start, end, TEXT, SHOWN)
    quote, start, end = _quote("Цена 1 440 000 рублей")
    assert qs.recheck(Kind.AMOUNT, "1440000.00", quote, start, end, TEXT, SHOWN)


def test_recheck_fails_when_the_text_moved() -> None:
    quote, start, end = _quote("№ ДП-17/2026")
    assert not qs.recheck(Kind.IDENTIFIER, "ДП-17/2026", quote, start + 1, end + 1, TEXT, SHOWN)


def test_recheck_fails_when_the_value_is_not_in_the_quote() -> None:
    quote, start, end = _quote("Цена 1 440 000 рублей")
    assert not qs.recheck(Kind.AMOUNT, "1200000.00", quote, start, end, TEXT, SHOWN)


def test_recheck_fails_outside_the_shown_part() -> None:
    quote, start, end = _quote("Приложение № 1")
    assert not qs.recheck(Kind.IDENTIFIER, "1", quote, start, end, TEXT, SHOWN)


# --- run time ----------------------------------------------------------------------------


def test_seconds_summary() -> None:
    assert qs.seconds_summary([10.0, 30.0, 20.0, None]) == {
        "documents": 3, "total": 60.0, "median": 20.0, "max": 30.0
    }
    assert qs.seconds_summary([]) == {"documents": 0, "total": 0.0, "median": None, "max": None}


# --- the documents for the manual check of Б5 ------------------------------------------------


def _docs(n_scans: int, review: set[int] = frozenset(), text_layer: int = 3) -> list[dict]:
    docs = [
        {"document_id": f"D-{i:04d}", "text_layer": True, "state": "done"}
        for i in range(1, text_layer + 1)
    ]
    for j in range(n_scans):
        seq = text_layer + 1 + j
        docs.append({
            "document_id": f"D-{seq:04d}",
            "text_layer": False,
            "state": "needs_review" if seq in review else "done",
        })
    return docs


def test_pick_review_all_text_layer_then_seven_scans_at_an_even_step() -> None:
    docs = _docs(53)
    picked = qs.pick_review(docs)
    assert len(picked) == 10
    assert picked[:3] == ["D-0001", "D-0002", "D-0003"]
    scans = [d["document_id"] for d in docs if not d["text_layer"]]
    steps = [scans.index(p) for p in picked[3:]]
    assert steps == sorted(steps)
    gaps = {b - a for a, b in pairwise(steps)}
    assert max(gaps) - min(gaps) <= 1  # an even step
    assert steps[0] == 0


def test_pick_review_includes_a_needs_review_scan() -> None:
    docs = _docs(53, review={40})
    picked = qs.pick_review(docs)
    assert "D-0040" in picked
    assert len(picked) == 10


def test_pick_review_keeps_a_picked_needs_review_scan() -> None:
    docs = _docs(53)
    first = qs.pick_review(docs)[3]
    for d in docs:
        if d["document_id"] == first:
            d["state"] = "needs_review"
    # a needs_review scan is already among the picks: the picks stay the same
    assert qs.pick_review(docs) == qs.pick_review(_docs(53))


def test_pick_review_with_few_scans() -> None:
    picked = qs.pick_review(_docs(4))
    assert picked == ["D-0001", "D-0002", "D-0003", "D-0004", "D-0005", "D-0006", "D-0007"]


def test_pick_review_is_deterministic() -> None:
    assert qs.pick_review(_docs(53, review={20, 33})) == qs.pick_review(
        _docs(53, review={20, 33})
    )
