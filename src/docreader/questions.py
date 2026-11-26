"""Gold questions (feature 02): kinds and origins (research R-11).

The enums equal the CHECK constraints of `0007_evaluation.sql`.
"""

from __future__ import annotations

from enum import StrEnum


class QuestionKind(StrEnum):
    """Where the answer comes from."""

    TEXT = "text"
    TABLE = "table"
    BOTH = "both"


class QuestionOrigin(StrEnum):
    """Which file kind a question came from."""

    OWN = "own"
    SET08 = "set08"
    SET09 = "set09"
    GENERATED = "generated"
