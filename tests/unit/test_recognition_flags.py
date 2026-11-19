"""Flags from a stored recognition result (research R-8, R-9; task T016).

`quality.recognition_flags(lines, quality, ink_share, orientation_unknown, settings)`
takes the stored `page_recognition` values and the `[recognition]` thresholds; reading
calls it, and so do `recognize` and `recognize-report` for their counts.
"""

from __future__ import annotations

from docreader.config import RecognitionSettings
from docreader.quality import (
    FLAG_NAMES,
    Flag,
    document_state,
    not_recognized_flag,
    recognition_error_flag,
    recognition_flags,
)
from docreader.stages import State

SETTINGS = RecognitionSettings()  # 0.80 / 0.60 / 0.20 / 0.003


def _lines(*items: tuple[str, float]) -> list[dict]:
    return [
        {"i": i, "text": text, "bbox": [0, 0, 1, 1], "confidence": conf}
        for i, (text, conf) in enumerate(items)
    ]


def _flags(lines, quality, ink=0.05, orientation_unknown=False, settings=SETTINGS):
    return recognition_flags(lines, quality, ink, orientation_unknown, settings)


GOOD = ("Подрядчик обязуется выполнить работы", 0.95)
LOW = ("неразборчиво", 0.40)


def test_good_page_has_no_flags() -> None:
    assert _flags(_lines(GOOD, GOOD), 0.95) == []


def test_low_page_quality_gives_the_flag_with_numbers() -> None:
    (flag,) = _flags(_lines(("текст", 0.71)), 0.71)
    assert flag == Flag("low_recognition_quality", "оценка 0,71 < 0,80")


def test_many_low_confidence_lines_give_the_flag() -> None:
    lines = _lines(*[GOOD] * 22, *[LOW] * 9)  # 9 of 31 lines, share 0.29 > 0.20
    (flag,) = _flags(lines, 0.85)
    assert flag == Flag("low_recognition_quality", "9 из 31 строки с уверенностью < 0,60")


def test_plural_after_numbers() -> None:
    lines = _lines(*[GOOD] * 8, *[LOW] * 14)  # 14 of 22
    (flag,) = _flags(lines, 0.85)
    assert flag.reason == "14 из 22 строк с уверенностью < 0,60"


def test_both_conditions_are_joined() -> None:
    lines = _lines(*[GOOD] * 2, *[LOW] * 2)
    (flag,) = _flags(lines, 0.52)
    assert flag.reason == "оценка 0,52 < 0,80; 2 из 4 строк с уверенностью < 0,60"


def test_exactly_at_the_thresholds_there_is_no_flag() -> None:
    lines = _lines(*[GOOD] * 4, LOW)  # share 0.20 == max_low_line_share
    assert _flags(lines, 0.80) == []


def test_line_confidence_exactly_at_the_threshold_is_not_low() -> None:
    assert _flags(_lines(*[("слово", 0.60)] * 3), 0.80) == []


def test_lines_without_letters_or_digits_are_left_out() -> None:
    """Form blanks and underlines are not bad recognition (spec edge case, R-9)."""
    blanks = [("__________", 0.1)] * 10 + [("— — —", 0.2), ("......", 0.3)]
    lines = _lines(*[GOOD] * 5, *blanks, LOW)  # counted: 6 lines, 1 low → 0.17
    assert _flags(lines, 0.90) == []


def test_reason_counts_only_counted_lines() -> None:
    lines = _lines(GOOD, LOW, LOW, ("__________", 0.1), ("__________", 0.1))
    (flag,) = _flags(lines, 0.85)
    assert flag.reason == "2 из 3 строк с уверенностью < 0,60"


def test_page_with_only_blank_lines_gets_no_low_quality_flag() -> None:
    lines = _lines(("__________", 0.1), ("«___» ________", 0.2))
    assert _flags(lines, None) == []


def test_no_lines_gives_no_low_quality_flag() -> None:
    codes = [f.code for f in _flags([], None)]
    assert "low_recognition_quality" not in codes


def test_thresholds_come_from_the_settings() -> None:
    strict = RecognitionSettings(page_min_quality=0.99)
    (flag,) = _flags(_lines(GOOD), 0.95, settings=strict)
    assert flag.reason == "оценка 0,95 < 0,99"
    lenient = RecognitionSettings(page_min_quality=0.5)
    assert _flags(_lines(("текст", 0.71)), 0.71, settings=lenient) == []


def test_flag_names() -> None:
    assert FLAG_NAMES["low_recognition_quality"] == "низкое качество распознавания"
    assert FLAG_NAMES["scan_no_text"] == "текст на скане не найден"


def test_low_quality_makes_the_reading_need_a_review() -> None:
    flag = Flag("low_recognition_quality", "оценка 0,71 < 0,80")
    state, reason = document_state({1: [], 2: [flag]}, read_pages=2)
    assert (state, reason) == (State.NEEDS_REVIEW, "стр. 2: низкое качество распознавания")


def test_scan_unread_reasons() -> None:
    assert not_recognized_flag("D-0003") == Flag(
        "scan_unread", "распознавание не выполнено — docreader recognize D-0003"
    )
    assert recognition_error_flag("RuntimeError: engine failed") == Flag(
        "scan_unread", "ошибка распознавания: RuntimeError: engine failed"
    )
