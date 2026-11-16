"""Opening PDFs and per-page metrics for the page kind rule (research R-1, R-2).

Metrics per page:
- char_count: non-whitespace characters of the text layer;
- image_coverage: share of the CropBox covered by the union of all image bounds,
  including images nested in form XObjects;
- invisible_text_share: share of text objects drawn in render mode 3 (diagnostics only).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

Rect = tuple[float, float, float, float]  # (left, bottom, right, top)
Matrix = tuple[float, float, float, float, float, float]  # (a, b, c, d, e, f)

MAX_OBJECT_DEPTH = 16

KIND_TEXT = "text"
KIND_SCAN = "scan"
KIND_SCAN_WITH_TEXT = "scan_with_text"
KINDS = (KIND_TEXT, KIND_SCAN, KIND_SCAN_WITH_TEXT)

REASONS = {
    "encrypted": "защищён паролем",
    "damaged": "файл повреждён или не читается",
    "no_pages": "в файле нет страниц",
}

_TEXT_RENDER_INVISIBLE = 3


class PdfOpenError(Exception):
    """The file cannot be registered; `reason_code` is one of REASONS."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        super().__init__(f"{reason_code}: {detail}" if detail else reason_code)
        self.reason_code = reason_code
        self.reason = REASONS[reason_code]


@dataclass(frozen=True)
class PageMetrics:
    page_number: int
    char_count: int
    image_coverage: float
    invisible_text_share: float | None


class Thresholds(Protocol):
    text_min_chars: int
    full_image_coverage: float


# --- geometry ------------------------------------------------------------------------


def union_area(rects: Iterable[Rect], clip: Rect) -> float:
    """Area of the union of `rects` inside `clip` (sweep over x slabs)."""
    cl, cb, cr, ct = clip
    clipped = []
    for left, bottom, right, top in rects:
        left, right = max(min(left, right), cl), min(max(left, right), cr)
        bottom, top = max(min(bottom, top), cb), min(max(bottom, top), ct)
        if right > left and top > bottom:
            clipped.append((left, bottom, right, top))
    if not clipped:
        return 0.0

    xs = sorted({x for r in clipped for x in (r[0], r[2])})
    area = 0.0
    for x0, x1 in zip(xs, xs[1:]):
        spans = sorted((r[1], r[3]) for r in clipped if r[0] <= x0 and r[2] >= x1)
        covered, cur_lo, cur_hi = 0.0, None, None
        for lo, hi in spans:
            if cur_hi is None or lo > cur_hi:
                if cur_hi is not None:
                    covered += cur_hi - cur_lo
                cur_lo, cur_hi = lo, hi
            else:
                cur_hi = max(cur_hi, hi)
        if cur_hi is not None:
            covered += cur_hi - cur_lo
        area += covered * (x1 - x0)
    return area


def _apply(m: Matrix, x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _transform_rect(rect: Rect, matrices: Sequence[Matrix]) -> Rect:
    """Map a rect through `matrices` (innermost first) and return its bounding box."""
    left, bottom, right, top = rect
    points = [(left, bottom), (left, top), (right, bottom), (right, top)]
    for m in matrices:
        points = [_apply(m, x, y) for x, y in points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


# --- opening and metrics -----------------------------------------------------------------


_SENTINEL_PATH = b"/nonexistent/docreader-error-sentinel.pdf"


def _reset_pdfium_error() -> None:
    """Set PDFium's global last error to FPDF_ERR_FILE.

    FPDF_GetLastError is process-global and is not reset by a successful load.
    A document without pages is refused without setting any error, so without this
    reset it would inherit the code of whichever file failed before it.
    """
    handle = pdfium_c.FPDF_LoadDocument(_SENTINEL_PATH, None)
    if handle:  # pragma: no cover - the sentinel path never exists
        pdfium_c.FPDF_CloseDocument(handle)


def open_pdf(path: str | Path) -> pdfium.PdfDocument:
    # Loaded from memory, so a failure of the real load never sets FPDF_ERR_FILE:
    # if the sentinel code survives, the load failed without a reason of its own.
    data = Path(path).read_bytes()
    _reset_pdfium_error()
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        code = getattr(exc, "err_code", None)
        if code == pdfium_c.FPDF_ERR_PASSWORD:
            raise PdfOpenError("encrypted") from exc
        if code == pdfium_c.FPDF_ERR_FILE:
            # PDFium refuses a structurally valid document without pages and sets
            # no error (checked on a hand-built PDF with `/Kids [] /Count 0`).
            raise PdfOpenError("no_pages") from exc
        raise PdfOpenError("damaged", str(exc)) from exc
    if len(pdf) == 0:
        pdf.close()
        raise PdfOpenError("no_pages")
    return pdf


def _page_metrics(page: pdfium.PdfPage, page_number: int) -> PageMetrics:
    textpage = page.get_textpage()
    try:
        text = textpage.get_text_range()
    finally:
        textpage.close()
    char_count = sum(1 for ch in text if not ch.isspace())

    image_rects: list[Rect] = []
    text_objects = invisible = 0
    # Cumulative stack of form matrices: form_stack[i] is the matrix of the form
    # object at nesting level i that encloses the objects at level i + 1.
    form_stack: list[Matrix] = []
    for obj in page.get_objects(max_depth=MAX_OBJECT_DEPTH):
        level = obj.level
        del form_stack[level:]
        if obj.type == pdfium_c.FPDF_PAGEOBJ_FORM:
            form_stack.append(tuple(obj.get_matrix().get()))
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            # Bounds of nested objects are in their form's space: map them to page space.
            image_rects.append(_transform_rect(obj.get_bounds(), list(reversed(form_stack))))
        elif obj.type == pdfium_c.FPDF_PAGEOBJ_TEXT:
            text_objects += 1
            if pdfium_c.FPDFTextObj_GetTextRenderMode(obj.raw) == _TEXT_RENDER_INVISIBLE:
                invisible += 1

    crop = page.get_cropbox()
    crop_area = (crop[2] - crop[0]) * (crop[3] - crop[1])
    coverage = union_area(image_rects, crop) / crop_area if crop_area > 0 else 0.0
    return PageMetrics(
        page_number=page_number,
        char_count=char_count,
        image_coverage=min(max(coverage, 0.0), 1.0),
        invisible_text_share=(invisible / text_objects) if text_objects else None,
    )


def page_metrics(pdf: pdfium.PdfDocument) -> list[PageMetrics]:
    result = []
    for index in range(len(pdf)):
        try:
            page = pdf[index]
        except pdfium.PdfiumError as exc:
            raise PdfOpenError("damaged", f"page {index + 1}: {exc}") from exc
        try:
            result.append(_page_metrics(page, index + 1))
        except pdfium.PdfiumError as exc:
            raise PdfOpenError("damaged", f"page {index + 1}: {exc}") from exc
        finally:
            page.close()
    return result


def analyse_pdf(path: str | Path) -> list[PageMetrics]:
    """Open the file, compute metrics of every page and close it again."""
    pdf = open_pdf(path)
    try:
        return page_metrics(pdf)
    finally:
        pdf.close()


# --- page kind rule (research R-2) ------------------------------------------------------


def classify(metrics: PageMetrics, thresholds: Thresholds) -> str:
    """Minimal version of the rule: «есть текст» → text, otherwise scan."""
    if metrics.char_count < thresholds.text_min_chars:
        return KIND_SCAN
    return KIND_TEXT
