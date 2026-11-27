"""Migration 0007_evaluation: the gold set and the results table (feature 02, T001).

data-model.md of specs/009-evaluation-set: seven tables; CHECK constraints equal the
enums of `gold.py`, `outcomes.py` and `questions.py`; the gold follows its document
(ON DELETE CASCADE), the results table does not.
"""

from __future__ import annotations

import re
from enum import StrEnum

import psycopg
import pytest

from docreader.gold import GoldPath, GoldState, LoadKind
from docreader.outcomes import EvalStage
from docreader.questions import QuestionKind, QuestionOrigin

TABLES = {
    "gold_load": {"id", "kind", "file_name", "file_sha256", "loaded_at", "gold_sha256", "counts"},
    "gold_field": {
        "document_id", "field", "state", "values_text", "values_normalized", "path",
        "system_normalized", "clause_key", "load_id",
    },
    "blind_pick": {"document_id", "picked_at"},
    "gold_blind": {
        "document_id", "field", "state", "values_text", "values_normalized", "load_id",
    },
    "gold_question": {
        "key", "document_id", "text", "kind", "has_answer", "false_premise", "expected",
        "clause_keys", "origin", "source_file", "load_id",
    },
    "eval_result": {
        "id", "created_at", "label", "stage", "provenance", "gold_sha256", "questions_sha256",
        "reviewed_share", "blind_summary", "metrics", "review_file", "from_file",
    },
    "eval_case": {
        "result_id", "case_key", "document_id", "field", "question_key", "outcome", "place",
        "flags", "gold_sha",
    },
}

SHA = "a" * 64


def _columns(db: psycopg.Connection, table: str) -> set[str]:
    rows = db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table,)
    ).fetchall()
    return {r[0] for r in rows}


def _check_values(db: psycopg.Connection, table: str, column: str) -> set[str]:
    """The quoted literals of the CHECK constraint on `table.column` of the form IN (...)."""
    rows = db.execute(
        "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class t ON t.oid = c.conrelid WHERE t.relname = %s AND c.contype = 'c'",
        (table,),
    ).fetchall()
    for (definition,) in rows:
        if re.search(rf"\b{column}\b", definition) and "ANY" in definition:
            return set(re.findall(r"'([^']+)'::text", definition))
    raise AssertionError(f"no CHECK of {table}.{column}")


def _document(db: psycopg.Connection, seq: int = 1) -> str:
    doc_id = f"D-{seq:04d}"
    run_id = db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('intake', 't', '{}') RETURNING id"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO document (id, seq, sha256, original_name, source_path, copy_path, "
        "size_bytes, page_count, intake_run_id) VALUES (%s, %s, %s, 'x.pdf', 's', 'c', 1, 1, %s)",
        (doc_id, seq, f"{seq:064x}", run_id),
    )
    return doc_id


def _load(db: psycopg.Connection, kind: str = "review") -> int:
    return db.execute(
        "INSERT INTO gold_load (kind, file_name, file_sha256, gold_sha256, counts) "
        "VALUES (%s, 'f.json', %s, %s, '{}') RETURNING id",
        (kind, SHA, SHA),
    ).fetchone()[0]


def _gold(db: psycopg.Connection, doc: str, load: int, **over: object) -> None:
    row = {
        "state": "value", "values_text": ["1"], "values_normalized": ["1"], "path": "agree",
        "field": "contract_number",
    }
    row.update(over)
    db.execute(
        "INSERT INTO gold_field (document_id, field, state, values_text, values_normalized, "
        "path, load_id) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (doc, row["field"], row["state"], row["values_text"], row["values_normalized"],
         row["path"], load),
    )


def test_tables_and_columns(db: psycopg.Connection) -> None:
    applied = {r[0] for r in db.execute("SELECT version FROM schema_migrations").fetchall()}
    assert "0007_evaluation" in applied
    for table, columns in TABLES.items():
        assert _columns(db, table) == columns, table


@pytest.mark.parametrize(
    ("table", "column", "enum"),
    [
        ("gold_field", "state", GoldState),
        ("gold_field", "path", GoldPath),
        ("gold_blind", "state", GoldState),
        ("gold_load", "kind", LoadKind),
        ("gold_question", "kind", QuestionKind),
        ("gold_question", "origin", QuestionOrigin),
        ("eval_result", "stage", EvalStage),
    ],
)
def test_checks_equal_enums(
    db: psycopg.Connection, table: str, column: str, enum: type[StrEnum]
) -> None:
    assert _check_values(db, table, column) == {e.value for e in enum}


def test_absent_has_empty_arrays(db: psycopg.Connection) -> None:
    doc = _document(db)
    load = _load(db)
    _gold(db, doc, load, field="contract_end_date", state="absent", values_text=[],
          values_normalized=[], path="absent_marked")
    with pytest.raises(psycopg.errors.CheckViolation):
        _gold(db, doc, load, state="absent", values_text=["1"], values_normalized=["1"])
    with pytest.raises(psycopg.errors.CheckViolation):
        _gold(db, doc, load, field="amount_with_vat", state="value", values_text=[],
              values_normalized=[])
    with pytest.raises(psycopg.errors.CheckViolation):
        _gold(db, doc, load, field="amount_without_vat", values_text=["1", "2"],
              values_normalized=["1"])


def test_document_removal_keeps_results(db: psycopg.Connection) -> None:
    doc = _document(db)
    load = _load(db)
    _gold(db, doc, load)
    db.execute(
        "INSERT INTO gold_blind (document_id, field, state, values_text, values_normalized, "
        "load_id) VALUES (%s, 'contract_number', 'value', '{1}', '{1}', %s)",
        (doc, load),
    )
    db.execute("INSERT INTO blind_pick (document_id) VALUES (%s)", (doc,))
    db.execute(
        "INSERT INTO gold_question (key, document_id, text, has_answer, clause_keys, origin, "
        "source_file, load_id) VALUES ('Q-0000000000', %s, 'q', true, '{2.1}', 'own', "
        "'questions/q.toml', %s)",
        (doc, load),
    )
    result = db.execute(
        "INSERT INTO eval_result (stage, provenance, metrics) VALUES ('fields', '{}', '{}') "
        "RETURNING id"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO eval_case (result_id, case_key, document_id, field, outcome, flags, "
        "gold_sha) VALUES (%s, %s, %s, 'contract_number', 'correct', '{}', 'abcdef0123456789')",
        (result, f"{doc}/contract_number", doc),
    )

    db.execute("DELETE FROM document WHERE id = %s", (doc,))

    for table in ("gold_field", "gold_blind", "blind_pick", "gold_question"):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table
    assert db.execute("SELECT count(*) FROM eval_result").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM eval_case").fetchone()[0] == 1


def test_load_in_use_cannot_be_deleted(db: psycopg.Connection) -> None:
    doc = _document(db)
    load = _load(db)
    _gold(db, doc, load)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        db.execute("DELETE FROM gold_load WHERE id = %s", (load,))


def test_case_outcome_values(db: psycopg.Connection) -> None:
    result = db.execute(
        "INSERT INTO eval_result (stage, provenance, metrics) VALUES ('fields', '{}', '{}') "
        "RETURNING id"
    ).fetchone()[0]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO eval_case (result_id, case_key, document_id, outcome, flags, gold_sha) "
            "VALUES (%s, 'k', 'D-0001', 'maybe', '{}', 'abcdef0123456789')",
            (result,),
        )
