"""Page flags and the reading stage state (research R-7; tasks T009, T023, T041)."""

from __future__ import annotations

import pytest

from docreader.quality import (
    FLAG_NAMES,
    FLAG_ORDER,
    NO_TEXT_REASON,
    Flag,
    PageInfo,
    document_state,
    skip_flag,
)


def info(kind: str = "text", char_count: int = 500, image_coverage: float = 0.0, page: int = 1) -> PageInfo:
    return PageInfo(page_number=page, kind=kind, char_count=char_count, image_coverage=image_coverage)


# --- flag catalogue -------------------------------------------------------------------


def test_flag_order_and_names_follow_fr006() -> None:
    assert FLAG_ORDER == (
        "scan_unread",
        "ocr_text",
        "unreadable",
        "maybe_not_russian",
        "empty",
        "reading_order_unknown",
    )
    assert FLAG_NAMES == {
        "scan_unread": "скан, не прочитана",
        "ocr_text": "текст получен распознаванием",
        "unreadable": "текст не читается",
        "maybe_not_russian": "возможно, не русский текст",
        "empty": "пустая",
        "reading_order_unknown": "порядок чтения не определён",
    }


# --- pages that are not read (step 1) ---------------------------------------------------


def test_blank_page_is_empty() -> None:
    flag = skip_flag(info(kind="scan", char_count=0, image_coverage=0.0))
    assert flag is not None
    assert flag.code == "empty"
    assert flag.reason.strip()


@pytest.mark.parametrize(("char_count", "coverage"), [(0, 1.0), (0, 0.3), (7, 0.9)])
def test_scan_with_image_is_not_read(char_count: int, coverage: float) -> None:
    flag = skip_flag(info(kind="scan", char_count=char_count, image_coverage=coverage))
    assert flag is not None
    assert flag.code == "scan_unread"
    assert flag.reason.strip()


def test_short_scan_page_without_images_is_read() -> None:
    # e.g. a page holding only «Подписи сторон:» (fewer chars than text_min_chars)
    assert skip_flag(info(kind="scan", char_count=15, image_coverage=0.0)) is None


@pytest.mark.parametrize("kind", ["text", "scan_with_text"])
def test_pages_with_text_are_read(kind: str) -> None:
    assert skip_flag(info(kind=kind, char_count=800, image_coverage=0.95)) is None


# --- document state ---------------------------------------------------------------------


def flag(code: str) -> Flag:
    return Flag(code, "причина")


def test_no_flags_is_done() -> None:
    assert document_state({1: [], 2: []}, read_pages=2) == ("done", None)


def test_only_empty_pages_is_done() -> None:
    assert document_state({1: [], 2: [flag("empty")]}, read_pages=1) == ("done", None)


def test_flag_other_than_empty_needs_review_with_page_list() -> None:
    pages = {
        1: [],
        3: [flag("scan_unread")],
        5: [flag("scan_unread")],
        6: [flag("empty")],
        7: [flag("maybe_not_russian")],
    }
    state, reason = document_state(pages, read_pages=2)
    assert state == "needs_review"
    assert reason == "стр. 3, 5: скан, не прочитана; стр. 7: возможно, не русский текст"


def test_reason_follows_flag_order_and_ascending_pages() -> None:
    pages = {
        9: [flag("reading_order_unknown"), flag("ocr_text")],
        2: [flag("ocr_text")],
        4: [flag("unreadable")],
    }
    state, reason = document_state(pages, read_pages=3)
    assert state == "needs_review"
    assert reason == (
        "стр. 2, 9: текст получен распознаванием; стр. 4: текст не читается; "
        "стр. 9: порядок чтения не определён"
    )


def test_no_read_text_needs_review() -> None:
    state, reason = document_state({1: [flag("scan_unread")], 2: [flag("scan_unread")]}, read_pages=0)
    assert state == "needs_review"
    assert reason is not None
    assert reason.startswith(NO_TEXT_REASON)
    assert NO_TEXT_REASON == "нет прочитанного текста"
    assert "стр. 1, 2: скан, не прочитана" in reason


def test_only_blank_pages_has_no_read_text() -> None:
    assert document_state({1: [flag("empty")]}, read_pages=0) == ("needs_review", NO_TEXT_REASON)


# --- flags of read pages (step 2, task T023) -------------------------------------------

from docreader.config import ReadingSettings  # noqa: E402
from docreader.pagetext import Char  # noqa: E402
from docreader.quality import content_flags, count_map_errors  # noqa: E402

RS = ReadingSettings()
MIN_CHARS = 20
RUSSIAN = (
    "1.1. Подрядчик обязуется выполнить работы по договору в срок, "
    "установленный графиком; Заказчик обязуется принять и оплатить их."
)


def codes(text: str, kind: str = "text", settings: ReadingSettings = RS, map_errors: int = 0) -> list[str]:
    flags = content_flags(info(kind=kind), text, settings, MIN_CHARS, map_errors=map_errors)
    for f in flags:
        assert f.reason.strip()
    return [f.code for f in flags]


def reason_of(text: str, code: str, **kw) -> str:
    flags = content_flags(info(**kw), text, RS, MIN_CHARS)
    return next(f.reason for f in flags if f.code == code)


def test_plain_russian_text_has_no_flags() -> None:
    assert codes(RUSSIAN) == []


def test_ocr_text_for_scan_with_text_page() -> None:
    assert codes(RUSSIAN, kind="scan_with_text") == ["ocr_text"]


@pytest.mark.parametrize(
    "text",
    [
        "«___» __________ 2024 г.",
        "Договор подряда № 123/45-У от «___» __________ 2024 г.\n1.1. 1.2. 1.3. 2.1.",
        "ИНН 7701234567 КПП 770101001 ОГРН 1027700000000 БИК 044525000",
        "Подписи сторон:",
    ],
)
def test_ordinary_contract_lines_are_readable(text: str) -> None:
    assert "unreadable" not in codes(text)


def test_short_garbage_is_never_unreadable() -> None:
    assert codes("� бвгд") == []  # fewer than text_min_chars


def test_low_letter_share_is_unreadable() -> None:
    text = "!!! ### $$$ %%% ^^^ &&& *** ((( ))) +++ === ~~~ абв"
    assert codes(text) == ["unreadable"]
    assert "букв и цифр" in reason_of(text, "unreadable")


def test_bad_chars_are_unreadable() -> None:
    text = RUSSIAN + " ��\U000f0000"
    assert codes(text) == ["unreadable"]
    assert "ошибкой кодировки" in reason_of(text, "unreadable")


def test_map_errors_count_as_bad_chars() -> None:
    assert codes(RUSSIAN, map_errors=12) == ["unreadable"]
    assert codes(RUSSIAN, map_errors=1) == []


def test_count_map_errors_does_not_double_count_replacement_chars() -> None:
    box = (0.0, 0.0, 1.0, 1.0)
    chars = [
        Char("а", box, map_error=True),
        Char("�", box, map_error=True),  # already counted from the text
        Char("", box, map_error=True),
        Char("б", box),
    ]
    assert count_map_errors(chars) == 1


def test_vowelless_words_are_unreadable() -> None:
    text = "бвгд жзкл мнпр стфх цчшщ бвгд жзкл мнпр и работы"
    assert codes(text) == ["unreadable"]
    assert "без гласных" in reason_of(text, "unreadable")


def test_thresholds_come_from_settings() -> None:
    text = "бвгд жзкл мнпр работы договор оплата"  # half of the words without vowels
    assert "unreadable" in codes(text)
    lenient = ReadingSettings(unreadable_max_vowelless_share=0.9)
    assert "unreadable" not in codes(text, settings=lenient)


def test_three_kazakh_letters_flag_not_russian() -> None:
    text = RUSSIAN + " Место исполнения: г. Қарағанды, ул. Әуезова."
    assert codes(text) == ["maybe_not_russian"]
    assert reason_of(text, "maybe_not_russian") == "3 буквы не русского алфавита: Қ, ғ, Ә"


def test_reason_lists_each_letter_once() -> None:
    text = RUSSIAN + " Қ Қ Ә Ұ І"
    assert reason_of(text, "maybe_not_russian") == "5 букв не русского алфавита: Қ, Ә, Ұ, І"


def test_one_kazakh_letter_in_a_surname_is_not_flagged() -> None:
    assert codes(RUSSIAN + " Представитель: Әлиев А.Б.") == []


def test_latin_letters_are_never_counted() -> None:
    text = RUSSIAN + " b55183f5-4c1e-4a7b CKAВ k-гo LLC e-mail: info@example.com"
    assert codes(text) == []


def test_ukrainian_letters_count_as_not_russian() -> None:
    assert codes(RUSSIAN + " Київ, Ґанок, Їжак") == ["maybe_not_russian"]


def test_not_russian_threshold_comes_from_settings() -> None:
    text = RUSSIAN + " Қарағанды Әуезова"
    strict = ReadingSettings(non_russian_min_letters=5)
    assert codes(text, settings=strict) == []


def test_flags_follow_fr006_order() -> None:
    text = "бвгд жзкл мнпр стфх цчшщ Қ Ә Ұ бвгд жзкл"
    assert codes(text, kind="scan_with_text") == ["ocr_text", "unreadable", "maybe_not_russian"]


# --- reading order (step 4, task T041) --------------------------------------------------

from docreader.quality import UNRESOLVED_MIN_LINES, layout_flag  # noqa: E402


def test_plain_layout_has_no_flag() -> None:
    assert layout_flag(rotated_lines=0, unresolved_lines=0) is None


def test_rotated_text_inside_the_page_is_flagged() -> None:
    flag = layout_flag(rotated_lines=3, unresolved_lines=0)
    assert flag is not None
    assert flag.code == "reading_order_unknown"
    assert "3" in flag.reason and "повёрнут" in flag.reason


def test_few_unresolved_multi_segment_lines_are_tolerated() -> None:
    assert UNRESOLVED_MIN_LINES == 3
    assert layout_flag(rotated_lines=0, unresolved_lines=2) is None


def test_many_unresolved_multi_segment_lines_are_flagged() -> None:
    flag = layout_flag(rotated_lines=0, unresolved_lines=4)
    assert flag is not None
    assert flag.code == "reading_order_unknown"
    assert "4" in flag.reason


def test_both_causes_are_in_one_reason() -> None:
    flag = layout_flag(rotated_lines=1, unresolved_lines=5)
    assert flag is not None
    assert "повёрнут" in flag.reason and "5" in flag.reason


def test_page_rotation_is_not_an_input() -> None:
    # The rule takes only the layout result: a page rotated in its properties is
    # read in the normal order and gives no rotated lines (FR-018).
    import inspect

    assert set(inspect.signature(layout_flag).parameters) == {"rotated_lines", "unresolved_lines"}
