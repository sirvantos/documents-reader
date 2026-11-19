"""Page quality, ink share, result fingerprint, orientation score (R-6, R-9…R-11; T007)."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from docreader.ocr import (
    EngineLine,
    ink_share,
    orientation_score,
    page_quality,
    result_sha256,
)


def _line(text: str, confidence: float) -> EngineLine:
    return EngineLine(text=text, box=(0, 0, 10, 10), confidence=confidence)


# --- page_quality (R-9) ----------------------------------------------------------------


def test_quality_is_mean_confidence_weighted_by_non_space_chars() -> None:
    lines = [_line("абв гд", 1.0), _line("ежз", 0.4)]  # 5 and 3 non-space chars
    assert page_quality(lines) == pytest.approx((5 * 1.0 + 3 * 0.4) / 8)


def test_quality_without_lines_is_none() -> None:
    assert page_quality([]) is None


@pytest.mark.parametrize("blank", ["__________", "— — —", "......", "_ _ _", "«___»"])
def test_lines_without_letters_or_digits_are_left_out(blank: str) -> None:
    good = [_line("Подрядчик обязуется", 0.95)]
    assert page_quality([*good, _line(blank, 0.1)]) == pytest.approx(page_quality(good))


def test_only_blank_lines_give_no_quality() -> None:
    assert page_quality([_line("__________", 0.2), _line("———", 0.3)]) is None


def test_form_line_with_digits_is_counted() -> None:
    lines = [_line("«___» __________ 2024 г.", 0.5)]
    assert page_quality(lines) == pytest.approx(0.5)


# --- ink_share (R-10) --------------------------------------------------------------------


def test_white_image_has_no_ink() -> None:
    assert ink_share(Image.new("L", (1000, 1000), 255)) == 0.0


def test_black_square_share_of_the_inner_area() -> None:
    image = Image.new("L", (1000, 1000), 255)
    ImageDraw.Draw(image).rectangle((450, 450, 549, 549), fill=0)  # 100 × 100 px
    margin = 30  # 3% of 1000 on each side
    assert ink_share(image) == pytest.approx(100 * 100 / (1000 - 2 * margin) ** 2)


def test_black_border_of_three_percent_is_ignored() -> None:
    image = Image.new("L", (1000, 1000), 0)
    ImageDraw.Draw(image).rectangle((30, 30, 969, 969), fill=255)
    assert ink_share(image) == 0.0


def test_grey_lighter_than_half_is_not_ink() -> None:
    assert ink_share(Image.new("L", (200, 200), 200)) == 0.0
    assert ink_share(Image.new("L", (200, 200), 60)) == pytest.approx(1.0)


def test_rgb_image_is_converted_to_grey() -> None:
    assert ink_share(Image.new("RGB", (200, 200), (0, 0, 0))) == pytest.approx(1.0)


# --- result_sha256 (R-11) ------------------------------------------------------------------

STORED = [
    {"i": 0, "text": "1.1. Подрядчик", "bbox": [51.0, 758.2, 374.1, 769.0], "confidence": 0.962},
    {"i": 1, "text": "обязуется", "bbox": [51.0, 740.0, 120.0, 751.0], "confidence": 0.9},
]


def _sha(lines=STORED, turn=0, orientation_unknown=False, quality=0.93, ink=0.05) -> str:
    return result_sha256(lines, turn, orientation_unknown, quality, ink)


def test_fingerprint_is_stable_hex() -> None:
    first = _sha()
    assert first == _sha([dict(line) for line in STORED])
    assert len(first) == 64 and set(first) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    "change",
    [
        {"lines": [{**STORED[0], "text": "1.1. Подрядчиk"}, STORED[1]]},
        {"lines": [{**STORED[0], "bbox": [51.0, 758.2, 374.2, 769.0]}, STORED[1]]},
        {"lines": [{**STORED[0], "confidence": 0.964}, STORED[1]]},
        {"lines": STORED[:1]},
        {"turn": 180},
        {"orientation_unknown": True},
        {"quality": 0.94},
        {"quality": None},
        {"ink": 0.06},
        {"ink": None},
    ],
)
def test_fingerprint_changes_with_the_result(change) -> None:
    assert _sha(**change) != _sha()


@pytest.mark.parametrize(
    "noise",
    [
        {"lines": [{**STORED[0], "bbox": [51.001, 758.2, 374.1, 769.0]}, STORED[1]]},
        {"lines": [{**STORED[0], "confidence": 0.9621}, STORED[1]]},
        {"quality": 0.930001},
        {"ink": 0.050001},
    ],
)
def test_fingerprint_ignores_noise_below_the_rounding(noise) -> None:
    assert _sha(**noise) == _sha()


def test_fingerprint_of_empty_result() -> None:
    assert _sha([], quality=None, ink=None) == _sha([], quality=None, ink=None)
    assert _sha([], quality=None, ink=None) != _sha()


# --- orientation_score (R-6) ------------------------------------------------------------


def test_russian_words_score_higher_than_garbage() -> None:
    good = [_line("Подрядчик обязуется выполнить работы", 0.6)]
    garbage = [_line("Пдрдчк бзтс вплнть рбт", 0.9)]
    assert orientation_score(good) > orientation_score(garbage)


def test_orientation_score_without_words_is_zero() -> None:
    assert orientation_score([]) == 0.0
    assert orientation_score([_line("____ 123", 0.9)]) == 0.0
