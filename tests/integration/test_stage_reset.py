"""`stages.reset_stage`: one stage back to pending unless it already is (feature 13, T004)."""

from __future__ import annotations

from docreader import stages
from docreader.stages import Stage, State

SHA = "b" * 64


def _seed(db) -> int:
    run_id = db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('recognition', 'test', '{}') "
        "RETURNING id"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO document (id, seq, sha256, original_name, source_path, copy_path, "
        "size_bytes, page_count, intake_run_id) "
        "VALUES ('D-0001', 1, %s, 'a.pdf', '/x/a.pdf', 'originals/a.pdf', 10, 1, %s)",
        (SHA, run_id),
    )
    with db.transaction():
        stages.create_pending(db, "D-0001")
    return run_id


def _state(db, stage: Stage) -> tuple:
    return db.execute(
        "SELECT state, reason, run_id FROM stage_status WHERE document_id = 'D-0001' "
        "AND stage = %s",
        (stage,),
    ).fetchone()


def test_create_pending_includes_recognition(db) -> None:
    _seed(db)
    assert _state(db, Stage.RECOGNITION)[0] == "pending"


def test_reset_stage_moves_a_finished_stage_to_pending(db) -> None:
    run_id = _seed(db)
    stages.set_state(db, "D-0001", Stage.READING, State.DONE, None, run_id)
    stages.set_state(db, "D-0001", Stage.STRUCTURE, State.DONE, None, run_id)

    stages.reset_stage(db, "D-0001", Stage.READING, "распознанный текст изменён", run_id)

    assert _state(db, Stage.READING) == ("pending", "распознанный текст изменён", run_id)
    assert _state(db, Stage.STRUCTURE)[0] == "done"  # later stages are not touched


def test_reset_stage_keeps_a_pending_stage_as_it_is(db) -> None:
    run_id = _seed(db)
    stages.set_state(db, "D-0001", Stage.READING, State.PENDING, "текст изменён", None)

    stages.reset_stage(db, "D-0001", Stage.READING, "распознанный текст изменён", run_id)

    assert _state(db, Stage.READING) == ("pending", "текст изменён", None)
