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
from docreader.pagetext import HYPHEN_MARKER, Line

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


def mark_page_furniture(pages: Sequence[PageLines], settings: ReadingSettings) -> None:
    """Set role header/footer/page_number on repeated lines in the top/bottom band (R-4)."""
    if len(pages) < settings.header_min_pages:
        return
    # (band, key) -> list of (page_number, left, top, line)
    groups: dict[tuple[str, str], list[tuple[int, float, float, Line]]] = defaultdict(list)
    for page in pages:
        for line in page.lines:
            if line.role != "body" or not line.text.strip():
                continue
            if line.bbox[3] >= page.height * (1 - settings.header_band):
                band = "header"
            elif line.bbox[1] <= page.height * settings.header_band:
                band = "footer"
            else:
                continue
            if _PAGE_NUMBER.match(line.text.strip()):
                line.role = "page_number"
                continue
            groups[(band, _furniture_key(line.text))].append(
                (page.page_number, line.bbox[0], line.bbox[3], line)
            )
    total = len(pages)
    for (band, _key), entries in groups.items():
        for _page, left, top, line in entries:
            near_pages = {
                p
                for p, other_left, other_top, _ in entries
                if abs(other_left - left) <= POSITION_TOLERANCE and abs(other_top - top) <= POSITION_TOLERANCE
            }
            if len(near_pages) / total > settings.header_min_share:
                line.role = band


def _is_hyphen_candidate(a: str, b: str) -> bool:
    if len(a) < 2 or a[-1] not in ("-", HYPHEN_MARKER):
        return False
    return bool(_TRAILING_CYRILLIC.search(a[:-1])) and bool(_LEADING_CYRILLIC.match(b))


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
            if _is_hyphen_candidate(line.text, following):
                stem = line.text[:-1]
                word = _TRAILING_CYRILLIC.search(stem).group() + _LEADING_CYRILLIC.match(following).group()
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
