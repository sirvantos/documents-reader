"""Native engine results → EngineLine, without importing any engine (research R-3, T031).

The adapters themselves run only on the analyst's Mac (quickstart Б1, level 3 tests);
here only their pure conversion helpers are checked on hand-made records.
"""

from __future__ import annotations

import pytest

from docreader import ocr_engines
from docreader.ocr import EngineLine
from docreader.ocr_engines import tesseract_lines, vision_lines


def test_queue_one_engines_are_registered() -> None:
    assert {"tesseract", "apple_vision"} <= set(ocr_engines.ENGINES)


def test_tesseract_lines_rescale_confidence_and_keep_boxes() -> None:
    items = [
        ("1.1. Подрядчик обязуется\n", 91.5, (100, 200, 900, 240)),
        ("ИНН 7701234567\n", 64.0, (100, 260, 500, 300)),
    ]
    assert tesseract_lines(items) == (
        EngineLine("1.1. Подрядчик обязуется", (100, 200, 900, 240), pytest.approx(0.915)),
        EngineLine("ИНН 7701234567", (100, 260, 500, 300), 0.64),
    )


def test_tesseract_lines_skip_empty_text_and_clamp_confidence() -> None:
    items = [
        ("  \n", 95.0, (0, 0, 1, 1)),
        ("текст", 120.0, (0, 0, 5, 5)),
        ("шум", -1.0, (0, 0, 5, 5)),
    ]
    lines = tesseract_lines(items)
    assert [ln.text for ln in lines] == ["текст", "шум"]
    assert [ln.confidence for ln in lines] == [1.0, 0.0]


def test_text_is_not_corrected() -> None:
    (line,) = tesseract_lines([("Подрядчнк  обязуется", 50.0, (0, 0, 9, 9))])
    assert line.text == "Подрядчнк  обязуется"


def test_vision_boxes_are_flipped_to_a_top_left_origin() -> None:
    # Vision: normalised (x, y, w, h), origin bottom-left
    items = [("Договор подряда", 0.98, (0.1, 0.8, 0.5, 0.05))]
    (line,) = vision_lines(items, size=(1000, 2000))
    assert line.text == "Договор подряда"
    assert line.confidence == pytest.approx(0.98)
    assert line.box == pytest.approx((100.0, 300.0, 600.0, 400.0))


def test_vision_lines_skip_empty_text() -> None:
    assert vision_lines([(" ", 1.0, (0, 0, 1, 1))], size=(10, 10)) == ()
