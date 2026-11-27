"""Page images with quote line boxes marked (moved from scripts/review_extraction.py).

Pure geometry (`pixel_box`), the lines of a quote from `text_span` / `page_text`, and the
rendering of one PDF page to a PNG with those lines highlighted.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import psycopg
from PIL import Image, ImageDraw

from docreader.ocr import display_point


def pixel_box(
    box: Sequence[float], *, crop: Sequence[float], rotation: int, scale: float
) -> tuple[float, float, float, float]:
    """`(left, bottom, right, top)` in unrotated PDF space → `(x0, y0, x1, y1)` image pixels.

    The image is the page rendered in display orientation (as PDFium renders it), top-left
    origin; the inverse of `ocr.image_box_to_pdf` without the recognition turn.
    """
    width, height = crop[2] - crop[0], crop[3] - crop[1]
    disp_h = width if rotation in (90, 270) else height
    xs, ys = [], []
    for x in (box[0], box[2]):
        for y in (box[1], box[3]):
            dx, dy = display_point(x - crop[0], y - crop[1], rotation, width, height)
            xs.append(dx * scale)
            ys.append((disp_h - dy) * scale)
    return (min(xs), min(ys), max(xs), max(ys))


def quote_lines(
    conn: psycopg.Connection, doc_id: str, start: int, end: int
) -> dict[int, list[int]]:
    lines: dict[int, list[int]] = {}
    for page, index in conn.execute(
        "SELECT page_number, line_index FROM text_span"
        " WHERE document_id = %s AND start < %s AND end_ > %s ORDER BY start",
        (doc_id, end, start),
    ):
        lines.setdefault(page, []).append(index)
    return lines


def line_boxes(
    conn: psycopg.Connection, doc_id: str, page: int, indexes: Sequence[int]
) -> tuple[int, list[list[float]]]:
    row = conn.execute(
        "SELECT rotation, lines FROM page_text WHERE document_id = %s AND page_number = %s",
        (doc_id, page),
    ).fetchone()
    if row is None:
        return 0, []
    rotation, lines = row
    wanted = set(indexes)
    return rotation, [ln["bbox"] for ln in lines if ln.get("i") in wanted]


def render_page(
    pdf: Any, page: int, rotation: int, boxes: list[list[float]], path: Path, *, dpi: int
) -> dict[str, Any]:
    """Render page `page` (1-based) at `dpi` with the boxes marked, save a PNG at `path`."""
    pdf_page = pdf[page - 1]
    crop = pdf_page.get_cropbox()
    scale = dpi / 72
    image = pdf_page.render(scale=scale).to_pil().convert("RGB")
    w, h = image.size
    pixels = []
    for box in boxes:
        x0, y0, x1, y1 = pixel_box(box, crop=crop, rotation=rotation, scale=scale)
        x0, y0 = max(0.0, x0 - 3), max(0.0, y0 - 3)
        x1, y1 = min(float(w), x1 + 3), min(float(h), y1 + 3)
        if x1 > x0 and y1 > y0:
            pixels.append([round(x0, 1), round(y0, 1), round(x1, 1), round(y1, 1)])
    overlay = image.copy()
    draw = ImageDraw.Draw(overlay)
    for x0, y0, x1, y1 in pixels:
        draw.rectangle((x0, y0, x1, y1), fill=(255, 220, 0))
    marked = Image.blend(image, overlay, 0.35)
    draw = ImageDraw.Draw(marked)
    for x0, y0, x1, y1 in pixels:
        draw.rectangle((x0, y0, x1, y1), outline=(220, 0, 0), width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    marked.save(path, "PNG", optimize=True)
    return {"file": "", "page": page, "width": w, "height": h, "boxes": pixels}
