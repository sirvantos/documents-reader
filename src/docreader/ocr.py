"""The recognition engine interface and pure image/coordinate helpers (feature 13).

The rest of the code knows only these types (contracts/engine.md, research R-3). No
engine library is imported here; adapters live in `ocr_engines.py`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from PIL import Image

PixelBox = tuple[float, float, float, float]  # image pixels: left, top, right, bottom


@dataclass(frozen=True)
class EngineLine:
    """One line (or fragment of a line) as the engine gave it."""

    text: str  # never corrected (FR-010)
    box: PixelBox  # origin top-left of the image passed in
    confidence: float  # 0..1; the adapter rescales the engine's own scale


@dataclass(frozen=True)
class EngineOutput:
    lines: tuple[EngineLine, ...]  # any order; reading builds the reading order
    orientation: int | None = None  # 0/90/180/270 clockwise the text is turned, if detected


class RecognitionEngine(Protocol):
    """Image of one page → lines with boxes and confidence."""

    name: str  # key in ocr_engines.ENGINES
    version: str  # engine and language model version

    def recognize(self, image: Image.Image) -> EngineOutput: ...


def display_point(
    x: float, y: float, rotation: int, width: float, height: float
) -> tuple[float, float]:
    """Unrotated PDF page space → display space (the page with /Rotate applied)."""
    if rotation == 90:
        return y, width - x
    if rotation == 180:
        return width - x, height - y
    if rotation == 270:
        return height - y, x
    return x, y


def pdf_point(
    x: float, y: float, rotation: int, width: float, height: float
) -> tuple[float, float]:
    """Display space → unrotated PDF page space; the inverse of `display_point`."""
    if rotation == 90:
        return width - y, x
    if rotation == 180:
        return width - x, height - y
    if rotation == 270:
        return y, height - x
    return x, y


def render_page(pdf_page: Any, dpi: int) -> Image.Image:
    """Render a page in display orientation as a grey image; nothing is written to disk."""
    return pdf_page.render(scale=dpi / 72).to_pil().convert("L")


def image_box_to_pdf(
    box: PixelBox,
    *,
    scale: float,
    turn: int,
    rotation: int,
    crop: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Engine pixel box → `(left, bottom, right, top)` in unrotated PDF space (R-5).

    `turn` is the clockwise turn applied to the rendered image before recognition;
    `crop` is the CropBox `(left, bottom, right, top)`.
    """
    width = crop[2] - crop[0]
    height = crop[3] - crop[1]
    disp_w, disp_h = (height, width) if rotation in (90, 270) else (width, height)
    img_w, img_h = disp_w * scale, disp_h * scale  # the image as rendered, before turning
    xs: list[float] = []
    ys: list[float] = []
    for u in (box[0], box[2]):
        for v in (box[1], box[3]):
            # undo the clockwise turn
            if turn == 90:
                x, y = v, img_h - u
            elif turn == 180:
                x, y = img_w - u, img_h - v
            elif turn == 270:
                x, y = img_w - v, u
            else:
                x, y = u, v
            px, py = pdf_point(x / scale, disp_h - y / scale, rotation, width, height)
            xs.append(px + crop[0])
            ys.append(py + crop[1])
    return (min(xs), min(ys), max(xs), max(ys))


def _weighted_confidence(lines: Sequence[EngineLine]) -> float | None:
    total = 0
    acc = 0.0
    for line in lines:
        n = sum(1 for ch in line.text if not ch.isspace())
        total += n
        acc += n * line.confidence
    return acc / total if total else None


def page_quality(lines: Sequence[EngineLine]) -> float | None:
    """Mean confidence weighted by non-space chars, over lines with a letter or digit."""
    return _weighted_confidence([ln for ln in lines if any(ch.isalnum() for ch in ln.text)])


def ink_share(image: Image.Image) -> float:
    """Share of dark pixels (< 128) inside the page, ignoring a 3% margin on each side."""
    grey = image.convert("L")
    width, height = grey.size
    mx, my = round(0.03 * width), round(0.03 * height)
    inner = grey.crop((mx, my, width - mx, height - my))
    total = inner.size[0] * inner.size[1]
    if total <= 0:
        return 0.0
    return sum(inner.histogram()[:128]) / total


def result_sha256(
    lines: Sequence[Mapping[str, Any]],
    turn: int,
    orientation_unknown: bool,
    quality: float | None,
    ink_share: float | None,
) -> str:
    """SHA-256 of the canonical JSON of a recognition result (R-11)."""
    payload = {
        "lines": [
            {
                "text": ln["text"],
                "bbox": [round(float(v), 2) for v in ln["bbox"]],
                "confidence": round(float(ln["confidence"]), 3),
            }
            for ln in lines
        ],
        "turn": turn,
        "orientation_unknown": orientation_unknown,
        "quality": None if quality is None else round(quality, 4),
        "ink_share": None if ink_share is None else round(ink_share, 4),
    }
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


_CYRILLIC_WORD = re.compile(r"[а-яёА-ЯЁ]{2,}")
_RUSSIAN_VOWELS = frozenset("аеёиоуыэюяАЕЁИОУЫЭЮЯ")


def orientation_score(lines: Sequence[EngineLine]) -> float:
    """Mean confidence × share of Cyrillic words that contain a vowel (R-6)."""
    words = [w for ln in lines for w in _CYRILLIC_WORD.findall(ln.text)]
    if not words:
        return 0.0
    share = sum(1 for w in words if _RUSSIAN_VOWELS.intersection(w)) / len(words)
    return (_weighted_confidence(lines) or 0.0) * share
