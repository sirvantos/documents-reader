"""`docreader check` on the synthetic contracts with injected errors (feature 06, T012).

The nine contracts of `make_check_contracts` go through add, read, parse and `extract` with
their scripted answers, then `check`. `--json` of `check` (contracts/cli.md):
{"run_id", "checks_version", "documents": [{"document_id", "state": "checked"|"skipped",
"reason": null|"no_extraction", "counts": {status: n}, "violated": [rule, …]}],
"totals": {"checked", "skipped", "fields": {status: n}}}.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.check_guard import assert_check_output_clean
from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts

STATUSES = ("accepted", "needs_review", "rejected", "not_found")

# (field, status, reasons) of every field that is not «accepted»; all others are accepted
EXPECTED: dict[str, set[tuple[str, str, tuple[str, ...]]]] = {
    "check-clean": set(),
    "check-rate10": set(),
    "check-words": {("amount_without_vat", "needs_review", ("amount_words:words_differ",))},
    "check-vat": {
        ("amount_without_vat", "needs_review", ("vat_consistent:vat_mismatch",)),
        ("amount_with_vat", "needs_review", ("vat_consistent:vat_mismatch",)),
    },
    "check-exempt": {("amount_with_vat", "needs_review", ("required:required_missing",))},
    "check-zero": {
        ("amount_without_vat", "needs_review", ("amount_positive:not_positive",)),
        ("amount_with_vat", "needs_review", ("amount_positive:not_positive",)),
    },
    "check-date": {("contract_end_date", "needs_review", ("end_date_range:date_out_of_range",))},
    "check-same": {
        ("customer_name_short", "needs_review", ("parties_differ:same_parties",)),
        ("contractor_name_short", "needs_review", ("parties_differ:same_parties",)),
    },
    "check-noamount": {("amount_with_vat", "needs_review", ("required:required_missing",))},
}


def _extract(cli, use_model, doc: str, name: str) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(CHECK_ANSWERS[name]))
    result = cli("extract", doc)
    assert result.exit_code == 0, result.stderr


@pytest.fixture
def docs(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    for name, doc in ids.items():
        _extract(cli, use_model, doc, name)
    return ids


def _statuses(db, doc: str) -> dict[str, tuple[str, tuple[str, ...]]]:  # type: ignore[no-untyped-def]
    rows = db.execute(
        "SELECT field, status, reasons FROM field_status WHERE document_id = %s", (doc,)
    ).fetchall()
    return {f: (s, tuple(sorted(r))) for f, s, r in rows}


def _check_json(cli, *args: str) -> dict:  # type: ignore[no-untyped-def]
    result = cli("check", *args, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_every_field_gets_one_status_and_the_expected_rules(cli, db, docs) -> None:  # type: ignore[no-untyped-def]
    report = _check_json(cli)
    assert report["checks_version"] == "06.1"
    assert report["totals"]["checked"] == len(docs) and report["totals"]["skipped"] == 0
    assert sum(report["totals"]["fields"].values()) == 6 * len(docs)
    for name, doc in docs.items():
        statuses = _statuses(db, doc)
        assert len(statuses) == 6, name  # SC-001
        not_accepted = {(f, s, r) for f, (s, r) in statuses.items() if s != "accepted"}
        assert not_accepted == EXPECTED[name], name
    entry = next(d for d in report["documents"] if d["document_id"] == docs["check-vat"])
    assert entry["state"] == "checked" and entry["counts"]["needs_review"] == 2
    assert entry["violated"] == ["vat_consistent"]


def test_rule_outcomes_are_stored_for_every_rule(cli, db, docs) -> None:  # type: ignore[no-untyped-def]
    _check_json(cli)
    rows = db.execute(
        "SELECT field, rule, outcome, reason FROM field_check WHERE document_id = %s",
        (docs["check-exempt"],),
    ).fetchall()
    by = {(f, r): (o, why) for f, r, o, why in rows}
    assert by[("amount_without_vat", "vat_consistent")] == ("not_applied", "exempt")
    assert by[("contract_number", "required")] == ("passed", None)
    assert len({r for _, r in by}) == 7


def test_second_run_has_nothing_to_do_and_again_gives_the_same(cli, db, docs) -> None:  # type: ignore[no-untyped-def]
    _check_json(cli)
    before = {doc: _statuses(db, doc) for doc in docs.values()}
    again = _check_json(cli)
    assert again["totals"]["checked"] == 0 and again["documents"] == []
    forced = _check_json(cli, "--again")
    assert forced["totals"]["checked"] == len(docs)
    assert {doc: _statuses(db, doc) for doc in docs.values()} == before  # SC-005


def test_a_new_extraction_rechecks_only_that_document(cli, db, docs, use_model) -> None:  # type: ignore[no-untyped-def]
    _check_json(cli)
    _extract(cli, use_model, docs["check-words"], "check-words")
    report = _check_json(cli)
    assert [d["document_id"] for d in report["documents"]] == [docs["check-words"]]
    run = db.execute(
        "SELECT DISTINCT s.extraction_run_id = v.run_id FROM field_status s JOIN field_value v "
        "USING (document_id, field) WHERE document_id = %s",
        (docs["check-words"],),
    ).fetchall()
    assert run == [(True,)]


def test_named_documents_and_all(cli, db, docs) -> None:  # type: ignore[no-untyped-def]
    report = _check_json(cli, docs["check-clean"])
    assert [d["document_id"] for d in report["documents"]] == [docs["check-clean"]]
    report = _check_json(cli, "--all")
    assert report["totals"]["checked"] == len(docs)


def test_a_document_without_extraction_is_skipped(cli, db, use_model, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    _extract(cli, use_model, ids["check-clean"], "check-clean")
    report = _check_json(cli, ids["check-clean"], ids["check-words"])
    states = {d["document_id"]: (d["state"], d["reason"]) for d in report["documents"]}
    assert states == {ids["check-clean"]: ("checked", None),
                      ids["check-words"]: ("skipped", "no_extraction")}
    text = cli("check", ids["check-words"]).stdout
    assert "docreader extract" in text


def test_stage_status_and_field_value_untouched(cli, db, docs) -> None:  # type: ignore[no-untyped-def]
    before = db.execute("SELECT * FROM field_value ORDER BY document_id, field").fetchall()
    _check_json(cli)
    after = db.execute("SELECT * FROM field_value ORDER BY document_id, field").fetchall()
    assert before == after
    states = dict(db.execute(
        "SELECT document_id, state FROM stage_status WHERE stage = 'checks'"
    ).fetchall())
    assert states[docs["check-clean"]] == "done"
    assert states[docs["check-words"]] == "needs_review"
    run_stage = db.execute(
        "SELECT r.stage FROM field_status s JOIN run r ON r.id = s.run_id LIMIT 1"
    ).fetchone()[0]
    assert run_stage == "checks"


def test_text_output_is_clean(cli, db, docs) -> None:  # type: ignore[no-untyped-def]
    result = cli("check")
    assert result.exit_code == 0, result.stderr
    assert "Итого: проверено 9" in result.stdout
    assert "правила 06.1" in result.stdout
    assert_check_output_clean(db, result.stdout + result.stderr)
    assert_check_output_clean(db, cli("check", "--again", "--json").stdout)
