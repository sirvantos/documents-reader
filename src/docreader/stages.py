"""Document processing stages and their states, in one place (tech-context «Правила кода»).

`Stage` and `State` must equal the CHECKs on `stage_status` in
the latest migration that sets them (tests/unit/test_stages.py checks it). Every update of
`stage_status` goes through the functions below, not through SQL of its own.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

import psycopg


class Stage(StrEnum):
    """A document processing stage, in pipeline order (FR-008)."""

    RECOGNITION = "recognition"  # feature 13: scan pages, before reading
    READING = "reading"
    STRUCTURE = "structure"
    EXTRACTION = "extraction"
    CHECKS = "checks"
    INDEXING = "indexing"


class State(StrEnum):
    """State of one stage for one document; `needs_review` and `failed` need a reason."""

    PENDING = "pending"
    DONE = "done"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class RunStage(StrEnum):
    """`run.stage`: which command family a run belongs to."""

    INTAKE = "intake"  # add, reclassify
    READING = "reading"
    RECOGNITION = "recognition"
    STRUCTURE = "structure"  # feature 04: parse
    EXTRACTION = "extraction"  # feature 05: extract
    INDEXING = "indexing"  # feature 07: index


STAGES: tuple[Stage, ...] = tuple(Stage)
# States a finished run of a stage can leave a document in.
RESULT_STATES: tuple[State, ...] = (State.DONE, State.NEEDS_REVIEW, State.FAILED)


def later_stages(stage: Stage) -> tuple[Stage, ...]:
    """The stages after `stage`; their results depend on it."""
    return STAGES[STAGES.index(stage) + 1 :]


def create_pending(conn: psycopg.Connection, doc_id: str) -> None:
    """One `pending` row per stage for a new document (call inside its transaction)."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO stage_status (document_id, stage) VALUES (%s, %s)",
            [(doc_id, stage) for stage in STAGES],
        )


def lock(conn: psycopg.Connection, doc_id: str, stage: Stage) -> None:
    """Lock the stage row until the end of the transaction (serialises reruns)."""
    conn.execute(
        "SELECT 1 FROM stage_status WHERE document_id = %s AND stage = %s FOR UPDATE",
        (doc_id, stage),
    )


def set_state(
    conn: psycopg.Connection,
    doc_id: str,
    stage: Stage,
    state: State,
    reason: str | None,
    run_id: int | None,
) -> None:
    conn.execute(
        "UPDATE stage_status SET state = %s, reason = %s, run_id = %s, updated_at = now()"
        " WHERE document_id = %s AND stage = %s",
        (state, reason, run_id, doc_id, stage),
    )


def reset_later(
    conn: psycopg.Connection, doc_id: str, stage: Stage, reason: str, run_id: int
) -> None:
    """Results after `stage` are stale: their stages go back to `pending` with `reason`.

    Stages already `pending` keep their reason. The results themselves stay until the
    stage is rerun (tech-context «Договорённости между этапами»).
    """
    conn.execute(
        "UPDATE stage_status SET state = %s, reason = %s, run_id = %s, updated_at = now()"
        " WHERE document_id = %s AND stage = ANY(%s) AND state <> %s",
        (State.PENDING, reason, run_id, doc_id, list(later_stages(stage)), State.PENDING),
    )


def reset_stage(
    conn: psycopg.Connection, doc_id: str, stage: Stage, reason: str, run_id: int
) -> bool:
    """One stage back to `pending` with `reason`; a stage already `pending` is kept as is.

    Recognition uses it for `reading` only: later stages are reset by reading itself
    when the text changes (research R-11 of feature 13). True if the stage was reset.
    """
    cur = conn.execute(
        "UPDATE stage_status SET state = %s, reason = %s, run_id = %s, updated_at = now()"
        " WHERE document_id = %s AND stage = %s AND state <> %s",
        (State.PENDING, reason, run_id, doc_id, stage, State.PENDING),
    )
    return cur.rowcount > 0


def reset_all(conn: psycopg.Connection, doc_ids: Sequence[str]) -> None:
    """Every stage of these documents back to `pending` without a reason (reclassify)."""
    conn.execute(
        "UPDATE stage_status SET state = %s, reason = NULL, run_id = NULL, updated_at = now()"
        " WHERE document_id = ANY(%s)",
        (State.PENDING, list(doc_ids)),
    )
