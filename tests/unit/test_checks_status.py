"""The status of a field and the staleness of checks (feature 06, T011; decisions — T018).

Interface (research R-6, R-7):
- `checks.evaluate_document(doc, settings, *, document_needs_review=False)` →
  `{field: FieldEvaluation(status: Status, checks: {rule: RuleCheck})}` for the six fields;
- `Status(status: FieldStatus, reasons: tuple[str, ...], flags: tuple[str, ...])`;
  a reason is `"<rule>:<code>"` for a violated rule, `"extraction:rejected"` or
  `"extraction:failed"` for an extraction outcome;
- `checks.settings_fingerprint(settings)` — SHA-256 of the canonical JSON of `[checks]`;
- `checks.is_stale(stored, *, extraction_run_id, settings)` — `stored` has
  `extraction_run_id`, `checks_version`, `settings_sha256`; None means no checks yet.
"""

from __future__ import annotations

from dataclasses import replace

from docreader.checks import (
    CHECKS_VERSION,
    RULES,
    FieldStatus,
    RuleCheck,
    RuleOutcome,
    StoredStatus,
    evaluate_document,
    is_stale,
    settings_fingerprint,
)
from docreader.config import CheckSettings
from tests.unit.test_checks_rules import NOT_FOUND, doc, found

SETTINGS = CheckSettings()
ACCEPTED, NEEDS_REVIEW = FieldStatus.ACCEPTED, FieldStatus.NEEDS_REVIEW
REJECTED, NOT_FOUND_STATUS = FieldStatus.REJECTED, FieldStatus.NOT_FOUND


def evaluate(d=None, **kw):  # type: ignore[no-untyped-def]
    return evaluate_document(d or doc(), SETTINGS, **kw)


def test_every_field_gets_one_status_and_every_rule_of_it() -> None:
    got = evaluate()
    assert set(got) == {"contract_number", "customer_name_short", "contractor_name_short",
                        "amount_without_vat", "amount_with_vat", "contract_end_date"}
    for field, item in got.items():
        assert item.status.status is ACCEPTED, field
        assert item.status.reasons == () and item.status.flags == ()
        expected = {r.code for r in RULES if field in r.fields}
        assert set(item.checks) == expected, field


def test_violated_rules_give_needs_review_with_all_reasons() -> None:
    wrong = found("1 250 000 (один миллион сто тысяч) рублей", "1250000.00")
    got = evaluate(doc(amount_with_vat=wrong))
    status = got["amount_with_vat"].status
    assert status.status is NEEDS_REVIEW
    assert set(status.reasons) == {"amount_words:words_differ", "vat_consistent:vat_mismatch"}
    # the other amount fails the VAT rule too (both fields of a pair rule)
    assert got["amount_without_vat"].status.reasons == ("vat_consistent:vat_mismatch",)


def test_rejected_is_rejected_and_its_rules_are_not_applied() -> None:
    rejected = replace(NOT_FOUND, result="rejected")
    item = evaluate(doc(amount_with_vat=rejected))["amount_with_vat"]
    assert item.status.status is REJECTED
    assert item.status.reasons == ("extraction:rejected",)
    assert all(c == RuleCheck(RuleOutcome.NOT_APPLIED, "rejected") for c in item.checks.values())


def test_failed_needs_review_with_the_extraction_reason() -> None:
    failed = replace(NOT_FOUND, result="failed")
    item = evaluate(doc(contract_number=failed))["contract_number"]
    assert item.status.status is NEEDS_REVIEW
    assert item.status.reasons == ("extraction:failed",)
    assert all(c == RuleCheck(RuleOutcome.NOT_APPLIED, "failed") for c in item.checks.values())


def test_not_found_end_date_is_not_found() -> None:
    item = evaluate(doc(contract_end_date=NOT_FOUND))["contract_end_date"]
    assert item.status.status is NOT_FOUND_STATUS
    assert item.status.reasons == ()


def test_not_found_required_field_needs_review() -> None:
    item = evaluate(doc(contract_number=NOT_FOUND))["contract_number"]
    assert item.status.status is NEEDS_REVIEW
    assert item.status.reasons == ("required:required_missing",)


def test_document_needs_review_is_a_flag_not_a_status() -> None:
    got = evaluate(document_needs_review=True)
    assert all(i.status.status is ACCEPTED for i in got.values())
    assert all(i.status.flags == ("document_needs_review",) for i in got.values())


def test_same_data_same_statuses() -> None:
    assert evaluate() == evaluate()


# --- staleness (research R-7, analyze U2) ---------------------------------------------------


def _stored(**over: object) -> StoredStatus:
    base = {"extraction_run_id": 7, "checks_version": CHECKS_VERSION,
            "settings_sha256": settings_fingerprint(SETTINGS)}
    base.update(over)
    return StoredStatus(**base)  # type: ignore[arg-type]


def test_fresh_checks_are_not_stale() -> None:
    assert not is_stale(_stored(), extraction_run_id=7, settings=SETTINGS)


def test_no_checks_is_stale() -> None:
    assert is_stale(None, extraction_run_id=7, settings=SETTINGS)


def test_new_extraction_rules_or_settings_make_checks_stale() -> None:
    assert is_stale(_stored(), extraction_run_id=8, settings=SETTINGS)
    assert is_stale(_stored(checks_version="06.0"), extraction_run_id=7, settings=SETTINGS)
    assert is_stale(_stored(), extraction_run_id=7, settings=CheckSettings(vat_rate=18.0))


def test_fingerprint_is_stable_and_follows_every_key() -> None:
    a = settings_fingerprint(SETTINGS)
    assert a == settings_fingerprint(CheckSettings())
    assert len(a) == 64
    assert a != settings_fingerprint(CheckSettings(end_date_max="2041-12-31"))
    assert a != settings_fingerprint(CheckSettings(end_date_min="2016-01-01"))
