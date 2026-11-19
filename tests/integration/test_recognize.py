"""Integration tests for `docreader recognize` (US1, FR-001…FR-016; task T014).

The CLI is run in-process. The engine comes from `docreader.ocr_engines.load_engine`,
which every test replaces with a spy factory handing out fakes from tests/fakes/ocr.py:
no real recognition engine is ever loaded (research R-4, R-13).
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from docreader import ocr_engines
from docreader.errors import EnvironmentProblem
from tests.fakes.ocr import FailingEngine, InterruptingEngine, ScriptedEngine, TruthEngine
from tests.synthetic import make_pdfs, make_scans

NOTHING_MSG = (
    "Нечего распознавать: все страницы-сканы распознаны "
    "(заново: docreader recognize --all --force)"
)
RESET_REASON = "распознанный текст изменён"
LATER_STAGES = ("structure", "extraction", "checks", "indexing")


# --- helpers ------------------------------------------------------------------------


def truth_of(pdf: Path) -> dict:
    return json.loads(pdf.with_suffix(".truth.json").read_text(encoding="utf-8"))


def add(cli, folder: Path, *makers) -> tuple[list[str], list[Path]]:
    """Add generated files (in this order); return their ids and the generated paths."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = [make(folder / f"f{i}.pdf") for i, make in enumerate(makers)]
    ids = []
    for path in paths:
        result = cli("add", path, "--json")
        assert result.exit_code == 0, result.stderr
        ids.append(json.loads(result.stdout)["files"][0]["document_id"])
    return ids, paths


def recognize(cli, *args) -> tuple[int, dict | None, str]:
    result = cli("recognize", *args, "--json")
    data = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
    return result.exit_code, data, result.stderr


def rows(db, doc_id: str) -> list[dict]:
    cur = db.execute(
        "SELECT page_number, engine, engine_version, dpi, turn, orientation_unknown, lines,"
        " quality, ink_share, result_sha256, seconds, error, run_id, recognized_at"
        " FROM page_recognition WHERE document_id = %s ORDER BY page_number",
        (doc_id,),
    )
    names = [c.name for c in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def stage(db, doc_id: str, name: str) -> tuple:
    return db.execute(
        "SELECT state, reason, run_id FROM stage_status WHERE document_id = %s AND stage = %s",
        (doc_id, name),
    ).fetchone()


def set_stage(db, doc_id: str, name: str, state: str, reason: str | None = None) -> None:
    db.execute(
        "UPDATE stage_status SET state = %s, reason = %s WHERE document_id = %s AND stage = %s",
        (state, reason, doc_id, name),
    )


def runs(db) -> list[tuple]:
    return db.execute(
        "SELECT id, stage, model, settings, label FROM run WHERE stage = 'recognition' ORDER BY id"
    ).fetchall()


def copy_path(db, data_dir: Path, doc_id: str) -> Path:
    (rel,) = db.execute("SELECT copy_path FROM document WHERE id = %s", (doc_id,)).fetchone()
    return data_dir / rel


def files_outside_reports(data_dir: Path) -> set[Path]:
    return {
        p.relative_to(data_dir)
        for p in data_dir.rglob("*")
        if p.is_file() and p.relative_to(data_dir).parts[0] != "reports"
    }


def scan_pages(truth: dict) -> Sequence[int]:
    return [p["page"] for p in truth["pages"] if p["kind"] == "scan"]


# --- US1-1, FR-001…FR-003: an all-scan document ---------------------------------------


def test_all_scan_document_gets_a_row_per_page(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    factory = use_engine(TruthEngine(truth_of(pdf)))

    code, data, _ = recognize(cli)

    assert code == 0
    assert factory.calls == 1  # loaded once per run
    saved = rows(db, doc)
    assert [r["page_number"] for r in saved] == [1, 2]
    for row, page in zip(saved, truth_of(pdf)["pages"], strict=True):
        assert row["error"] is None
        assert (row["engine"], row["engine_version"], row["dpi"]) == ("truth", "1", 300)
        assert row["turn"] == 0 and row["orientation_unknown"] is False
        assert row["seconds"] >= 0 and row["run_id"] == data["run_id"]
        assert row["quality"] == pytest.approx(0.99)
        assert 0 <= row["ink_share"] <= 1
        assert len(row["result_sha256"]) == 64
        assert [ln["text"] for ln in row["lines"]] == [ln["text"] for ln in page["lines"]]
        for i, line in enumerate(row["lines"]):
            assert set(line) == {"i", "text", "bbox", "confidence"}
            assert line["i"] == i
            left, bottom, right, top = line["bbox"]
            assert 0 <= left < right <= 595 and 0 <= bottom < top <= 842
            assert line["confidence"] == pytest.approx(0.99)
    assert stage(db, doc, "recognition")[:2] == ("done", None)
    entry = data["documents"][0]
    assert (entry["id"], entry["scan_pages"], entry["recognized"], entry["errors"]) == (
        doc,
        2,
        2,
        0,
    )
    assert entry["state"] == "done" and entry["reason"] is None
    assert (data["engine"], data["engine_version"], data["dpi"]) == ("truth", "1", 300)
    assert data["interrupted"] is False
    assert {p["page"] for p in entry["pages"]} == {1, 2}
    assert all("text" not in p for p in entry["pages"])  # no contract text in JSON


def test_bboxes_follow_the_page(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))

    recognize(cli)

    for row, page in zip(rows(db, doc), truth_of(pdf)["pages"], strict=True):
        for got, want in zip(row["lines"], page["lines"], strict=True):
            assert got["bbox"] == pytest.approx(want["bbox"], abs=1.0)


# --- US1-2: only scan pages of a mixed document -----------------------------------------


def test_mixed_document_recognises_only_scan_pages(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_mixed)
    engine = TruthEngine(truth_of(pdf))
    use_engine(engine)

    recognize(cli)

    assert [r["page_number"] for r in rows(db, doc)] == list(scan_pages(truth_of(pdf)))
    assert engine.calls == 2


# --- US1-3: a document without scans --------------------------------------------------


def test_text_document_is_done_without_loading_the_engine(cli, db, tmp_path, use_engine) -> None:
    (doc,), _ = add(cli, tmp_path / "in", make_pdfs.make_contract_ru)
    factory = use_engine(ScriptedEngine([]))

    code, data, _ = recognize(cli)

    assert code == 0
    assert factory.calls == 0
    assert stage(db, doc, "recognition")[:2] == ("done", None)
    assert data["documents"][0]["scan_pages"] == 0
    assert rows(db, doc) == []
    (run,) = runs(db)
    assert run[2] is None  # model: no engine was needed


def test_scan_with_embedded_text_is_not_recognised(cli, db, tmp_path, use_engine) -> None:
    """Open question 1, default: the embedded layer is kept and read as before."""
    (doc,), _ = add(cli, tmp_path / "in", make_pdfs.make_image_with_invisible_text)
    factory = use_engine(ScriptedEngine([]))

    recognize(cli)

    assert factory.calls == 0
    assert rows(db, doc) == []
    assert stage(db, doc, "recognition")[0] == "done"
    assert cli("read", doc).exit_code == 0
    flags = db.execute(
        "SELECT DISTINCT code FROM page_flag WHERE document_id = %s", (doc,)
    ).fetchall()
    assert ("ocr_text",) in flags
    sources = db.execute(
        "SELECT DISTINCT source FROM page_text WHERE document_id = %s", (doc,)
    ).fetchall()
    assert sources == [("pdf",)]


# --- US1-5, FR-007: the copy is untouched, no files written ---------------------------


def test_copy_unchanged_and_no_files_written(cli, db, data_dir, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))
    copy = copy_path(db, data_dir, doc)
    digest = hashlib.sha256(copy.read_bytes()).hexdigest()
    before = files_outside_reports(data_dir)

    recognize(cli)

    assert hashlib.sha256(copy.read_bytes()).hexdigest() == digest
    assert files_outside_reports(data_dir) == before


# --- US1-6, FR-013: interrupted, then resumed -----------------------------------------


def test_interrupted_run_resumes_from_the_first_unsaved_page(
    cli, db, tmp_path, use_engine
) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", lambda p: make_scans.make_scan_clean(p, pages=3))
    truth = truth_of(pdf)
    use_engine(InterruptingEngine(2, TruthEngine(truth)))

    code, data, _ = recognize(cli)

    assert code == 130
    assert data["interrupted"] is True
    assert [r["page_number"] for r in rows(db, doc)] == [1]
    assert stage(db, doc, "recognition")[0] != "done"

    rest = TruthEngine(truth, pages=[2, 3])
    use_engine(rest)
    code, data, _ = recognize(cli)

    assert code == 0
    assert rest.calls == 2
    resumed = rows(db, doc)
    assert [r["page_number"] for r in resumed] == [1, 2, 3]
    assert stage(db, doc, "recognition")[:2] == ("done", None)

    # the same result as one uninterrupted run
    db.execute("DELETE FROM page_recognition WHERE document_id = %s", (doc,))
    set_stage(db, doc, "recognition", "pending")
    use_engine(TruthEngine(truth))
    recognize(cli)
    assert [r["result_sha256"] for r in rows(db, doc)] == [
        r["result_sha256"] for r in resumed
    ]


# --- US1-7, FR-011, SC-008: nothing to do -----------------------------------------------


def test_second_run_recognises_nothing(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))
    recognize(cli)
    states = db.execute("SELECT * FROM stage_status ORDER BY 1, 2").fetchall()
    saved = rows(db, doc)
    factory = use_engine(ScriptedEngine([]))

    result = cli("recognize")

    assert result.exit_code == 0
    assert NOTHING_MSG in result.stdout
    assert factory.calls == 0
    assert len(runs(db)) == 1
    assert db.execute("SELECT * FROM stage_status ORDER BY 1, 2").fetchall() == states
    assert rows(db, doc) == saved


def test_explicit_id_without_force_recognises_no_saved_page(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))
    recognize(cli)
    saved = rows(db, doc)
    engine = ScriptedEngine([])
    use_engine(engine)

    code, _, _ = recognize(cli, doc)

    assert code == 0
    assert engine.calls == 0
    assert rows(db, doc) == saved


# --- FR-012: reading goes back to pending when the recognised text changed -------------


def test_reading_is_reset_when_scans_get_text(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    assert cli("read", doc).exit_code == 0
    assert stage(db, doc, "reading")[0] == "needs_review"  # scans not read yet
    for name in LATER_STAGES:
        set_stage(db, doc, name, "done")
    use_engine(TruthEngine(truth_of(pdf)))

    code, data, _ = recognize(cli)

    assert code == 0
    assert stage(db, doc, "reading") == ("pending", RESET_REASON, data["run_id"])
    assert data["documents"][0]["reading_reset"] is True
    for name in LATER_STAGES:
        assert stage(db, doc, name)[0] == "done"


def test_pending_reading_keeps_its_reason(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    set_stage(db, doc, "reading", "pending", "текст изменён")
    use_engine(TruthEngine(truth_of(pdf)))

    _, data, _ = recognize(cli)

    assert stage(db, doc, "reading")[:2] == ("pending", "текст изменён")
    assert data["documents"][0]["reading_reset"] is False


# --- FR-014, FR-016: page and document errors -----------------------------------------


def test_page_error_keeps_the_other_pages(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", lambda p: make_scans.make_scan_clean(p, pages=3))
    # call 2 fails; the inner engine sees only calls 1 and 3 → pages 1 and 3
    use_engine(FailingEngine({2}, TruthEngine(truth_of(pdf), pages=[1, 3])))

    code, data, _ = recognize(cli)

    assert code == 0
    saved = {r["page_number"]: r for r in rows(db, doc)}
    assert set(saved) == {1, 2, 3}
    assert saved[1]["error"] is None and saved[3]["error"] is None
    failed = saved[2]
    assert failed["error"] == "RuntimeError: engine failed"
    assert failed["lines"] == [] and failed["quality"] is None
    reason = "стр. 2: ошибка распознавания — RuntimeError: engine failed"
    assert stage(db, doc, "recognition")[:2] == ("needs_review", reason)
    entry = data["documents"][0]
    assert (entry["recognized"], entry["errors"], entry["state"]) == (2, 1, "needs_review")


def test_failed_page_is_retried_by_the_next_run(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    truth = truth_of(pdf)
    use_engine(FailingEngine({2}, TruthEngine(truth)))
    recognize(cli)
    retry = TruthEngine(truth, pages=[2])
    use_engine(retry)

    recognize(cli)

    assert retry.calls == 1
    assert all(r["error"] is None for r in rows(db, doc))
    assert stage(db, doc, "recognition")[:2] == ("done", None)


def test_missing_copy_fails_only_that_document(cli, db, data_dir, tmp_path, use_engine) -> None:
    (first, second), (_, pdf2) = add(
        cli, tmp_path / "in", make_scans.make_scan_clean, make_scans.make_scan_faded_noisy
    )
    copy_path(db, data_dir, first).unlink()
    use_engine(TruthEngine(truth_of(pdf2)))

    code, data, _ = recognize(cli)

    assert code == 0
    state, reason, _ = stage(db, first, "recognition")
    assert state == "failed" and "docreader verify" in reason
    assert stage(db, second, "recognition")[0] == "done"
    assert {d["id"]: d["state"] for d in data["documents"]} == {
        first: "failed",
        second: "done",
    }


def test_environment_problem_stops_the_run(cli, db, tmp_path, monkeypatch) -> None:
    add(cli, tmp_path / "in", make_scans.make_scan_clean)

    def refuse(settings, data_dir):
        raise EnvironmentProblem("Не выбран движок распознавания — укажите [recognition] engine")

    monkeypatch.setattr(ocr_engines, "load_engine", refuse)

    result = cli("recognize")

    assert result.exit_code == 2
    assert "Не выбран движок распознавания" in result.stderr


def test_real_guard_stops_the_run_on_this_machine(cli, tmp_path, data_dir) -> None:
    """Without a replaced factory the real loader refuses: the engine is forbidden here."""
    add(cli, tmp_path / "in", make_scans.make_scan_clean)
    (data_dir / "settings.toml").write_text('[recognition]\nengine = "spy"\n', encoding="utf-8")
    ocr_engines.ENGINES.setdefault("spy", lambda settings, data_dir: None)  # type: ignore[arg-type,return-value]
    try:
        result = cli("recognize")
    finally:
        ocr_engines.ENGINES.pop("spy", None)

    assert result.exit_code == 2
    assert "DOCREADER_FORBID_MODELS" in result.stderr


# --- FR-015: the run record ---------------------------------------------------------------


def test_run_records_engine_settings_and_label(cli, db, tmp_path, use_engine) -> None:
    _, (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))

    result = cli("recognize", "--label", "проба")

    assert result.exit_code == 0
    (run,) = runs(db)
    _, run_stage, model, settings, label = run
    assert (run_stage, model, label) == ("recognition", "truth 1", "проба")
    rec = settings["recognition"]
    assert rec["dpi"] == 300 and rec["engine_version"] == "1"
    assert rec["platform"] == {"system": sys.platform, "machine": platform.machine()}
    assert "page_min_quality" in rec


# --- selection errors ---------------------------------------------------------------------


def test_all_with_ids_is_a_user_error(cli, tmp_path, use_engine) -> None:
    (doc,), _ = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(ScriptedEngine([]))
    result = cli("recognize", doc, "--all")
    assert result.exit_code == 1


def test_unknown_id_is_a_user_error_and_nothing_recognised(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    engine = TruthEngine(truth_of(pdf))
    use_engine(engine)

    result = cli("recognize", doc, "D-0099")

    assert result.exit_code == 1
    assert "D-0099" in result.stderr
    assert engine.calls == 0
    assert rows(db, doc) == []
