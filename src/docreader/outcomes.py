"""Outcomes of evaluation cases, totals and the comparison of records (feature 02).

Pure functions, no database (research R-7, R-12, R-13). The enums equal the CHECK
constraints of `0007_evaluation.sql`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from docreader import catalog
from docreader.gold import GoldState
from docreader.values import same_value


class Outcome(StrEnum):
    """The outcome of one pair «document, field» (research R-7)."""

    CORRECT = "correct"
    WRONG = "wrong"
    MISSED = "missed"
    INVENTED = "invented"
    UNLABELED = "unlabeled"
    NO_RESULT = "no_result"
    MANUAL = "manual"


class BlindOutcome(StrEnum):
    """A blind value against the reviewed one (research R-10)."""

    SAME = "same"
    DIFFERS = "differs"
    BLIND_ONLY = "blind_only"
    REVIEWED_ONLY = "reviewed_only"


class EvalStage(StrEnum):
    """What a record of the results table compared."""

    FIELDS = "fields"
    RULES = "rules"
    SEARCH_PLAIN = "search_plain"
    SEARCH_RERANK = "search_rerank"
    GOLD_BLIND = "gold_blind"


# --- the pair outcome (research R-7) -------------------------------------------------------

# Flags of a case: why there is no result, or a rejected system value.
REJECTED = "rejected"
NOT_RUN = "not_run"
FAILED = "failed"
STALE = "stale"
NOT_EXTRACTED = "not_extracted"

SCORED: tuple[Outcome, ...] = (Outcome.CORRECT, Outcome.WRONG, Outcome.MISSED, Outcome.INVENTED)


@dataclass(frozen=True)
class GoldValue:
    """A marked gold pair: a value with its normalized variants, or absent."""

    state: GoldState
    normalized: tuple[str, ...]


@dataclass(frozen=True)
class SystemValue:
    """What a stage gave for a pair: `found` (with its normalized value), `not_found`,
    `rejected` or `failed`; `stale` — the result was obtained on another text."""

    result: str
    normalized: str | None
    stale: bool = False


@dataclass(frozen=True)
class CaseOutcome:
    outcome: Outcome
    flags: tuple[str, ...] = ()


def field_outcome(
    field_: catalog.CatalogField,
    gold: GoldValue | None,
    system: SystemValue | None,
    *,
    extracted: bool,
) -> CaseOutcome:
    """The outcome of one pair by the table of research R-7, top row first."""
    if not catalog.auto_compared(field_):
        return CaseOutcome(Outcome.MANUAL)
    if gold is None:
        return CaseOutcome(Outcome.UNLABELED)
    if not extracted:
        return CaseOutcome(Outcome.NO_RESULT, (NOT_EXTRACTED,))
    if system is None:
        return CaseOutcome(Outcome.NO_RESULT, (NOT_RUN,))
    if system.result == "failed":
        return CaseOutcome(Outcome.NO_RESULT, (FAILED,))
    if system.stale:
        return CaseOutcome(Outcome.NO_RESULT, (STALE,))
    flags = (REJECTED,) if system.result == "rejected" else ()
    given = system.result == "found" and system.normalized is not None
    if gold.state is GoldState.ABSENT:
        return CaseOutcome(Outcome.INVENTED) if given else CaseOutcome(Outcome.CORRECT, flags)
    if not given:
        return CaseOutcome(Outcome.MISSED, flags)
    assert system.normalized is not None
    if any(same_value(field_, variant, system.normalized) for variant in gold.normalized):
        return CaseOutcome(Outcome.CORRECT)
    return CaseOutcome(Outcome.WRONG)


# --- totals -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldCase:
    """One pair with its outcome; `extracted` — the stage extracts this field at all."""

    document_id: str
    field: str
    outcome: CaseOutcome
    extracted: bool = True


@dataclass(frozen=True)
class OutcomeCounts:
    counts: dict[Outcome, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def scored(self) -> int:
        """Marked pairs with a result: the denominator of the shares."""
        return sum(self.counts[o] for o in SCORED)

    def share(self, outcome: Outcome) -> float | None:
        return self.counts[outcome] / self.scored if self.scored else None


def _count(cases: Sequence[FieldCase]) -> OutcomeCounts:
    counts = dict.fromkeys(Outcome, 0)
    for c in cases:
        counts[c.outcome.outcome] += 1
    return OutcomeCounts(counts)


@dataclass(frozen=True)
class FieldTotals:
    field: str
    counts: OutcomeCounts


@dataclass(frozen=True)
class Totals:
    overall: OutcomeCounts
    fields: list[FieldTotals] = field(default_factory=list)  # extracted, worst first
    not_extracted: list[FieldTotals] = field(default_factory=list)  # catalog order


def _catalog_index(name: str) -> int:
    order = {f.name: i for i, f in enumerate(catalog.CATALOG)}
    return order.get(name, len(order))


def totals(cases: Sequence[FieldCase]) -> Totals:
    """Counts per field and overall; the sum equals the number of pairs (SC-002)."""
    by_field: dict[str, list[FieldCase]] = {}
    for c in cases:
        by_field.setdefault(c.field, []).append(c)
    extracted: list[FieldTotals] = []
    other: list[FieldTotals] = []
    for name, group in by_field.items():
        item = FieldTotals(name, _count(group))
        (extracted if all(c.extracted for c in group) else other).append(item)

    def worst_first(t: FieldTotals) -> tuple[int, float, int, int]:
        share = t.counts.share(Outcome.CORRECT)
        return (
            share is None,
            share if share is not None else 0.0,
            -t.counts.counts[Outcome.INVENTED],
            _catalog_index(t.field),
        )

    extracted.sort(key=worst_first)
    other.sort(key=lambda t: _catalog_index(t.field))
    return Totals(_count(cases), extracted, other)
