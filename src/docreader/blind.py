"""The blind control of the gold set (feature 02, research R-10).

A few documents are marked from an empty template before their review cards are shown.
The report compares those blind values with the values set by the review afterwards:
how often the review confirmed a system value that the blind marking disagrees with.
Pure functions here; the database part lives below them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from docreader import catalog
from docreader.gold import SYSTEM_CONFIRMED_PATHS, GoldPath, GoldState
from docreader.outcomes import BlindOutcome, GoldValue
from docreader.values import same_value


@dataclass(frozen=True)
class BlindPair:
    """A pair of a blind document: its blind value, its reviewed value and whether the
    reviewed value was loaded after the blind marking."""

    document_id: str
    field: str
    blind: GoldValue | None
    reviewed: GoldValue | None
    path: GoldPath | None
    after_blind: bool


def _same(field: catalog.CatalogField, a: GoldValue, b: GoldValue) -> bool:
    if a.state is not b.state:
        return False
    if a.state is GoldState.ABSENT:
        return True
    return any(same_value(field, x, y) for x in a.normalized for y in b.normalized)


def blind_outcome(field: catalog.CatalogField, pair: BlindPair) -> BlindOutcome | None:
    """The outcome of a pair, or None when its review came before the blind marking (such
    a review could not be blind to nothing, but it is not the test of the review)."""
    if pair.blind is None:
        return BlindOutcome.REVIEWED_ONLY if pair.reviewed is not None else None
    if pair.reviewed is None:
        return BlindOutcome.BLIND_ONLY
    if not pair.after_blind:
        return None
    return BlindOutcome.SAME if _same(field, pair.blind, pair.reviewed) else BlindOutcome.DIFFERS


@dataclass(frozen=True)
class BlindTotals:
    pairs: int  # counted pairs
    not_reviewed: int  # reviewed before the blind marking, not counted
    same: int
    differs: int
    blind_only: int
    reviewed_only: int
    confirmed_pairs: int  # compared pairs whose review confirmed a system value
    confirmed_differs: int  # … of them differing from the blind value

    def as_dict(self) -> dict[str, int]:
        return {
            "pairs": self.pairs, "not_reviewed": self.not_reviewed, "same": self.same,
            "differs": self.differs, "blind_only": self.blind_only,
            "reviewed_only": self.reviewed_only, "confirmed_pairs": self.confirmed_pairs,
            "confirmed_differs": self.confirmed_differs,
        }


def blind_totals(pairs: Sequence[BlindPair]) -> BlindTotals:
    counts = dict.fromkeys(BlindOutcome, 0)
    not_reviewed = confirmed = confirmed_differs = 0
    for pair in pairs:
        outcome = blind_outcome(catalog.field(pair.field), pair)
        if outcome is None:
            not_reviewed += 1
            continue
        counts[outcome] += 1
        if outcome in (BlindOutcome.SAME, BlindOutcome.DIFFERS) and (
            pair.path in SYSTEM_CONFIRMED_PATHS
        ):
            confirmed += 1
            confirmed_differs += outcome is BlindOutcome.DIFFERS
    return BlindTotals(
        sum(counts.values()), not_reviewed, counts[BlindOutcome.SAME],
        counts[BlindOutcome.DIFFERS], counts[BlindOutcome.BLIND_ONLY],
        counts[BlindOutcome.REVIEWED_ONLY], confirmed, confirmed_differs,
    )
