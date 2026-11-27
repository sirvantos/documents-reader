"""Rule checks and field statuses of the six prototype fields (feature 06).

The schema of migration 0008 and its enums; the rules, statuses and commands come in the
tasks that follow (specs/010-rule-checks/research.md).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

import psycopg

from docreader import catalog, numwords, runs, stages, textnorm, values
from docreader.config import CheckSettings, Settings
from docreader.errors import UserError
from docreader.ids import parse_document_id
from docreader.stages import RunStage, Stage, State

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
SYSTEM_CHANGED = "system_changed"


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


# --- the command: load, check, store (research R-1, R-7, R-12) ------------------------------

AFTER_CHARS = 320
SKIP_NO_EXTRACTION = "no_extraction"


def _after(text: str, row: tuple) -> str:
    """Up to `AFTER_CHARS` of the clean text right after the value, inside its quote's reach."""
    value_text, quote_start, quote_end = row
    if not value_text or quote_start is None or quote_end is None:
        return ""
    spans = textnorm.locate(text[quote_start:quote_end], value_text)
    if not spans:
        return ""
    end = quote_start + spans[0][1]
    return text[end : end + AFTER_CHARS]


def load_document(conn: psycopg.Connection, doc_id: str) -> tuple[DocFields, int] | None:
    """The stored fields of a document and the id of the extraction run; None without them."""
    rows = conn.execute(
        "SELECT field, result, value_text, value_normalized, quote, quote_start, quote_end,"
        " run_id FROM field_value WHERE document_id = %s",
        (doc_id,),
    ).fetchall()
    if not rows:
        return None
    text_row = conn.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()
    text = text_row[0] if text_row else ""
    fields = {
        name: FieldRow(
            result, value_text, normalized, quote,
            _after(text, (value_text, q_start, q_end)),
        )
        for name, result, value_text, normalized, quote, q_start, q_end, _ in rows
    }
    return DocFields(fields, text), max(row[7] for row in rows)


def document_needs_review(conn: psycopg.Connection, doc_id: str) -> bool:
    """Reading or structure of the document is marked `needs_review`."""
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM stage_status WHERE document_id = %s"
        " AND stage = ANY(%s) AND state = %s)",
        (doc_id, [Stage.READING, Stage.STRUCTURE], State.NEEDS_REVIEW),
    ).fetchone()
    return bool(row and row[0])


def stored_status(conn: psycopg.Connection, doc_id: str) -> StoredStatus | None:
    """What the stored statuses were computed from; None when incomplete or inconsistent."""
    rows = conn.execute(
        "SELECT extraction_run_id, checks_version, settings_sha256, count(*)"
        " FROM field_status WHERE document_id = %s"
        " GROUP BY extraction_run_id, checks_version, settings_sha256",
        (doc_id,),
    ).fetchall()
    if len(rows) != 1 or rows[0][3] != len(FIELDS):
        return None
    return StoredStatus(rows[0][0], rows[0][1], rows[0][2])


@dataclass(frozen=True)
class CheckedDocument:
    document_id: str
    counts: dict[str, int]  # status -> number of fields, all four statuses present
    violated: list[str]  # sorted distinct rule codes violated in the document


@dataclass(frozen=True)
class SkippedCheck:
    document_id: str
    reason: str


@dataclass
class CheckReport:
    """Result of one `check` command (contracts/cli.md «docreader check»)."""

    run_id: int | None = None
    documents: list[CheckedDocument] = dataclass_field(default_factory=list)
    skipped: list[SkippedCheck] = dataclass_field(default_factory=list)

    @property
    def totals(self) -> dict:
        fields = {s.value: 0 for s in FieldStatus}
        for doc in self.documents:
            for status, n in doc.counts.items():
                fields[status] += n
        return {"checked": len(self.documents), "skipped": len(self.skipped), "fields": fields}

    def to_json(self) -> dict:
        entries: list[dict] = [
            {"document_id": d.document_id, "state": "checked", "reason": None,
             "counts": d.counts, "violated": d.violated}
            for d in self.documents
        ]
        entries += [
            {"document_id": s.document_id, "state": "skipped", "reason": s.reason,
             "counts": {}, "violated": []}
            for s in self.skipped
        ]
        entries.sort(key=lambda e: e["document_id"])
        return {
            "run_id": self.run_id,
            "checks_version": CHECKS_VERSION,
            "documents": entries,
            "totals": self.totals,
        }


def _candidates(
    conn: psycopg.Connection,
    settings: Settings,
    ids: Sequence[str] | None,
    *,
    all_: bool,
    again: bool,
) -> tuple[list[str], list[SkippedCheck]]:
    """Documents to check, in order, and the named ones that have no extraction."""
    with_values = {
        doc_id: run_id
        for doc_id, run_id in conn.execute(
            "SELECT document_id, max(run_id) FROM field_value GROUP BY document_id"
        )
    }
    if ids:
        chosen: list[str] = []
        skipped: list[SkippedCheck] = []
        for doc_id in dict.fromkeys(ids):
            if not conn.execute("SELECT 1 FROM document WHERE id = %s", (doc_id,)).fetchone():
                raise UserError(f"Документ {doc_id} не найден — список документов: docreader list")
            if doc_id in with_values:
                chosen.append(doc_id)
            else:
                skipped.append(SkippedCheck(doc_id, SKIP_NO_EXTRACTION))
        return chosen, skipped
    ordered = sorted(with_values, key=parse_document_id)
    if all_ or again:
        return ordered, []
    return [
        doc_id
        for doc_id in ordered
        if is_stale(
            stored_status(conn, doc_id),
            extraction_run_id=with_values[doc_id],
            settings=settings.checks,
        )
    ], []


def _store(
    conn: psycopg.Connection,
    settings: Settings,
    run_id: int,
    doc_id: str,
    extraction_run_id: int,
    evaluation: dict[str, FieldEvaluation],
) -> None:
    """Replace the checks, statuses and stage state of one document, all or nothing."""
    fingerprint = settings_fingerprint(settings.checks)
    check_rows = [
        (doc_id, name, code, check.outcome, check.reason, run_id)
        for name, ev in evaluation.items()
        for code, check in ev.checks.items()
    ]
    status_rows = [
        (doc_id, name, ev.status.status, list(ev.status.reasons), list(ev.status.flags),
         extraction_run_id, CHECKS_VERSION, fingerprint, run_id)
        for name, ev in evaluation.items()
    ]
    flagged = sum(
        1 for ev in evaluation.values()
        if ev.status.status in (FieldStatus.NEEDS_REVIEW, FieldStatus.REJECTED)
    )
    with conn.transaction():
        stages.lock(conn, doc_id, Stage.CHECKS)
        conn.execute("DELETE FROM field_check WHERE document_id = %s", (doc_id,))
        conn.execute("DELETE FROM field_status WHERE document_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO field_check (document_id, field, rule, outcome, reason, run_id)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                check_rows,
            )
            cur.executemany(
                "INSERT INTO field_status (document_id, field, status, reasons, flags,"
                " extraction_run_id, checks_version, settings_sha256, run_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                status_rows,
            )
        if flagged:
            stages.set_state(
                conn, doc_id, Stage.CHECKS, State.NEEDS_REVIEW,
                f"полей требует просмотра: {flagged}", run_id,
            )
        else:
            stages.set_state(conn, doc_id, Stage.CHECKS, State.DONE, None, run_id)


def run_checks(
    conn: psycopg.Connection,
    settings: Settings,
    ids: Sequence[str] | None,
    *,
    all_: bool,
    again: bool,
) -> CheckReport:
    """Check the chosen documents (contracts/cli.md «docreader check»)."""
    if all_ and ids:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    chosen, skipped = _candidates(conn, settings, ids, all_=all_, again=again)
    report = CheckReport(skipped=skipped)
    if not chosen:
        return report
    run_settings = {"checks": asdict(settings.checks), "checks_version": CHECKS_VERSION}
    run_id = runs.start_run(conn, RunStage.CHECKS, run_settings, None)
    report.run_id = run_id
    try:
        for doc_id in chosen:
            loaded = load_document(conn, doc_id)
            if loaded is None:  # the extraction vanished since the selection
                report.skipped.append(SkippedCheck(doc_id, SKIP_NO_EXTRACTION))
                continue
            doc, extraction_run_id = loaded
            evaluation = evaluate_document(
                doc, settings.checks,
                document_needs_review=document_needs_review(conn, doc_id),
            )
            _store(conn, settings, run_id, doc_id, extraction_run_id, evaluation)
            counts = Counter(ev.status.status.value for ev in evaluation.values())
            report.documents.append(CheckedDocument(
                doc_id,
                {s.value: counts.get(s.value, 0) for s in FieldStatus},
                sorted({
                    code for ev in evaluation.values()
                    for code, c in ev.checks.items() if c.outcome is RuleOutcome.VIOLATED
                }),
            ))
    finally:
        runs.finish_run(conn, run_id)
    return report


# --- the summary (research R-7, R-10) ------------------------------------------------------


def split_fresh(
    conn: psycopg.Connection, settings: Settings, doc_ids: Sequence[str]
) -> tuple[list[str], list[str]]:
    """Documents with extraction split into (checks up to date, checks stale)."""
    fresh: list[str] = []
    stale: list[str] = []
    for doc in doc_ids:
        loaded = load_document(conn, doc)
        if loaded is None:
            continue
        run_id = loaded[1]
        if is_stale(stored_status(conn, doc), extraction_run_id=run_id, settings=settings.checks):
            stale.append(doc)
        else:
            fresh.append(doc)
    return fresh, stale


def documents_with_extraction(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT document_id FROM field_value ORDER BY document_id")]


@dataclass(frozen=True)
class CheckSummary:
    """Counts only (no values): statuses per field and in total, decisions, stale documents."""

    documents: int
    stale: int
    fields: dict[str, dict[str, int]]
    total: dict[str, int]
    decisions: dict[str, int]
    system_changed: int

    def to_json(self) -> dict[str, object]:
        return {
            "checks_version": CHECKS_VERSION,
            "documents": self.documents,
            "stale": self.stale,
            "fields": self.fields,
            "total": self.total,
            "decisions": self.decisions,
            "system_changed": self.system_changed,
        }


def summarize(conn: psycopg.Connection, settings: Settings) -> CheckSummary:
    """Statuses of the fields of documents with up-to-date checks; stale ones are only counted."""
    docs = documents_with_extraction(conn)
    fresh, stale = split_fresh(conn, settings, docs)
    statuses = [s.value for s in FieldStatus]
    fields = {f: dict.fromkeys(statuses, 0) for f in FIELDS}
    changed = 0
    for field, status, flags in conn.execute(
        "SELECT field, status, flags FROM field_status WHERE document_id = ANY(%s)", (fresh,)
    ):
        fields[field][status] += 1
        changed += SYSTEM_CHANGED in flags
    total = {s: sum(f[s] for f in fields.values()) for s in statuses}
    decisions = dict.fromkeys((k.value for k in DecisionKind), 0)
    for kind, n in conn.execute("SELECT kind, count(*) FROM field_decision GROUP BY kind"):
        decisions[kind] = n
    return CheckSummary(len(docs), len(stale), fields, total, decisions, changed)
