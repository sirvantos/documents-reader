"""Page text from PDFium chars: chars → segments → lines in reading order (R-2, R-3, R-8).

Pure functions work on simple records (`Char`), not on pypdfium2 objects; reading
PDFium is the thin function `read_page_chars`.

Coordinates are PDF page space, unrotated, as PDFium gives them:
a box is `(left, bottom, right, top)`.
"""

from __future__ import annotations

import ctypes
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from docreader.textnorm import normalize_chars

Box = tuple[float, float, float, float]  # (left, bottom, right, top)

ROLE_BODY = "body"

SEGMENT_GAP_FACTOR = 1.5  # x gap above this many char heights starts a new segment
LINE_OVERLAP_SHARE = 0.5  # vertical overlap needed, share of the smaller height
DUPLICATE_MAX_OFFSET = 1.0  # pt; same char closer than this in x and y is fake bold
HYPHEN_MARKER = "\ufffe"  # PDFium's mark for a hyphen at a line end


@dataclass(frozen=True)
class Char:
    """One char of the PDFium text page."""

    text: str  # one code point
    box: Box
    angle: float = 0.0  # degrees, as FPDFText_GetCharAngle gives it
    generated: bool = False  # inserted by PDFium (spaces, line breaks)
    map_error: bool = False  # FPDFText_HasUnicodeMapError


@dataclass(frozen=True)
class Segment:
    """A run of chars on one line without a large horizontal gap."""

    text: str
    bbox: Box


@dataclass
class Line:
    """One line of the page; `to_json` gives the `page_text.lines` element (data-model)."""

    index: int
    text: str
    bbox: Box
    role: str = ROLE_BODY
    column: int | None = None
    table: dict | None = None
    segments: tuple[Segment, ...] = field(default=(), compare=False)

    def to_json(self) -> dict:
        return {
            "i": self.index,
            "text": self.text,
            "bbox": [round(v, 2) for v in self.bbox],
            "role": self.role,
            "column": self.column,
            "table": self.table,
        }


def _height(box: Box) -> float:
    return box[3] - box[1]


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def _build_segments(chars: Sequence[Char]) -> list[Segment]:
    """Splits chars into segments: break on a large x gap or a line break char."""
    segments: list[Segment] = []
    parts: list[str] = []
    bbox: Box | None = None
    prev: Char | None = None  # last visible char of the current segment

    def flush() -> None:
        nonlocal parts, bbox, prev
        text = _collapse_spaces("".join(parts))
        if text and bbox is not None:
            segments.append(Segment(text, bbox))
        parts, bbox, prev = [], None, None

    for ch in chars:
        if ch.text in ("\r", "\n"):
            flush()
            continue
        if ch.text.isspace():
            parts.append(" ")
            continue
        if prev is not None:
            gap = ch.box[0] - prev.box[2]
            limit = SEGMENT_GAP_FACTOR * max(_height(ch.box), _height(prev.box))
            # a char that starts left of the previous one is a jump back: new segment
            if gap > limit or ch.box[0] < prev.box[0]:
                flush()
        parts.append(ch.text)
        bbox = ch.box if bbox is None else _union(bbox, ch.box)
        prev = ch
    flush()
    return segments


def _drop_duplicate_chars(chars: Sequence[Char]) -> list[Char]:
    """Drops fake-bold duplicates: a char with the same text as an already kept one,
    within `DUPLICATE_MAX_OFFSET` in both left and bottom. Whitespace is never dropped.

    Kept chars sit in a grid of 1 pt cells keyed by (text, int(left), int(bottom)),
    so each char checks only the 3x3 neighbour cells.
    """
    grid: dict[tuple[str, int, int], list[tuple[float, float]]] = {}
    kept: list[Char] = []
    for ch in chars:
        if ch.text.isspace():
            kept.append(ch)
            continue
        left, bottom = ch.box[0], ch.box[1]
        cx, cy = math.floor(left), math.floor(bottom)
        duplicate = any(
            abs(left - kl) < DUPLICATE_MAX_OFFSET and abs(bottom - kb) < DUPLICATE_MAX_OFFSET
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for kl, kb in grid.get((ch.text, cx + dx, cy + dy), ())
        )
        if duplicate:
            continue
        grid.setdefault((ch.text, cx, cy), []).append((left, bottom))
        kept.append(ch)
    return kept


def _same_line(a: Box, b: Box) -> bool:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    smaller = min(_height(a), _height(b))
    return smaller > 0 and overlap >= LINE_OVERLAP_SHARE * smaller


def build_lines(chars: Sequence[Char]) -> list[Line]:
    """Chars → segments → lines, top to bottom; indices from 0.

    Line text is normalized (R-5); a line that is empty afterwards is dropped.
    """
    segments = _build_segments(_drop_duplicate_chars(chars))
    groups: list[list[Segment]] = []
    boxes: list[Box] = []
    for seg in sorted(segments, key=lambda s: (-s.bbox[3], s.bbox[0])):
        for k, box in enumerate(boxes):
            if _same_line(box, seg.bbox):
                groups[k].append(seg)
                boxes[k] = _union(box, seg.bbox)
                break
        else:
            groups.append([seg])
            boxes.append(seg.bbox)
    order = sorted(range(len(groups)), key=lambda k: (-boxes[k][3], boxes[k][0]))
    lines: list[Line] = []
    for k in order:
        members = tuple(sorted(groups[k], key=lambda s: s.bbox[0]))
        text = normalize_chars(" ".join(s.text for s in members))
        if not text:
            continue
        lines.append(
            Line(
                index=len(lines),
                text=text,
                bbox=boxes[k],
                segments=members,
            )
        )
    return lines


def read_page_chars(pdf_page) -> list[Char]:  # noqa: ANN001 - pypdfium2.PdfPage
    """All chars of a pypdfium2 page via the raw PDFium API; every handle is closed."""
    import pypdfium2.raw as raw

    textpage = raw.FPDFText_LoadPage(pdf_page.raw)
    if not textpage:
        return []
    chars: list[Char] = []
    try:
        left, right = ctypes.c_double(), ctypes.c_double()
        bottom, top = ctypes.c_double(), ctypes.c_double()
        for i in range(raw.FPDFText_CountChars(textpage)):
            code = raw.FPDFText_GetUnicode(textpage, i)
            if code == 0 or 0xD800 <= code <= 0xDFFF or code > 0x10FFFF:
                continue
            if code == 0x02:  # PDFium's other form of the line-end hyphen mark
                code = ord(HYPHEN_MARKER)
            if not raw.FPDFText_GetCharBox(
                textpage,
                i,
                ctypes.byref(left),
                ctypes.byref(right),
                ctypes.byref(bottom),
                ctypes.byref(top),
            ):
                continue
            chars.append(
                Char(
                    text=chr(code),
                    box=(left.value, bottom.value, right.value, top.value),
                    angle=math.degrees(raw.FPDFText_GetCharAngle(textpage, i)),
                    generated=bool(raw.FPDFText_IsGenerated(textpage, i)),
                    map_error=bool(raw.FPDFText_HasUnicodeMapError(textpage, i)),
                )
            )
    finally:
        raw.FPDFText_ClosePage(textpage)
    return chars
