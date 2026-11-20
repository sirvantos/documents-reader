"""Recognition on recordings of the real engine (level 2, research R-13; task T037).

Every scan variant of `make_scans` is recognised with `RecordedEngine` (the recorded
output of the configured engine) and then read. The checks are about structure, not
exact text. A missing or out-of-date recording fails the test; it is never skipped.
Recordings are made only with `python -m tests.synthetic.record_recognition`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docreader.config import RecognitionSettings
from docreader.recognition_eval import char_accuracy
from tests.fakes.ocr import RecordedEngine
from tests.integration.test_recognize import add, rows, truth_of
from tests.integration.test_recognize_reading import flags, page_text, read
from tests.synthetic import make_scans

RECORDINGS = Path(__file__).resolve().parents[1] / "recordings" / "13-scan-recognition"
SETTINGS = RecognitionSettings()  # the test data dir has no [recognition]: the defaults
PAGE_MID = 595.0 / 2
STAMP = (84.0, 612.0, 176.0, 704.0)  # make_scans._STAMP_X/_Y/_R (130, 658, 46) as a box

VARIANTS = {
    "clean": make_scans.make_scan_clean,
    "mixed": make_scans.make_scan_mixed,
    "faded_noisy": make_scans.make_scan_faded_noisy,
    "page_rotate_90": make_scans.make_scan_page_rotate_90,
    "requisites_two_columns": make_scans.make_scan_requisites_two_columns,
    "rotated_90": make_scans.make_scan_rotated_90,
    "rotated_180": make_scans.make_scan_rotated_180,
    "skew_3deg": make_scans.make_scan_skew_3deg,
    "table": make_scans.make_scan_table,
    "stamp_over_text": make_scans.make_scan_stamp_over_text,
    "stamp_only": make_scans.make_scan_stamp_only,
    "blank": make_scans.make_scan_blank,
}


def recording(variant: str) -> Path:
    return RECORDINGS / SETTINGS.engine / f"{variant}.json"


def recognised(cli, db, tmp_path, use_engine, variant: str) -> tuple[str, Path]:
    """Recognise and read one generated variant with its recording; return id and PDF."""
    engine = RecordedEngine(recording(variant), SETTINGS)
    (doc,), (pdf,) = add(cli, tmp_path / variant, VARIANTS[variant])
    use_engine(engine)
    result = cli("recognize", doc)
    assert result.exit_code == 0, result.stderr
    assert engine.misses == [], f"no recorded answer for images of size {engine.misses}"
    read(cli, doc)
    return doc, pdf


def lines_of(db, doc: str, page: int) -> list[dict]:
    for number, _, lines, _ in page_text(db, doc):
        if number == page:
            return lines if isinstance(lines, list) else json.loads(lines)
    raise AssertionError(f"no page_text for page {page}")


def overlap(a, b) -> float:
    """Intersection area of two PDF boxes [left, bottom, right, top]."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    return max(width, 0.0) * max(height, 0.0)


def mean_quality(db, doc: str) -> float:
    values = [r["quality"] for r in rows(db, doc)]
    assert all(v is not None for v in values)
    return sum(values) / len(values)


# --- the recordings themselves ------------------------------------------------------------


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_recording_is_current(variant: str) -> None:
    RecordedEngine(recording(variant), SETTINGS)  # fails with «запись устарела…»


def test_all_recordings_come_from_one_engine_version() -> None:
    versions = {
        json.loads(recording(v).read_text(encoding="utf-8"))["engine_version"] for v in VARIANTS
    }
    assert len(versions) == 1, f"recordings made with different engine versions: {versions}"


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_every_variant_is_recognised_without_page_errors(
    cli, db, tmp_path, use_engine, variant
) -> None:
    doc, _ = recognised(cli, db, tmp_path, use_engine, variant)
    assert all(r["error"] is None for r in rows(db, doc))


# --- clean ----------------------------------------------------------------------------------


def test_clean_text_and_boxes(cli, db, tmp_path, use_engine) -> None:
    doc, pdf = recognised(cli, db, tmp_path, use_engine, "clean")
    for page in truth_of(pdf)["pages"]:
        got = lines_of(db, doc, page["page"])
        expected = "\n".join(line["text"] for line in page["lines"])
        accuracy = char_accuracy(expected, "\n".join(line["text"] for line in got))
        assert accuracy >= 0.95, f"page {page['page']}: {accuracy:.3f}"
        for line in page["lines"]:
            assert any(overlap(line["bbox"], g["bbox"]) > 0 for g in got), line["text"]


# --- layout ----------------------------------------------------------------------------------


def test_two_columns_are_read_left_then_right(cli, db, tmp_path, use_engine) -> None:
    doc, pdf = recognised(cli, db, tmp_path, use_engine, "requisites_two_columns")
    truth_lines = truth_of(pdf)["pages"][0]["lines"]
    columns = []
    for line in lines_of(db, doc, 1):
        best = max(truth_lines, key=lambda t: overlap(t["bbox"], line["bbox"]))
        if overlap(best["bbox"], line["bbox"]) > 0:
            columns.append("right" if best["bbox"][0] >= PAGE_MID else "left")
    assert "right" in columns and "left" in columns
    first_right = columns.index("right")
    assert "left" not in columns[first_right:], columns


def test_rotated_page_is_turned_back(cli, db, tmp_path, use_engine) -> None:
    doc, _ = recognised(cli, db, tmp_path, use_engine, "rotated_180")
    assert [r["turn"] for r in rows(db, doc)] == [180]


# --- quality ---------------------------------------------------------------------------------


def test_faded_page_scores_lower_than_clean(cli, db, tmp_path, use_engine) -> None:
    clean, _ = recognised(cli, db, tmp_path, use_engine, "clean")
    faded, _ = recognised(cli, db, tmp_path, use_engine, "faded_noisy")
    assert mean_quality(db, faded) < mean_quality(db, clean)


def test_stamp_lowers_quality_but_text_around_it_is_read(cli, db, tmp_path, use_engine) -> None:
    clean, _ = recognised(cli, db, tmp_path, use_engine, "clean")
    doc, pdf = recognised(cli, db, tmp_path, use_engine, "stamp_over_text")
    assert mean_quality(db, doc) < mean_quality(db, clean)
    got = [line["text"] for line in lines_of(db, doc, 1)]
    for line in truth_of(pdf)["pages"][0]["lines"]:
        if overlap(line["bbox"], STAMP) > 0:
            continue
        best = max(char_accuracy(line["text"], g) for g in got)
        assert best >= 0.9, f"{line['text']!r}: {best:.3f}"


def test_blank_sheet_is_empty(cli, db, tmp_path, use_engine) -> None:
    doc, _ = recognised(cli, db, tmp_path, use_engine, "blank")
    assert set(flags(db, doc)[1]) == {"empty"}
