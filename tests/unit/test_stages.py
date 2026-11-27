"""Stages and states in code equal the CHECKs of the schema (task T064)."""

from __future__ import annotations

import re

from docreader.db import MIGRATIONS_DIR
from docreader.stages import STAGES, RunStage, Stage, State, later_stages


def _check_values(column: str) -> list[str]:
    """Values of the latest `CHECK (column IN (...))` of `stage_status` across the
    migrations, in order. Migrations that do not touch `stage_status` are skipped: other
    tables have columns of the same names (`eval_result.stage`, `gold_field.state`)."""
    found: list[str] | None = None
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        if "stage_status" not in sql:
            continue
        for match in re.finditer(rf"CHECK \({column} IN \(([^)]*)\)\)", sql):
            found = re.findall(r"'([a-z_]+)'", match.group(1))
    assert found, f"no CHECK on {column}"
    return found


def test_stages_equal_the_schema_check_in_order():
    assert [s.value for s in STAGES] == _check_values("stage")


def test_states_equal_the_schema_check():
    assert sorted(s.value for s in State) == sorted(_check_values("state"))


def test_later_stages():
    assert later_stages(Stage.READING) == (
        Stage.STRUCTURE,
        Stage.EXTRACTION,
        Stage.CHECKS,
        Stage.INDEXING,
    )
    assert later_stages(Stage.INDEXING) == ()


def test_enum_members_are_plain_strings_for_sql_and_json():
    assert Stage.READING == "reading"
    assert {State.NEEDS_REVIEW: 1}["needs_review"] == 1


def test_recognition_is_the_first_stage():
    assert STAGES[0] is Stage.RECOGNITION
    assert Stage.RECOGNITION == "recognition"
    assert RunStage.RECOGNITION == "recognition"
    assert [s.value for s in STAGES] == [
        "recognition",
        "reading",
        "structure",
        "extraction",
        "checks",
        "indexing",
    ]


def test_structure_run_stage():
    assert RunStage.STRUCTURE == "structure"


def test_run_stage_indexing_equals_stage_indexing():
    assert RunStage.INDEXING.value == Stage.INDEXING.value
