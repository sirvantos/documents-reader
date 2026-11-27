"""SC-002: every rule catches every error made for it, and none fires on a clean contract
(feature 06, T014). The contracts and scripted answers are those of `make_check_contracts`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts

# contract → the (field, rule, reason) violations it was made for; nothing else is violated
MADE_FOR: dict[str, set[tuple[str, str, str]]] = {
    "check-clean": set(),
    "check-rate10": set(),
    "check-words": {("amount_without_vat", "amount_words", "words_differ")},
    "check-vat": {("amount_without_vat", "vat_consistent", "vat_mismatch"),
                  ("amount_with_vat", "vat_consistent", "vat_mismatch")},
    "check-zero": {("amount_without_vat", "amount_positive", "not_positive"),
                   ("amount_with_vat", "amount_positive", "not_positive")},
    "check-date": {("contract_end_date", "end_date_range", "date_out_of_range")},
    "check-same": {("customer_name_short", "parties_differ", "same_parties"),
                   ("contractor_name_short", "parties_differ", "same_parties")},
    "check-noamount": {("amount_with_vat", "required", "required_missing")},
    "check-exempt": {("amount_with_vat", "required", "required_missing")},
}


@pytest.fixture
def checked(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    for name, doc in ids.items():
        use_model(ScriptedModel(CHECK_ANSWERS[name]))
        assert cli("extract", doc).exit_code == 0
    result = cli("check")
    assert result.exit_code == 0, result.stderr
    return ids


def _checks(db, doc: str, outcome: str) -> set[tuple[str, str, str]]:  # type: ignore[no-untyped-def]
    rows = db.execute(
        "SELECT field, rule, reason FROM field_check WHERE document_id = %s AND outcome = %s",
        (doc, outcome),
    ).fetchall()
    return {(f, r, why) for f, r, why in rows}


def test_each_rule_catches_its_errors_and_nothing_else(db, checked) -> None:  # type: ignore[no-untyped-def]
    for name, doc in checked.items():
        assert _checks(db, doc, "violated") == MADE_FOR[name], name


def test_every_rule_is_caught_somewhere(db, checked) -> None:  # type: ignore[no-untyped-def]
    caught = {rule for name in checked for _, rule, _ in MADE_FOR[name]}
    rules = {r for (r,) in db.execute("SELECT DISTINCT rule FROM field_check").fetchall()}
    # kind_valid cannot be caught end to end: extraction stores only normalized values
    assert rules - caught == {"kind_valid"}


def test_rate_written_in_the_text_is_used(db, checked) -> None:  # type: ignore[no-untyped-def]
    doc = checked["check-rate10"]
    assert ("amount_with_vat", "vat_consistent", None) in _checks(db, doc, "passed")


def test_exempt_contract_does_not_apply_the_vat_rule(db, checked) -> None:  # type: ignore[no-untyped-def]
    not_applied = _checks(db, checked["check-exempt"], "not_applied")
    assert ("amount_without_vat", "vat_consistent", "exempt") in not_applied
    assert ("amount_with_vat", "vat_consistent", "exempt") in not_applied
