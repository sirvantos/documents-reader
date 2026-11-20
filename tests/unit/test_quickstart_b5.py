"""The Б5 summary carries only numbers and ids, never file names (principle I)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "quickstart_b5.py"
spec = importlib.util.spec_from_file_location("quickstart_b5", SCRIPT)
assert spec is not None and spec.loader is not None
quickstart_b5 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quickstart_b5)

SECRET_NAME = "договор_ООО_Ромашка_секретный.pdf"


def summary() -> str:
    report = {
        "documents": [
            {"id": "D-0001", "name": SECRET_NAME, "scan_pages": 40, "recognized": 39,
             "errors": 1, "flags": {"low_recognition_quality": [3, 4], "scan_no_text": [7],
                                    "empty": []}, "mean_quality": 0.91, "seconds": 60.0},
            {"id": "D-0002", "name": "другой.pdf", "scan_pages": 10, "recognized": 10,
             "errors": 0, "flags": {}, "mean_quality": 0.95, "seconds": 15.0},
        ],
        "totals": {"scan_pages": 50, "recognized": 49, "errors": 1, "seconds": 75.0,
                   "flags": {"low_recognition_quality": 2, "scan_no_text": 1, "empty": 0}},
    }
    read_report = {
        "documents": [
            {"id": "D-0001", "name": SECRET_NAME, "pages": 40, "read": 39, "state": "needs_review"},
            {"id": "D-0002", "name": "другой.pdf", "pages": 10, "read": 10, "state": "done"},
        ],
        "totals": {"pages": 50, "read": 49, "tables": 3, "flags": {}},
    }
    lines = quickstart_b5.summarize(
        machine={"system": "Darwin", "release": "15.1", "arch": "arm64", "cpus": 12},
        precheck={"engine": "tesseract", "dpi": 300, "try_rotations": True,
                  "langs": ["osd", "rus"]},
        run_pages=[
            {"page": 1, "turn": 0, "seconds": 1.5},
            {"page": 2, "turn": 180, "seconds": 2.5},
        ],
        recognize_wall=4.0,
        report=report,
        review={"pages": [{"id": "D-0001", "page": 3, "code": "low_recognition_quality",
                           "reason": "оценка 0,52 < 0,80"}]},
        read_report=read_report,
        read_all_seconds=42.0,
        second_run={"pages": 0},
        states_unchanged=True,
        peak_mb=310.0,
    )
    return "\n".join(lines)


def test_summary_has_no_file_names_or_reasons() -> None:
    text = summary()
    assert SECRET_NAME not in text and "Ромашка" not in text and "другой" not in text
    assert "оценка 0,52" not in text


def test_summary_has_the_numbers() -> None:
    text = summary()
    assert "страниц-сканов 50, распознано 49, ошибок 1, без учёта 0" in text
    assert "2 из 2 (100.0%)" in text
    assert "D-0001: 40, 3, 0.91" in text and "D-0002:" not in text  # only flagged documents
    assert "доворот в этом запуске: {0: 1, 180: 1}" in text
    assert "read --all: 42 с" in text
