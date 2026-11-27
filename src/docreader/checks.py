"""Rule checks and field statuses of the six prototype fields (feature 06).

The schema of migration 0008 and its enums; the rules, statuses and commands come in the
tasks that follow (specs/010-rule-checks/research.md).
"""

from __future__ import annotations

from enum import StrEnum

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
