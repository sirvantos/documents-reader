"""Engine pixel boxes → PDF page boxes (research R-5, task T007).

Conventions under test:
- the page is rendered in display orientation (PDFium applies /Rotate) at `scale`
  pixels per point; the image origin is top-left;
- before recognition the image may be turned `turn` degrees **clockwise**;
- the result is `(left, bottom, right, top)` in unrotated PDF page space, including the
  CropBox origin — the same space as `page_text.lines[].bbox`.
"""

from __future__ import annotations

import pytest

from docreader.ocr import image_box_to_pdf

W, H = 595.0, 842.0
CROP = (0.0, 0.0, W, H)
SCALE = 2.0
BOX = (100.0, 200.0, 300.0, 260.0)  # pixels in the image as rendered (turn 0)


def _approx(box):
    return pytest.approx(box, abs=1e-6)


def _image_size(rotation: int, turn: int) -> tuple[float, float]:
    dw, dh = (W, H) if rotation in (0, 180) else (H, W)
    iw, ih = dw * SCALE, dh * SCALE
    return (iw, ih) if turn in (0, 180) else (ih, iw)


def _turn_box(box, turn: int, size: tuple[float, float]):
    """Where `box` of the rendered image (size `size`) lands after turning it clockwise."""
    w, h = size
    corners = [(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
    if turn == 0:
        moved = corners
    elif turn == 90:
        moved = [(h - y, x) for x, y in corners]
    elif turn == 180:
        moved = [(w - x, h - y) for x, y in corners]
    else:  # 270
        moved = [(y, w - x) for x, y in corners]
    xs, ys = [p[0] for p in moved], [p[1] for p in moved]
    return (min(xs), min(ys), max(xs), max(ys))


@pytest.mark.parametrize(
    ("rotation", "expected"),
    [
        (0, (50.0, 712.0, 150.0, 742.0)),
        (90, (100.0, 50.0, 130.0, 150.0)),
        (180, (445.0, 100.0, 545.0, 130.0)),
        (270, (465.0, 692.0, 495.0, 792.0)),
    ],
)
def test_inner_box_for_each_page_rotation(rotation: int, expected) -> None:
    got = image_box_to_pdf(BOX, scale=SCALE, turn=0, rotation=rotation, crop=CROP)
    assert got == _approx(expected)


@pytest.mark.parametrize(
    ("turn", "turned_box"),
    [
        (90, (1424.0, 100.0, 1484.0, 300.0)),
        (180, (890.0, 1424.0, 1090.0, 1484.0)),
        (270, (200.0, 890.0, 260.0, 1090.0)),
    ],
)
def test_turned_image_maps_back_to_the_same_place(turn: int, turned_box) -> None:
    got = image_box_to_pdf(turned_box, scale=SCALE, turn=turn, rotation=0, crop=CROP)
    assert got == _approx((50.0, 712.0, 150.0, 742.0))


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("turn", [0, 90, 180, 270])
def test_every_rotation_and_turn_combination(rotation: int, turn: int) -> None:
    rendered = _image_size(rotation, 0)
    turned = _turn_box(BOX, turn, rendered)
    straight = image_box_to_pdf(BOX, scale=SCALE, turn=0, rotation=rotation, crop=CROP)

    got = image_box_to_pdf(turned, scale=SCALE, turn=turn, rotation=rotation, crop=CROP)

    assert got == _approx(straight)
    left, bottom, right, top = got
    assert left < right and bottom < top
    assert 0 <= left and right <= W and 0 <= bottom and top <= H


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("turn", [0, 90, 180, 270])
def test_whole_image_is_the_whole_page(rotation: int, turn: int) -> None:
    iw, ih = _image_size(rotation, turn)
    got = image_box_to_pdf((0, 0, iw, ih), scale=SCALE, turn=turn, rotation=rotation, crop=CROP)
    assert got == _approx(CROP)


def test_crop_box_origin_shifts_the_result() -> None:
    crop = (10.0, 20.0, 10.0 + W, 20.0 + H)
    got = image_box_to_pdf(BOX, scale=SCALE, turn=0, rotation=0, crop=crop)
    assert got == _approx((60.0, 732.0, 160.0, 762.0))


def test_crop_box_origin_with_rotation() -> None:
    crop = (10.0, 20.0, 10.0 + W, 20.0 + H)
    got = image_box_to_pdf(BOX, scale=SCALE, turn=0, rotation=90, crop=crop)
    assert got == _approx((110.0, 70.0, 140.0, 170.0))


def test_scale_from_dpi() -> None:
    # 300 dpi: 300 / 72 pixels per point
    scale = 300 / 72
    got = image_box_to_pdf(
        (0, 0, 300.0, 300.0), scale=scale, turn=0, rotation=0, crop=CROP
    )
    assert got == _approx((0.0, H - 72.0, 72.0, H))
