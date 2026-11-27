"""Migration 0008_checks: rule checks, field statuses and analyst decisions (feature 06, T001).

data-model.md of specs/010-rule-checks: three tables; CHECK constraints equal the enums of
`checks.py` and `outcomes.py`; the rows follow their document (ON DELETE CASCADE).
"""

from __future__ import annotations

from enum import StrEnum

import psycopg
import pytest

from docreader.checks import DecisionKind, FieldStatus, RuleOutcome
from docreader.outcomes import BlindOutcome, CheckOutcome, EvalStage, Outcome
from tests.integration.test_migration_0007 import _check_values, _columns, _document

TABLES = {
    "field_check": {"document_id", "field", "rule", "outcome", "reason", "run_id"},
    "field_status": {
        "document_id", "field", "status", "reasons", "flags", "extraction_run_id",
        "checks_version", "settings_sha256", "run_id",
    },
    "field_decision": {
        "document_id", "field", "kind", "value_text", "value_normalized", "clause_key",
        "system_result", "system_normalized", "answers_sha256", "decided_at",
    },
}
FIELDS = {
    "contract_number", "customer_name_short", "contractor_name_short",
    "amount_without_vat", "amount_with_vat", "contract_end_date",
}
SHA = "b" * 64


def _run(db: psycopg.Connection) -> int:
    return db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('checks', 't', '{}') RETURNING id"
    ).fetchone()[0]


def _status(db: psycopg.Connection, doc: str, run: int, **over: object) -> None:
    row: dict[str, object] = {"field": "contract_number", "status": "accepted"}
    row.update(over)
    db.execute(
        "INSERT INTO field_status (document_id, field, status, reasons, flags, "
        "extraction_run_id, checks_version, settings_sha256, run_id) "
        "VALUES (%s, %s, %s, '{}', '{}', %s, '06.1', %s, %s)",
        (doc, row["field"], row["status"], run, SHA, run),
    )


def _decision(db: psycopg.Connection, doc: str, **over: object) -> None:
    row: dict[str, object] = {
        "field": "amount_with_vat", "kind": "correct", "value_text": "1 000,00",
        "value_normalized": "1000.00",
    }
    row.update(over)
    db.execute(
        "INSERT INTO field_decision (document_id, field, kind, value_text, value_normalized, "
        "system_result, system_normalized, answers_sha256) "
        "VALUES (%s, %s, %s, %s, %s, 'found', '900.00', %s)",
        (doc, row["field"], row["kind"], row["value_text"], row["value_normalized"], SHA),
    )


def test_tables_and_columns(db: psycopg.Connection) -> None:
    applied = {r[0] for r in db.execute("SELECT version FROM schema_migrations").fetchall()}
    assert {"0007_evaluation", "0008_checks"} <= applied
    for table, columns in TABLES.items():
        assert _columns(db, table) == columns, table


@pytest.mark.parametrize(
    ("table", "column", "enum"),
    [
        ("field_check", "outcome", RuleOutcome),
        ("field_status", "status", FieldStatus),
        ("field_decision", "kind", DecisionKind),
        ("eval_result", "stage", EvalStage),
    ],
)
def test_checks_equal_enums(
    db: psycopg.Connection, table: str, column: str, enum: type[StrEnum]
) -> None:
    assert _check_values(db, table, column) == {e.value for e in enum}


def test_eval_stage_has_checks() -> None:
    assert EvalStage.CHECKS.value == "checks"


def test_case_outcomes_are_feature_02_plus_check_outcomes(db: psycopg.Connection) -> None:
    expected = {e.value for e in (*Outcome, *BlindOutcome, *CheckOutcome)}
    assert _check_values(db, "eval_case", "outcome") == expected
    assert {e.value for e in CheckOutcome} == {
        "queued_wrong", "queued_right", "accepted_wrong", "accepted_right",
    }


@pytest.mark.parametrize("table", ["field_check", "field_status", "field_decision"])
def test_field_is_one_of_the_six(db: psycopg.Connection, table: str) -> None:
    assert _check_values(db, table, "field") == FIELDS


def test_correct_needs_its_value(db: psycopg.Connection) -> None:
    doc = _document(db)
    _decision(db, doc)
    _decision(db, doc, field="contract_end_date", kind="absent", value_text=None,
              value_normalized=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        _decision(db, doc, field="contract_number", value_normalized=None)
    with pytest.raises(psycopg.errors.CheckViolation):
        _decision(db, doc, field="customer_name_short", kind="confirm")


def test_rows_follow_their_document(db: psycopg.Connection) -> None:
    doc = _document(db)
    run = _run(db)
    _status(db, doc, run)
    db.execute(
        "INSERT INTO field_check (document_id, field, rule, outcome, reason, run_id) "
        "VALUES (%s, 'contract_number', 'required', 'passed', NULL, %s)",
        (doc, run),
    )
    _decision(db, doc)

    db.execute("DELETE FROM document WHERE id = %s", (doc,))

    for table in TABLES:
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_bad_values_are_refused(db: psycopg.Connection) -> None:
    doc = _document(db)
    run = _run(db)
    with pytest.raises(psycopg.errors.CheckViolation):
        _status(db, doc, run, status="maybe")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO field_status (document_id, field, status, reasons, flags, "
            "extraction_run_id, checks_version, settings_sha256, run_id) "
            "VALUES (%s, 'contract_number', 'accepted', '{}', '{}', %s, '06.1', 'short', %s)",
            (doc, run, run),
        )
