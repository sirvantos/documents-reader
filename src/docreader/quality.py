"""Page quality flags and the reading stage state (research R-7, FR-006, FR-008).

Pure functions: page facts in, flags and the document state out. No database, no PDF.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from docreader.pdfpages import KIND_SCAN

# FR-006 order; it is also the order of the parts of the state reason.
FLAG_NAMES: dict[str, str] = {
    "scan_unread": "скан, не прочитана",
    "ocr_text": "текст получен распознаванием",
    "unreadable": "текст не читается",
    "maybe_not_russian": "возможно, не русский текст",
    "empty": "пустая",
    "reading_order_unknown": "порядок чтения не определён",
}
FLAG_ORDER: tuple[str, ...] = tuple(FLAG_NAMES)

# Flags that do not make the document need a review (US2-7).
NEUTRAL_FLAGS = frozenset({"empty"})

NO_TEXT_REASON = "нет прочитанного текста"

STATE_DONE = "done"
STATE_NEEDS_REVIEW = "needs_review"


@dataclass(frozen=True)
class PageInfo:
    """Page facts stored by intake (feature 01, table `page`)."""

    page_number: int
    kind: str
    char_count: int
    image_coverage: float


@dataclass(frozen=True)
class Flag:
    code: str
    reason: str


def skip_flag(page: PageInfo) -> Flag | None:
    """Flag of a page that is not read at all, or None when the page is read."""
    if page.char_count == 0 and page.image_coverage == 0:
        return Flag("empty", "на странице нет ни текста, ни изображений")
    if page.kind == KIND_SCAN and page.image_coverage > 0:
        if page.char_count == 0:
            detail = "текстового слоя нет"
        else:
            detail = f"в текстовом слое {page.char_count} зн."
        return Flag(
            "scan_unread",
            f"изображение на {page.image_coverage:.0%} страницы, {detail}; распознавание не выполняется",
        )
    return None


def _pages_by_flag(page_flags: Mapping[int, Sequence[Flag]]) -> list[tuple[str, list[int]]]:
    found: dict[str, set[int]] = {}
    for page_number, flags in page_flags.items():
        for flag in flags:
            if flag.code not in NEUTRAL_FLAGS:
                found.setdefault(flag.code, set()).add(page_number)
    return [(code, sorted(found[code])) for code in FLAG_ORDER if code in found]


def flags_reason(page_flags: Mapping[int, Sequence[Flag]]) -> str | None:
    """«стр. 3, 5: скан, не прочитана; стр. 7: …» for every flag except `empty`."""
    parts = [
        f"стр. {', '.join(map(str, pages))}: {FLAG_NAMES[code]}"
        for code, pages in _pages_by_flag(page_flags)
    ]
    return "; ".join(parts) or None


def document_state(
    page_flags: Mapping[int, Sequence[Flag]], read_pages: int
) -> tuple[str, str | None]:
    """State of the reading stage for a document and its reason (FR-008).

    `page_flags` maps every page number to its flags; `read_pages` is the number of
    pages that gave at least one line.
    """
    listed = flags_reason(page_flags)
    if read_pages == 0:
        return STATE_NEEDS_REVIEW, f"{NO_TEXT_REASON}; {listed}" if listed else NO_TEXT_REASON
    if listed:
        return STATE_NEEDS_REVIEW, listed
    return STATE_DONE, None
