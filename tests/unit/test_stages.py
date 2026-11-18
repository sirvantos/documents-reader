"""Stages and states in code equal the CHECKs of the schema (task T064)."""

from __future__ import annotations

import re

from docreader.db import MIGRATIONS_DIR
from docreader.stages import STAGES, Stage, State, later_stages


def _check_values(column: str) -> list[str]:
    sql = (MIGRATIONS_DIR / "0001_intake.sql").read_text(encoding="utf-8")
    match = re.search(rf"CHECK \({column} IN \(([^)]*)\)\)", sql)
    assert match, f"no CHECK on {column}"
    return re.findall(r"'([a-z_]+)'", match.group(1))


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
