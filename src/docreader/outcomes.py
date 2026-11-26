"""Outcomes of evaluation cases, totals and the comparison of records (feature 02).

Pure functions, no database (research R-7, R-12, R-13). The enums equal the CHECK
constraints of `0007_evaluation.sql`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

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


# --- comparison of two records (research R-13) ------------------------------------------------

NOT_FOUND_PLACE = "не найден"
EXCLUDED = "excluded"
_MISSING = "—"
# A smaller rank is better (principle IV: invented is worse than missed).
_FIELD_RANK = {Outcome.CORRECT: 0, Outcome.MISSED: 1, Outcome.WRONG: 2, Outcome.INVENTED: 3}
_BLIND_RANK = {
    BlindOutcome.SAME: 0, BlindOutcome.BLIND_ONLY: 1, BlindOutcome.REVIEWED_ONLY: 1,
    BlindOutcome.DIFFERS: 2,
}
_SEARCH = frozenset({EvalStage.SEARCH_PLAIN, EvalStage.SEARCH_RERANK})


@dataclass(frozen=True)
class StoredCase:
    """One `eval_case` row as the comparison needs it."""

    case_key: str
    outcome: str | None
    place: int | None
    gold_sha: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecordView:
    stage: EvalStage
    metrics: dict[str, Any]
    gold_version: str | None
    cases: dict[str, StoredCase]


@dataclass(frozen=True)
class CaseChange:
    case_key: str
    before: str
    after: str


@dataclass(frozen=True)
class Comparison:
    metrics: dict[str, tuple[float, float]]  # dotted key → (a, b), numeric leaves only
    better: list[CaseChange]
    worse: list[CaseChange]
    outside: list[CaseChange]  # to or from an unscored outcome, or in one record only
    by_gold: list[CaseChange]  # the gold value of the case changed between the records
    gold_differs: bool


def _numbers(data: Any, prefix: str = "") -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            out.update(_numbers(value, f"{prefix}{key}."))
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        out[prefix.rstrip(".")] = data
    return out


def _shown(stage: EvalStage, case: StoredCase | None) -> str:
    if case is None:
        return _MISSING
    if stage in _SEARCH:
        if EXCLUDED in case.flags:
            return "вне метрик"
        return str(case.place) if case.place is not None else NOT_FOUND_PLACE
    return case.outcome or _MISSING


def _rank(stage: EvalStage, case: StoredCase) -> int | None:
    """The rank of a case, or None when it is outside the comparison."""
    if stage in _SEARCH:
        if EXCLUDED in case.flags:
            return None
        return case.place if case.place is not None else 10**9
    if stage is EvalStage.GOLD_BLIND:
        try:
            return _BLIND_RANK[BlindOutcome(case.outcome or "")]
        except ValueError:
            return None
    try:
        return _FIELD_RANK.get(Outcome(case.outcome or ""))
    except ValueError:
        return None


def compare(a: RecordView, b: RecordView) -> Comparison:
    """Differences of two records of one stage; every changed case exactly once (SC-005)."""
    if a.stage is not b.stage:
        raise ValueError(f"записи разных этапов: {a.stage.value} и {b.stage.value}")
    na, nb = _numbers(a.metrics), _numbers(b.metrics)
    metrics = {k: (na[k], nb[k]) for k in sorted(na.keys() & nb.keys())}
    better: list[CaseChange] = []
    worse: list[CaseChange] = []
    outside: list[CaseChange] = []
    by_gold: list[CaseChange] = []
    for key in sorted(a.cases.keys() | b.cases.keys()):
        ca, cb = a.cases.get(key), b.cases.get(key)
        before, after = _shown(a.stage, ca), _shown(b.stage, cb)
        if ca is None or cb is None:
            outside.append(CaseChange(key, before, after))
            continue
        if before == after:
            continue
        change = CaseChange(key, before, after)
        if ca.gold_sha != cb.gold_sha:
            by_gold.append(change)
            continue
        ra, rb = _rank(a.stage, ca), _rank(b.stage, cb)
        if ra is None or rb is None or ra == rb:
            outside.append(change)
        elif rb < ra:
            better.append(change)
        else:
            worse.append(change)
    return Comparison(metrics, better, worse, outside, by_gold, a.gold_version != b.gold_version)
