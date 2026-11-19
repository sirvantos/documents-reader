"""Rendering with the real PDFium and mapping pixels back to the page (R-5, task T013).

No recognition engine: a black rectangle is drawn at a known place, the page is rendered
by `ocr.render_page`, the rectangle is found by its dark pixels, and its pixel box is
mapped back with `ocr.image_box_to_pdf`. This also confirms that PDFium applies /Rotate
and the CropBox when it renders.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest
from reportlab.pdfgen import canvas

from docreader.ocr import image_box_to_pdf, render_page

# left, bottom, right, top in PDF points; inside the page whatever its orientation
# (reportlab swaps the MediaBox sides of a page rotated by 90 or 270 degrees)
RECT = (100.0, 300.0, 220.0, 360.0)
DPI = 100


def _pdf(path: Path, *, rotation: int = 0, crop: tuple[float, float, float, float] | None = None):
    c = canvas.Canvas(str(path), pagesize=(595, 842), invariant=1)
    if crop is not None:
        c.setCropBox(crop)
    c.setPageRotation(rotation)
    left, bottom, right, top = RECT
    c.setFillColorRGB(0, 0, 0)
    c.rect(left, bottom, right - left, top - bottom, stroke=0, fill=1)
    c.showPage()
    c.save()
    return path


def _found_box(path: Path) -> tuple[tuple[float, float, float, float], tuple]:
    pdf = pdfium.PdfDocument(str(path))
    try:
        page = pdf[0]
        try:
            image = render_page(page, DPI)
            crop = tuple(page.get_cropbox())
            rotation = page.get_rotation() % 360
        finally:
            page.close()
    finally:
        pdf.close()
    dark = image.point(lambda v: 255 if v < 128 else 0)
    bbox = dark.getbbox()
    assert bbox is not None, "the rectangle was not rendered"
    got = image_box_to_pdf(bbox, scale=DPI / 72, turn=0, rotation=rotation, crop=crop)
    return got, (rotation, crop)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rendered_rectangle_maps_back_for_every_rotation(tmp_path: Path, rotation: int) -> None:
    got, (seen_rotation, _) = _found_box(_pdf(tmp_path / f"r{rotation}.pdf", rotation=rotation))
    assert seen_rotation == rotation
    assert got == pytest.approx(RECT, abs=1.0)


@pytest.mark.parametrize("rotation", [0, 90])
def test_rendered_rectangle_maps_back_with_a_crop_box_offset(
    tmp_path: Path, rotation: int
) -> None:
    crop = (20.0, 30.0, 520.0, 560.0)
    got, (_, seen_crop) = _found_box(
        _pdf(tmp_path / f"c{rotation}.pdf", rotation=rotation, crop=crop)
    )
    assert seen_crop == pytest.approx(crop)
    assert got == pytest.approx(RECT, abs=1.0)
