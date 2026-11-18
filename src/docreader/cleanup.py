"""Clean document text and the map «text range → page line» (R-4, R-6).

Pure functions over `pagetext.Line` lists; no database, no PDF.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from docreader.config import ReadingSettings
from docreader.pagetext import HYPHEN_MARKER, Box, Line

# Roles that go into the clean document text (R-4).
TEXT_ROLES = frozenset({"body", "rotated"})


@dataclass(frozen=True)
class Span:
    """`[start, end)` of the document text comes from line `line_index` of `page_number`."""

    start: int
    end: int
    page_number: int
    line_index: int


class DocumentText(NamedTuple):
    text: str
    spans: list[Span]
    sha256: str
    read_pages: int


POSITION_TOLERANCE = 5.0  # pt, for "the same place on the page"

_PAGE_NUMBER = re.compile(
    r"^(?:[-\u2013\u2014]\s*\d+\s*[-\u2013\u2014]|(?:стр\.?|страница)\s*\d+(?:\s+из\s+\d+)?|\d+(?:\s+из\s+\d+)?)$",
    re.IGNORECASE,
)
_PAGE_NUMBER_KEY = "\x00page-number"  # cannot clash with the key of a text line
_DIGITS = re.compile(r"\d+")
_TRAILING_CYRILLIC = re.compile(r"[А-Яа-яЁё]+$")
_LEADING_CYRILLIC = re.compile(r"^[а-яё]+")


@dataclass
class PageLines:
    page_number: int
    height: float  # page height in pt (display space)
    lines: list[Line]


def _furniture_key(text: str) -> str:
    return " ".join(_DIGITS.sub("#", text).split())


def _band(box: Box, page_height: float, share: float) -> str | None:
    """`header` / `footer` when the line lies in the top / bottom band of the page."""
    if box[3] >= page_height * (1 - share):
        return "header"
    if box[1] <= page_height * share:
        return "footer"
    return None


def _same_place(a: Box, b: Box) -> bool:
    """Same top and the same left, right or centre: «9» and «10» differ in width."""
    if abs(a[3] - b[3]) > POSITION_TOLERANCE:
        return False
    return (
        abs(a[0] - b[0]) <= POSITION_TOLERANCE
        or abs(a[2] - b[2]) <= POSITION_TOLERANCE
        or abs((a[0] + a[2]) - (b[0] + b[2])) / 2 <= POSITION_TOLERANCE
    )


def mark_page_furniture(pages: Sequence[PageLines], settings: ReadingSettings) -> None:
    """Set role header/footer/page_number on repeated lines of the top/bottom band (R-4).

    A line is furniture only when the same text (digits aside) stands at the same place
    on more than `header_min_share` of the pages (FR-004: «повторяющиеся»). This holds
    for page numbers too, so a lone number near the page edge stays in the text.
    Table cells are never furniture: they are contract data (amounts, totals).
    """
    if len(pages) < settings.header_min_pages:
        return
    groups: dict[tuple[str, str], list[tuple[int, Box, Line]]] = defaultdict(list)
    for page in pages:
        for line in page.lines:
            if line.role != "body" or line.table is not None or not line.text.strip():
                continue
            box = line.display_bbox or line.bbox
            band = _band(box, page.height, settings.header_band)
            if band is None:
                continue
            # page numbers form one group whatever their form («- 3 -» / «Стр. 4»)
            text = line.text.strip()
            key = _PAGE_NUMBER_KEY if _PAGE_NUMBER.match(text) else _furniture_key(text)
            groups[(band, key)].append((page.page_number, box, line))
    total = len(pages)
    for (band, _key), entries in groups.items():
        for _page, box, line in entries:
            near_pages = {p for p, other, _ in entries if _same_place(box, other)}
            if len(near_pages) / total > settings.header_min_share:
                line.role = "page_number" if _PAGE_NUMBER.match(line.text.strip()) else band


def _hyphen_word(a: str, b: str) -> str | None:
    """The word broken between line `a` and line `b`, or None if it is not a candidate."""
    if len(a) < 2 or a[-1] not in ("-", HYPHEN_MARKER):
        return None
    tail = _TRAILING_CYRILLIC.search(a[:-1])
    head = _LEADING_CYRILLIC.match(b)
    if tail is None or head is None:
        return None
    return tail.group() + head.group()


def build_document_text(
    pages: Sequence[tuple[int, Sequence[Line]]],
    is_known: Callable[[str], bool] | None = None,
) -> DocumentText:
    """Join the lines of all pages (page number, lines in reading order) (tasks T014, T036).

    With `is_known`, a word broken at a line end is joined (R-6); without it lines are
    only joined with "\n".
    """
    read_pages = 0
    included: list[tuple[int, Line]] = []
    for page_number, lines in pages:
        if any(line.text for line in lines):
            read_pages += 1
        for line in lines:
            if line.role in TEXT_ROLES and line.text:
                included.append((page_number, line))

    parts: list[str] = []
    spans: list[Span] = []
    position = 0
    glue = False  # the previous line was joined to this one without "\n"
    for i, (page_number, line) in enumerate(included):
        emitted = line.text
        next_glue = False
        if is_known is not None and emitted[-1] == HYPHEN_MARKER:
            emitted = emitted[:-1] + "-"  # not a candidate unless changed below
        if is_known is not None and i + 1 < len(included):
            following = included[i + 1][1].text
            word = _hyphen_word(line.text, following)
            if word is not None:
                stem = line.text[:-1]
                emitted = stem if is_known(word.lower()) else stem + "-"
                next_glue = True
        if parts and not glue:
            position += 1  # the "\n" separator
        spans.append(Span(position, position + len(emitted), page_number, line.index))
        parts.append(("" if glue or not parts else "\n") + emitted)
        position += len(emitted)
        glue = next_glue
    text = "".join(parts)
    return DocumentText(text, spans, hashlib.sha256(text.encode("utf-8")).hexdigest(), read_pages)
