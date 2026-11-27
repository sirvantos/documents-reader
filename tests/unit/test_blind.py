"""Blind control: the pick of documents (feature 02, T023, research R-10)."""

from __future__ import annotations

import itertools

from docreader import catalog
from docreader.blind import BlindPair, blind_outcome, blind_totals, pick
from docreader.gold import GoldPath, GoldState
from docreader.outcomes import BlindOutcome, GoldValue


def docs(layers: int, scans: int) -> list[dict[str, object]]:
    out = []
    for i in range(1, layers + scans + 1):
        out.append({"document_id": f"D-{i:04d}", "text_layer": i <= layers, "state": "done"})
    return out


def test_one_text_layer_and_scans_at_an_even_step() -> None:
    got = pick(docs(3, 53), count=5)
    assert len(got) == 5
    assert got[0] == "D-0001"
    scans = [d for d in got if d != "D-0001"]
    assert all(int(d[2:]) > 3 for d in scans)
    numbers = [int(d[2:]) for d in scans]
    assert numbers == sorted(numbers)
    steps = [b - a for a, b in itertools.pairwise(numbers)]
    assert max(steps) - min(steps) <= 1


def test_no_text_layer_takes_scans_only() -> None:
    assert len(pick(docs(0, 10), count=5)) == 5


def test_too_few_scans_are_filled_with_text_layer_documents() -> None:
    got = pick(docs(7, 1), count=5)
    assert len(got) == 5
    assert "D-0008" in got  # the only scan


def test_fewer_documents_than_count_takes_all() -> None:
    assert pick(docs(1, 2), count=5) == ["D-0001", "D-0002", "D-0003"]


def test_pick_is_deterministic_and_sorted() -> None:
    a = pick(docs(3, 40), count=5)
    assert a == pick(list(reversed(docs(3, 40))), count=5)
    assert a == sorted(a)


# --- the blind report (T025) ----------------------------------------------------------------


def v(*norm: str) -> GoldValue:
    return GoldValue(GoldState.VALUE if norm else GoldState.ABSENT, norm)


def bp(blind, reviewed, path=GoldPath.AGREE, after=True, field="amount_with_vat"):  # type: ignore[no-untyped-def]
    return BlindPair("D-0001", field, blind, reviewed, path, after)


def test_blind_outcomes() -> None:
    f = catalog.field("amount_with_vat")
    assert blind_outcome(f, bp(v("1.00"), v("1.00"))) is BlindOutcome.SAME
    assert blind_outcome(f, bp(v("1.00"), v("2.00"))) is BlindOutcome.DIFFERS
    assert blind_outcome(f, bp(v(), v())) is BlindOutcome.SAME
    assert blind_outcome(f, bp(v(), v("1.00"))) is BlindOutcome.DIFFERS
    assert blind_outcome(f, bp(v("1.00"), None, path=None)) is BlindOutcome.BLIND_ONLY
    assert blind_outcome(f, bp(None, v("1.00"))) is BlindOutcome.REVIEWED_ONLY
    assert blind_outcome(f, bp(v("1.00"), v("1.00"), after=False)) is None  # not counted


def test_blind_names_ignore_case() -> None:
    f = catalog.field("customer_name_short")
    pair = bp(v('ООО "Альфа"'), v('ооо "альфа"'), field="customer_name_short")
    assert blind_outcome(f, pair) is BlindOutcome.SAME


def test_blind_totals_split_by_confirmed_system_values() -> None:
    pairs = [
        bp(v("1"), v("1"), GoldPath.AGREE),
        bp(v("1"), v("2"), GoldPath.CONFIRMED),
        bp(v("1"), v("2"), GoldPath.CHOSEN),
        bp(v("1"), v("2"), GoldPath.TYPED),
        bp(v("1"), v("1"), GoldPath.AGREE, after=False),
        bp(v("1"), None, None),
    ]
    t = blind_totals(pairs)
    assert t.pairs == 5 and t.not_reviewed == 1
    assert (t.same, t.differs, t.blind_only, t.reviewed_only) == (1, 3, 1, 0)
    assert (t.confirmed_pairs, t.confirmed_differs) == (3, 2)


def test_stored_values_are_normalized_again_by_the_current_code() -> None:
    # analyst's measurement, record 27: the blind values were loaded before later fixes of
    # the normalization, so their stored forms differed from the gold set's
    from docreader.blind import current_value

    name = catalog.field("contractor_name_short")
    stale = current_value(name, "value", ["акционерное общество «Дельта»"], ["stale form"])
    assert stale == GoldValue(GoldState.VALUE, ('акционерное общество "Дельта"',))
    amount = catalog.field("amount_with_vat")
    assert current_value(amount, "value", ["1 800 000,00"], ["0"]).normalized == ("1800000.00",)
    # a text the current code cannot read keeps the stored form; «absent» stays absent
    assert current_value(amount, "value", ["???"], ["5.00"]).normalized == ("5.00",)
    assert current_value(amount, "absent", [], []) == GoldValue(GoldState.ABSENT, ())
