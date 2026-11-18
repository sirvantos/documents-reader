"""Page quality flags and the reading stage state (research R-7, FR-006, FR-008).

Pure functions: page facts in, flags and the document state out. No database, no PDF.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from docreader.config import ReadingSettings
from docreader.pagetext import Char
from docreader.pdfpages import KIND_SCAN, KIND_SCAN_WITH_TEXT

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


# --- flags of read pages (step 2) --------------------------------------------------------

# Blanks of a form («___» __________ 2024 г.) are not text and not garbage (spec, edge
# cases): they count neither for the length nor for the shares of the `unreadable` rule.
_PLACEHOLDER_CHARS = frozenset("_")
_RUSSIAN_VOWELS = frozenset("аеёиоуыэюяАЕЁИОУЫЭЮЯ")
_CYRILLIC_WORD = re.compile("[Ѐ-ԯ]{3,}")


def _is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ԯ"


def _is_russian_letter(ch: str) -> bool:
    return "А" <= ch <= "я" or ch in "Ёё"


def _is_bad_char(ch: str) -> bool:
    """Replacement char or private use area: the font has no usable mapping."""
    code = ord(ch)
    return (
        ch == "�"
        or 0xE000 <= code <= 0xF8FF
        or 0xF0000 <= code <= 0xFFFFD
        or 0x100000 <= code <= 0x10FFFD
    )


def _is_letter_or_digit(ch: str) -> bool:
    return _is_cyrillic(ch) and ch.isalpha() or ch.isascii() and ch.isalnum()


def count_map_errors(chars: Iterable[Char]) -> int:
    """Chars PDFium marks as badly mapped that the text check does not see by itself."""
    return sum(1 for ch in chars if ch.map_error and not _is_bad_char(ch.text))


def _share(part: int, whole: int) -> str:
    return f"{part / whole:.0%}"


def _unreadable_reason(
    text: str, settings: ReadingSettings, text_min_chars: int, map_errors: int
) -> str | None:
    chars = [ch for ch in text if not ch.isspace() and ch not in _PLACEHOLDER_CHARS]
    total = len(chars)
    if total < text_min_chars:
        return None
    problems = []

    letters = sum(1 for ch in chars if _is_letter_or_digit(ch))
    if letters / total < settings.unreadable_min_letter_share:
        problems.append(
            f"доля букв и цифр {_share(letters, total)} "
            f"(порог {settings.unreadable_min_letter_share:.0%})"
        )

    bad = sum(1 for ch in chars if _is_bad_char(ch)) + map_errors
    if bad / total > settings.unreadable_max_bad_share:
        problems.append(
            f"знаков с ошибкой кодировки {_share(bad, total)} "
            f"(порог {settings.unreadable_max_bad_share:.0%})"
        )

    words = _CYRILLIC_WORD.findall(text)
    if words:
        vowelless = sum(1 for w in words if not _RUSSIAN_VOWELS.intersection(w))
        if vowelless / len(words) > settings.unreadable_max_vowelless_share:
            problems.append(
                f"слов без гласных {_share(vowelless, len(words))} "
                f"(порог {settings.unreadable_max_vowelless_share:.0%})"
            )
    return "; ".join(problems) or None


def _letters_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "буква"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "буквы"
    return "букв"


def _not_russian_reason(text: str, settings: ReadingSettings) -> str | None:
    found = [ch for ch in text if _is_cyrillic(ch) and ch.isalpha() and not _is_russian_letter(ch)]
    if len(found) < settings.non_russian_min_letters:
        return None
    distinct = ", ".join(dict.fromkeys(found))
    return f"{len(found)} {_letters_word(len(found))} не русского алфавита: {distinct}"


def content_flags(
    page: PageInfo,
    text: str,
    settings: ReadingSettings,
    text_min_chars: int,
    *,
    map_errors: int = 0,
) -> list[Flag]:
    """Flags of a read page from its kind and its normalized text, in FR-006 order.

    `map_errors` comes from `count_map_errors` over the page chars; Latin letters are
    never counted as not Russian (spec, US2-6).
    """
    flags = []
    if page.kind == KIND_SCAN_WITH_TEXT:
        flags.append(
            Flag(
                "ocr_text",
                f"текстовый слой поверх изображения на {page.image_coverage:.0%} страницы",
            )
        )
    reason = _unreadable_reason(text, settings, text_min_chars, map_errors)
    if reason:
        flags.append(Flag("unreadable", reason))
    reason = _not_russian_reason(text, settings)
    if reason:
        flags.append(Flag("maybe_not_russian", reason))
    return flags


# --- reading order (step 4) ------------------------------------------------------------

# Lines with two or more segments outside columns and tables that make the order
# of the page doubtful (R-3, p. 6).
UNRESOLVED_MIN_LINES = 3


def _lines_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "строка"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "строки"
    return "строк"


def layout_flag(*, rotated_lines: int, unresolved_lines: int) -> Flag | None:
    """`reading_order_unknown` from the layout result of a page (R-3, p. 6).

    Only text turned inside the page counts as rotated: a page rotated in its
    properties is read in the normal order before this rule (FR-018).
    """
    parts = []
    if rotated_lines > 0:
        parts.append(f"{rotated_lines} {_lines_word(rotated_lines)} повёрнутого текста")
    if unresolved_lines >= UNRESOLVED_MIN_LINES:
        parts.append(
            f"{unresolved_lines} {_lines_word(unresolved_lines)} из нескольких частей "
            "вне колонок и таблиц"
        )
    if not parts:
        return None
    return Flag("reading_order_unknown", "; ".join(parts))


# --- document state ----------------------------------------------------------------------


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
