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
    # page width in pt (display space); None: compare left/right edges as they are
    width: float | None = None


def _furniture_key(text: str) -> str:
    return " ".join(_DIGITS.sub("#", text).split())


def _band(box: Box, page_height: float, share: float) -> str | None:
    """`header` / `footer` when the line lies in the top / bottom band of the page."""
    if box[3] >= page_height * (1 - share):
        return "header"
    if box[1] <= page_height * share:
        return "footer"
    return None


class _Place(NamedTuple):
    """Where a line stands, measured from the page edges (display space, pt).

    Measuring from the edges keeps a footer «at the same place» on a landscape page of
    a portrait document: it keeps its margins, not its absolute x and y.
    """

    edge: float  # header: from the top edge to the line top; footer: line top from bottom
    left: float  # from the left edge
    right: float  # from the right edge
    centre: float  # line centre from the page centre


def _place(box: Box, page: PageLines, band: str) -> _Place:
    width = page.width if page.width is not None else 0.0
    edge = page.height - box[3] if band == "header" else box[3]
    return _Place(
        edge=edge,
        left=box[0],
        right=width - box[2],
        centre=(box[0] + box[2]) / 2 - width / 2,
    )


def _same_place(a: _Place, b: _Place) -> bool:
    """Same distance to the band edge and the same left, right or centre.

    «9» and «10» differ in width, so one of the three horizontal anchors is enough.
    """
    if abs(a.edge - b.edge) > POSITION_TOLERANCE:
        return False
    return (
        abs(a.left - b.left) <= POSITION_TOLERANCE
        or abs(a.right - b.right) <= POSITION_TOLERANCE
        or abs(a.centre - b.centre) <= POSITION_TOLERANCE
    )


class _Entry(NamedTuple):
    page: int
    place: _Place
    line: Line


def _page_number_offset(text: str, page_number: int) -> int | None:
    """Printed number minus the PDF page number («Страница 62 из 71» on page 62 → 0)."""
    found = _DIGITS.search(text)
    return None if found is None else int(found.group()) - page_number


def mark_page_furniture(pages: Sequence[PageLines], settings: ReadingSettings) -> None:
    """Set role header/footer/page_number on repeated lines of the top/bottom band (R-4).

    A line is furniture only when the same text (digits aside) stands at the same place
    on more than `header_min_share` of the pages (FR-004: «повторяющиеся»). The place
    is measured from the page edges, so pages of another size or orientation match.
    A page number is also furniture when it belongs to a run of at least
    `header_min_pages` consecutive pages whose printed numbers grow with the PDF page
    (one offset) at the same distance from the band edge: annexes may move the number
    or restart the numbering. A lone number near the page edge stays in the text.
    Table cells are contract data (amounts, totals) and never make furniture on their
    own. A cell line only joins furniture already found outside tables at the same
    place: a page frame joined to a table grid puts the footer of that page in a cell.
    """
    if len(pages) < settings.header_min_pages:
        return
    groups: dict[tuple[str, str], list[_Entry]] = defaultdict(list)
    numbered: dict[tuple[str, int], list[_Entry]] = defaultdict(list)
    cells: list[tuple[tuple[str, str], _Entry]] = []
    for page in pages:
        for line in page.lines:
            if line.role != "body" or not line.text.strip():
                continue
            box = line.display_bbox or line.bbox
            band = _band(box, page.height, settings.header_band)
            if band is None:
                continue
            entry = _Entry(page.page_number, _place(box, page, band), line)
            # page numbers form one group whatever their form («- 3 -» / «Стр. 4»)
            text = line.text.strip()
            is_number = _PAGE_NUMBER.match(text) is not None
            key = (band, _PAGE_NUMBER_KEY if is_number else _furniture_key(text))
            if line.table is not None:
                cells.append((key, entry))
                continue
            groups[key].append(entry)
            if is_number:
                offset = _page_number_offset(text, page.page_number)
                if offset is not None:
                    numbered[(band, offset)].append(entry)
    total = len(pages)
    for (band, _key), entries in groups.items():
        for entry in entries:
            near_pages = {e.page for e in entries if _same_place(entry.place, e.place)}
            if len(near_pages) / total > settings.header_min_share:
                entry.line.role = "page_number" if _key == _PAGE_NUMBER_KEY else band
    for key, cell in cells:
        found = next(
            (
                e.line.role
                for e in groups.get(key, ())
                if e.line.role != "body" and _same_place(cell.place, e.place)
            ),
            None,
        )
        if found is not None:
            cell.line.role = found
    for entries in numbered.values():
        for entry in entries:
            level_pages = {
                e.page
                for e in entries
                if abs(entry.place.edge - e.place.edge) <= POSITION_TOLERANCE
            }
            if _run_length(level_pages, entry.page) >= settings.header_min_pages:
                entry.line.role = "page_number"


def _run_length(pages: set[int], page: int) -> int:
    """Length of the run of consecutive page numbers in `pages` that contains `page`."""
    first = page
    while first - 1 in pages:
        first -= 1
    last = page
    while last + 1 in pages:
        last += 1
    return last - first + 1


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
