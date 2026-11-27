"""Rule checks and field statuses of the six prototype fields (feature 06).

The schema of migration 0008 and its enums; the rules, statuses and commands come in the
tasks that follow (specs/010-rule-checks/research.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from docreader import catalog, numwords, values
from docreader.config import CheckSettings

# Changes with any change of a rule or of the status table (research R-2).
CHECKS_VERSION = "06.1"


class RuleOutcome(StrEnum):
    """The outcome of one rule on one field."""

    PASSED = "passed"
    VIOLATED = "violated"
    NOT_APPLIED = "not_applied"


class FieldStatus(StrEnum):
    """The status of a field (research R-6)."""

    ACCEPTED = "accepted"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    NOT_FOUND = "not_found"


class DecisionKind(StrEnum):
    """The analyst's decision on a queue card (research R-9)."""

    CONFIRM = "confirm"
    CORRECT = "correct"
    ABSENT = "absent"


@dataclass(frozen=True)
class FieldRow:
    """One extracted field of a contract as the rules see it."""

    result: str  # found / not_found / rejected / failed
    value_text: str | None
    value_normalized: str | None
    quote: str | None
    after: str  # the text right after the value


@dataclass(frozen=True)
class DocFields:
    """The six prototype fields of a contract (by field name) and its clean text."""

    rows: dict[str, FieldRow]
    text: str


@dataclass(frozen=True)
class RuleCheck:
    """The outcome of a rule on one field and its reason (None when passed)."""

    outcome: RuleOutcome
    reason: str | None


@dataclass(frozen=True)
class Rule:
    """A rule: its code, the fields it covers and the function that runs it."""

    code: str
    fields: tuple[str, ...]
    fn: Callable[[DocFields, CheckSettings], dict[str, RuleCheck]]


_PASSED = RuleCheck(RuleOutcome.PASSED, None)
_AMOUNTS = ("amount_without_vat", "amount_with_vat")
_PARTIES = ("customer_name_short", "contractor_name_short")
_REQUIRED = (
    "contract_number", "customer_name_short", "contractor_name_short",
    "amount_without_vat", "amount_with_vat",
)
_ALL = (*_REQUIRED, "contract_end_date")


def _present(row: FieldRow) -> str | None:
    """The normalized value of a found field, None when there is no value to check."""
    if row.result == "found" and row.value_normalized is not None:
        return row.value_normalized
    return None


def _no_value() -> RuleCheck:
    return RuleCheck(RuleOutcome.NOT_APPLIED, "no_value")


def _required(doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    return {
        name: RuleCheck(RuleOutcome.VIOLATED, "required_missing")
        if doc.rows[name].result == "not_found" else _PASSED
        for name in _REQUIRED
    }


def _kind_valid(doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    out: dict[str, RuleCheck] = {}
    for name in _ALL:
        value = _present(doc.rows[name])
        if value is None:
            out[name] = _no_value()
            continue
        try:
            values.normalize_field(catalog.field(name), value)
        except ValueError:
            out[name] = RuleCheck(RuleOutcome.VIOLATED, "kind_invalid")
        else:
            out[name] = _PASSED
    return out


def _amount_positive(doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    out: dict[str, RuleCheck] = {}
    for name in _AMOUNTS:
        value = _present(doc.rows[name])
        if value is None:
            out[name] = _no_value()
        elif Decimal(value) <= 0:
            out[name] = RuleCheck(RuleOutcome.VIOLATED, "not_positive")
        else:
            out[name] = _PASSED
    return out


def _amount_words(doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    """The words in brackets with the amount spell its roubles (research R-3)."""
    out: dict[str, RuleCheck] = {}
    for name in _AMOUNTS:
        row = doc.rows[name]
        value = _present(row)
        if value is None:
            out[name] = _no_value()
            continue
        words = numwords.words_of_amount(row.value_text or "", row.after)
        if words is None:
            out[name] = RuleCheck(RuleOutcome.NOT_APPLIED, "no_words")
            continue
        number = numwords.words_to_int(words)
        if number is None:
            out[name] = RuleCheck(RuleOutcome.VIOLATED, "words_unreadable")
        elif number != int(Decimal(value)):
            out[name] = RuleCheck(RuleOutcome.VIOLATED, "words_differ")
        else:
            out[name] = _PASSED
    return out


_RATE = re.compile(r"НДС\W{0,3}(\d{1,2}(?:[.,]\d+)?)\s*%", re.IGNORECASE)
_EXEMPT = re.compile(r"не\s+облага", re.IGNORECASE)
_KOPECK = Decimal("0.01")


def _vat_consistent(doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    """With VAT = without VAT × (1 + rate), rounded half up to the kopeck (research R-4).

    The rate is the first one written in the quotes of the two amounts, else
    `[checks] vat_rate`; «не облагается» in the text wins over a missing amount.
    """
    if _EXEMPT.search(doc.text):
        return dict.fromkeys(_AMOUNTS, RuleCheck(RuleOutcome.NOT_APPLIED, "exempt"))
    without, with_vat = (_present(doc.rows[name]) for name in _AMOUNTS)
    if without is None or with_vat is None:
        return dict.fromkeys(_AMOUNTS, RuleCheck(RuleOutcome.NOT_APPLIED, "one_amount"))
    quotes = " ".join(doc.rows[name].quote or "" for name in _AMOUNTS)
    m = _RATE.search(quotes)
    rate = Decimal(m.group(1).replace(",", ".")) if m else Decimal(str(settings.vat_rate))
    expected = (Decimal(without) * (1 + rate / 100)).quantize(_KOPECK, rounding=ROUND_HALF_UP)
    if expected != Decimal(with_vat):
        return dict.fromkeys(_AMOUNTS, RuleCheck(RuleOutcome.VIOLATED, "vat_mismatch"))
    return dict.fromkeys(_AMOUNTS, _PASSED)


def _parties_differ(doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    a, b = (_present(doc.rows[name]) for name in _PARTIES)
    if a is None or b is None:
        return dict.fromkeys(_PARTIES, RuleCheck(RuleOutcome.NOT_APPLIED, "one_party"))
    if values.same_value(catalog.field("customer_name_short"), a, b):
        return dict.fromkeys(_PARTIES, RuleCheck(RuleOutcome.VIOLATED, "same_parties"))
    return dict.fromkeys(_PARTIES, _PASSED)


def _end_date_range(doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    value = _present(doc.rows["contract_end_date"])
    if value is None:
        return {"contract_end_date": _no_value()}
    low = date.fromisoformat(settings.end_date_min)
    high = date.fromisoformat(settings.end_date_max)
    if not low <= date.fromisoformat(value) <= high:
        return {"contract_end_date": RuleCheck(RuleOutcome.VIOLATED, "date_out_of_range")}
    return {"contract_end_date": _PASSED}


RULES: tuple[Rule, ...] = (
    Rule("required", _REQUIRED, _required),
    Rule("kind_valid", _ALL, _kind_valid),
    Rule("amount_positive", _AMOUNTS, _amount_positive),
    Rule("amount_words", _AMOUNTS, _amount_words),
    Rule("vat_consistent", _AMOUNTS, _vat_consistent),
    Rule("parties_differ", _PARTIES, _parties_differ),
    Rule("end_date_range", ("contract_end_date",), _end_date_range),
)


def apply(code: str, doc: DocFields, settings: CheckSettings) -> dict[str, RuleCheck]:
    """Run the rule `code` on a contract; KeyError for an unknown code."""
    for rule in RULES:
        if rule.code == code:
            return rule.fn(doc, settings)
    raise KeyError(code)


# --- the status of a field (research R-6) -------------------------------------------------

FIELDS = _ALL
DOCUMENT_NEEDS_REVIEW = "document_needs_review"


@dataclass(frozen=True)
class Status:
    """A field's status, its reasons (`rule:code` or `extraction:result`) and flags."""

    status: FieldStatus
    reasons: tuple[str, ...]
    flags: tuple[str, ...]


@dataclass(frozen=True)
class FieldEvaluation:
    status: Status
    checks: dict[str, RuleCheck]


def _rules_of(field: str) -> tuple[Rule, ...]:
    return tuple(r for r in RULES if field in r.fields)


def evaluate_document(
    doc: DocFields, settings: CheckSettings, *, document_needs_review: bool = False
) -> dict[str, FieldEvaluation]:
    """Every rule on every field and the status of each field (rows 3–7 of research R-6).

    A rejected or failed field is not checked: its rules are `not_applied` with that
    result as the reason (FR-002) and its status follows the extraction (FR-004).
    """
    outcomes: dict[str, dict[str, RuleCheck]] = {f: {} for f in FIELDS}
    for rule in RULES:
        for field, check in rule.fn(doc, settings).items():
            outcomes[field][rule.code] = check
    flags = (DOCUMENT_NEEDS_REVIEW,) if document_needs_review else ()
    out: dict[str, FieldEvaluation] = {}
    for field in FIELDS:
        result = doc.rows[field].result
        if result in ("rejected", "failed"):
            checks = {r.code: RuleCheck(RuleOutcome.NOT_APPLIED, result) for r in _rules_of(field)}
            status = FieldStatus.REJECTED if result == "rejected" else FieldStatus.NEEDS_REVIEW
            out[field] = FieldEvaluation(Status(status, (f"extraction:{result}",), flags), checks)
            continue
        checks = outcomes[field]
        violated = tuple(
            f"{code}:{c.reason}" for code, c in checks.items()
            if c.outcome is RuleOutcome.VIOLATED
        )
        if violated:
            status = FieldStatus.NEEDS_REVIEW
        elif result == "not_found":
            status = FieldStatus.NOT_FOUND
        else:
            status = FieldStatus.ACCEPTED
        out[field] = FieldEvaluation(Status(status, violated, flags), checks)
    return out


# --- staleness (research R-7) --------------------------------------------------------------


@dataclass(frozen=True)
class StoredStatus:
    """What a stored status was computed from."""

    extraction_run_id: int
    checks_version: str
    settings_sha256: str


def settings_fingerprint(settings: CheckSettings) -> str:
    """SHA-256 of the canonical JSON of `[checks]`: a change of a setting makes checks stale."""
    data = json.dumps(asdict(settings), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def is_stale(
    stored: StoredStatus | None, *, extraction_run_id: int, settings: CheckSettings
) -> bool:
    """No checks yet, or computed from another extraction, rules version or settings."""
    return stored is None or (
        stored.extraction_run_id != extraction_run_id
        or stored.checks_version != CHECKS_VERSION
        or stored.settings_sha256 != settings_fingerprint(settings)
    )
