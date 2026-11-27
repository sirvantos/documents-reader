"""docreader.pageimage: pixel boxes and rendering one page to a PNG."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from docreader.pageimage import pixel_box, render_page
from docreader.pdfpages import open_pdf
from tests.synthetic.make_pdfs import make_contract_ru


def test_pixel_box_upright_page() -> None:
    box = pixel_box((100, 700, 200, 720), crop=(0, 0, 600, 800), rotation=0, scale=2)
    assert box == (200, 160, 400, 200)


def test_render_page_writes_a_png(tmp_path: Path) -> None:
    pdf_path = make_contract_ru(tmp_path / "contract.pdf", pages=1)
    pdf = open_pdf(pdf_path)
    try:
        out = tmp_path / "pages" / "p1.png"
        info = render_page(pdf, 1, 0, [[50.0, 700.0, 200.0, 720.0]], out, dpi=72)
    finally:
        pdf.close()
    assert out.is_file() and out.stat().st_size > 0
    with Image.open(out) as image:
        assert image.size == (info["width"], info["height"])
    assert len(info["boxes"]) == 1
