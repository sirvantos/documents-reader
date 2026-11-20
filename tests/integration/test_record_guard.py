"""The recording command takes only files from tests/synthetic/ (principle I; task T036).

The real `tests/synthetic/` is never written to here (Docker mounts the repository
read-only): the command gets a temporary `synthetic_dir` and `recordings_dir`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docreader.config import RecognitionSettings
from tests.fakes.ocr import EngineFactorySpy, TruthEngine
from tests.synthetic import make_scans, record_recognition


@pytest.fixture
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    synthetic = tmp_path / "synthetic"
    (synthetic / "out").mkdir(parents=True)
    return synthetic, tmp_path / "recordings"


def _run(paths, dirs, factory) -> int:
    synthetic, recordings = dirs
    return record_recognition.main(
        [str(p) for p in paths],
        synthetic_dir=synthetic,
        recordings_dir=recordings,
        settings=RecognitionSettings(engine="truth", dpi=100),
        data_dir=synthetic,
        engine_factory=factory,
    )


def test_real_synthetic_dir_is_the_default() -> None:
    assert record_recognition.SYNTHETIC_DIR == Path(make_scans.__file__).resolve().parent


@pytest.mark.parametrize("where", ["outside", "dotdot", "symlink"])
def test_paths_outside_synthetic_are_refused_before_the_engine(
    where: str, tmp_path: Path, dirs, capsys
) -> None:
    synthetic, _ = dirs
    outside = make_scans.make_scan_clean(tmp_path / "real.pdf", pages=1)
    if where == "outside":
        path = outside
    elif where == "dotdot":
        path = synthetic / ".." / "real.pdf"
    else:
        path = synthetic / "out" / "link.pdf"
        path.symlink_to(outside)
    factory = EngineFactorySpy(TruthEngine({"pages": []}))

    code = _run([path], dirs, factory)

    assert code == 1
    assert factory.calls == 0
    assert "записываются только синтетические файлы из tests/synthetic/" in capsys.readouterr().err


def test_real_guard_stops_recording_on_this_machine(dirs, capsys) -> None:
    synthetic, recordings = dirs
    code = record_recognition.main(
        [],
        synthetic_dir=synthetic,
        recordings_dir=recordings,
        settings=RecognitionSettings(engine="tesseract"),
        data_dir=synthetic,
    )
    assert code == 2
    assert "DOCREADER_FORBID_MODELS" in capsys.readouterr().err
    assert not recordings.exists()


def test_a_synthetic_file_is_recorded_in_the_documented_shape(dirs) -> None:
    synthetic, recordings = dirs
    pdf = make_scans.make_scan_mixed(synthetic / "out" / "scan_mixed.pdf")
    truth = json.loads(pdf.with_suffix(".truth.json").read_text(encoding="utf-8"))
    engine = TruthEngine(truth)

    code = _run([pdf], dirs, EngineFactorySpy(engine))

    assert code == 0
    saved = json.loads((recordings / "truth" / "mixed.json").read_text(encoding="utf-8"))
    assert {k: saved[k] for k in ("engine", "engine_version", "dpi", "variant")} == {
        "engine": "truth",
        "engine_version": "1",
        "dpi": 100,
        "variant": "mixed",
    }
    assert saved["generator_version"] == make_scans.SCAN_GENERATOR_VERSION
    assert saved["recorded_at"]
    assert [p["page"] for p in saved["pages"]] == [2, 4]  # scan pages only
    first = saved["pages"][0]
    assert set(first) == {"page", "turns"}
    # the turn trial of recognition (R-6) asks the engine about the turned image too
    assert [t["turn"] for t in first["turns"]] == [0, 90, 180, 270]
    upright, quarter = first["turns"][0], first["turns"][1]
    assert set(upright) == {"turn", "image_size", "thumb", "orientation", "lines"}
    assert quarter["image_size"] == upright["image_size"][::-1]
    assert upright["thumb"] != quarter["thumb"]
    assert set(upright["lines"][0]) == {"text", "box", "confidence"}
    assert upright["lines"][0]["text"] == truth["pages"][1]["lines"][0]["text"]
    assert engine.calls == 8  # 2 scan pages x 4 turns
