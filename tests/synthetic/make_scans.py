"""Synthetic scanned PDFs for auto-tests (research R-13, task T011).

A scan page is drawn with reportlab (DejaVu Sans, texts of make_pdfs), rendered by
pypdfium2 at 200 dpi, altered with Pillow and embedded into a new PDF as one full-page
picture with no text layer. Text pages are drawn directly as in make_pdfs.

Each generator `make_scan_<variant>(path, ...)` writes the PDF and returns its path. Next to
it it writes `<stem>.truth.json`: for every page its kind ("scan" or "text"), the exact line
texts in reading order and each line's box `[left, bottom, right, top]` in PDF page
coordinates of the drawn text (unrotated page space, as in `page_text.lines[].bbox`).

Output is deterministic: the same arguments give byte-identical PDF and truth files.
Bump SCAN_GENERATOR_VERSION on any change of the generator; older recordings go stale.

Run the set for manual checking:
    uv run python -m tests.synthetic.make_scans <folder>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageChops
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from tests.synthetic.make_pdfs import (
    _CYRILLIC_FONT,
    CONTRACT_RU_PAGES,
    PAGE_H,
    PAGE_W,
    _pdf,
    _register_cyrillic_font,
    _ru_page,
    make_contract_ru,
    ru_line_baselines,
)

SCAN_GENERATOR_VERSION = 1
SCAN_DPI = 200

_TEXT_SIZE = 11  # same size and leading as the defaults of make_pdfs._ru_page
_TEXT_LEADING = 16
_TEXT_X = 72
_DESCENT = 0.2  # box bottom = baseline - 0.2 * size
_ASCENT = 0.8  # box top = baseline + 0.8 * size

_FADE = 0.45  # contrast factor of the faded variant: 1.0 keeps the page as drawn
_NOISE_SCALE = 0.25  # spread of the noise around mid grey
_NOISE_SEED = 1307  # page n of a noisy variant uses random.Random(_NOISE_SEED + n)

_REQ_LEFT_X = 50
_REQ_RIGHT_X = 320
_REQ_HEADING = "Адреса и платежные реквизиты Сторон"
_REQ_CUSTOMER = (
    "Заказчик:",
    "ООО «Альфа»",
    "ИНН 7701234567",
    "КПП 770101001",
    "ОГРН 1027700000001",
    "Банк: ПАО «Тестбанк»",
    "р/с 40702810900000000001",
    "к/с 30101810400000000225",
    "БИК 044525000",
)
_REQ_CONTRACTOR = (
    "Подрядчик:",
    "ООО «Бета»",
    "ИНН 7702345678",
    "КПП 770201001",
    "ОГРН 1027700000002",
    "Банк: АО «Пробанк»",
    "р/с 40702810900000000002",
    "к/с 30101810400000000226",
    "БИК 044525001",
)


@dataclass(frozen=True)
class TruthLine:
    text: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class _Page:
    """One page of a variant: how it is drawn, whether it is a scan, and how it is altered."""

    draw: Callable[[canvas.Canvas], list[TruthLine]]
    scan: bool
    alter: Callable[[Image.Image, random.Random], Image.Image] | None = None
    rotate: int = 0  # /Rotate of the page as a whole; 0 leaves it out


# --- geometry and drawing ---------------------------------------------------------


def _text_box(text: str, x: float, baseline: float) -> tuple[float, float, float, float]:
    _register_cyrillic_font()
    width = stringWidth(text, _CYRILLIC_FONT, _TEXT_SIZE)
    return (
        round(x, 2),
        round(baseline - _DESCENT * _TEXT_SIZE, 2),
        round(x + width, 2),
        round(baseline + _ASCENT * _TEXT_SIZE, 2),
    )


def _draw_column(
    c: canvas.Canvas, lines: tuple[str, ...], x: float, y_top: float
) -> list[TruthLine]:
    """Draws the lines of one column at x from y_top downwards; returns their truth."""
    _ru_page(c, lines, x=x, y_top=y_top, size=_TEXT_SIZE, leading=_TEXT_LEADING)
    baselines = ru_line_baselines(len(lines), y_top=y_top, leading=_TEXT_LEADING)
    return [
        TruthLine(text, _text_box(text, x, baseline))
        for text, baseline in zip(lines, baselines, strict=True)
    ]


def _contract_page(index: int) -> Callable[[canvas.Canvas], list[TruthLine]]:
    """Draw function for page `index` of CONTRACT_RU_PAGES (taken modulo the page count)."""
    lines = CONTRACT_RU_PAGES[index % len(CONTRACT_RU_PAGES)]

    def draw(c: canvas.Canvas) -> list[TruthLine]:
        return _draw_column(c, lines, _TEXT_X, PAGE_H - 72)

    return draw


def _requisites_page(c: canvas.Canvas) -> list[TruthLine]:
    """Heading across the page, then the customer column and the contractor column."""
    top = PAGE_H - 72
    truth = _draw_column(c, (_REQ_HEADING,), _REQ_LEFT_X, top)
    y = top - 3 * _TEXT_LEADING  # one empty line after the heading
    truth += _draw_column(c, _REQ_CUSTOMER, _REQ_LEFT_X, y)
    truth += _draw_column(c, _REQ_CONTRACTOR, _REQ_RIGHT_X, y)
    return truth


# --- scan pipeline ----------------------------------------------------------------


def _source_pdf(draw: Callable[[canvas.Canvas], list[TruthLine]]) -> tuple[bytes, list[TruthLine]]:
    """One-page PDF with the drawn page, and the truth of its lines."""
    truth: list[TruthLine] = []

    def paged(c: canvas.Canvas) -> None:
        truth.extend(draw(c))
        c.showPage()

    return _pdf(paged), truth


def _render(source: bytes) -> Image.Image:
    """The only page of `source` as 8-bit grey at SCAN_DPI, as pypdfium2 renders it."""
    document = pdfium.PdfDocument(source)
    try:
        bitmap = document[0].render(scale=SCAN_DPI / 72)
        return bitmap.to_pil().convert("L")
    finally:
        document.close()


def _gaussian_noise(size: tuple[int, int], rng: random.Random) -> Image.Image:
    """Noise around mid grey: the sum of four uniform layers (close to Gaussian), seeded."""
    width, height = size
    layers = [Image.frombytes("L", size, rng.randbytes(width * height)) for _ in range(4)]
    pairs = [
        ImageChops.add(layers[0], layers[1], scale=2),
        ImageChops.add(layers[2], layers[3], scale=2),
    ]
    total = ImageChops.add(pairs[0], pairs[1], scale=2)
    return total.point(lambda v: round(128 + (v - 128) * _NOISE_SCALE))


def _faded_noisy(image: Image.Image, rng: random.Random) -> Image.Image:
    faded = image.point(lambda v: round(255 - (255 - v) * _FADE))
    return ImageChops.add(faded, _gaussian_noise(image.size, rng), scale=1, offset=-128)


def _write_truth(path: Path, variant: str, pages: list[dict[str, object]]) -> None:
    payload = {
        "generator_version": SCAN_GENERATOR_VERSION,
        "variant": variant,
        "pages": pages,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    path.with_name(f"{path.stem}.truth.json").write_text(text, encoding="utf-8")


def _build(path: str | Path, variant: str, pages: list[_Page]) -> Path:
    """Writes the PDF of `pages` and its truth file; returns the PDF path."""
    target = Path(path)
    truth_pages: list[dict[str, object]] = []

    def draw_document(c: canvas.Canvas) -> None:
        for number, spec in enumerate(pages, start=1):
            if spec.scan:
                source, lines = _source_pdf(spec.draw)
                image = _render(source)
                if spec.alter is not None:
                    image = spec.alter(image, random.Random(_NOISE_SEED + number))
                c.drawImage(ImageReader(image), 0, 0, width=PAGE_W, height=PAGE_H)
                kind = "scan"
            else:
                lines = spec.draw(c)
                kind = "text"
            if spec.rotate:
                c.setPageRotation(spec.rotate)
            c.showPage()
            truth_pages.append(
                {
                    "page": number,
                    "kind": kind,
                    "lines": [{"text": line.text, "bbox": list(line.bbox)} for line in lines],
                }
            )

    target.write_bytes(_pdf(draw_document))
    _write_truth(target, variant, truth_pages)
    return target


def _check_pages(pages: int) -> None:
    if not 1 <= pages <= len(CONTRACT_RU_PAGES):
        raise ValueError(f"pages must be from 1 to {len(CONTRACT_RU_PAGES)}, got {pages}")


# --- variants ---------------------------------------------------------------------


def make_scan_clean(path: str | Path, pages: int = 2) -> Path:
    """`pages` scanned contract pages (the first ones of CONTRACT_RU_PAGES), no alteration."""
    _check_pages(pages)
    specs = [_Page(_contract_page(n), scan=True) for n in range(pages)]
    return _build(path, "clean", specs)


def make_scan_mixed(path: str | Path) -> Path:
    """Text, scan, text, scan: contract pages as text layers between scanned ones."""
    specs = [
        _Page(_contract_page(0), scan=False),
        _Page(_contract_page(1), scan=True),
        _Page(_contract_page(2), scan=False),
        _Page(_contract_page(0), scan=True),
    ]
    return _build(path, "mixed", specs)


def make_scan_faded_noisy(path: str | Path) -> Path:
    """Two scanned contract pages with lower contrast and seeded noise."""
    specs = [_Page(_contract_page(n), scan=True, alter=_faded_noisy) for n in range(2)]
    return _build(path, "faded_noisy", specs)


def make_scan_page_rotate_90(path: str | Path) -> Path:
    """One scanned contract page whose PDF page has /Rotate 90; truth stays unrotated."""
    specs = [_Page(_contract_page(0), scan=True, rotate=90)]
    return _build(path, "page_rotate_90", specs)


def make_scan_requisites_two_columns(path: str | Path) -> Path:
    """One scanned page: requisites of both parties side by side, left column first."""
    specs = [_Page(_requisites_page, scan=True)]
    return _build(path, "requisites_two_columns", specs)


# --- command line -----------------------------------------------------------------


def make_all(directory: str | Path) -> list[Path]:
    """Writes every scan variant and the text-only contract into the folder."""
    root = Path(directory)
    return [
        make_scan_clean(root / "scan_clean.pdf"),
        make_scan_mixed(root / "scan_mixed.pdf"),
        make_scan_faded_noisy(root / "scan_faded_noisy.pdf"),
        make_scan_page_rotate_90(root / "scan_page_rotate_90.pdf"),
        make_scan_requisites_two_columns(root / "scan_requisites_two_columns.pdf"),
        make_contract_ru(root / "contract_ru.pdf"),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Записать синтетические сканы и текстовый договор."
    )
    parser.add_argument("directory", type=Path, help="папка, куда записать файлы")
    args = parser.parse_args(argv)
    args.directory.mkdir(parents=True, exist_ok=True)
    for path in make_all(args.directory):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
