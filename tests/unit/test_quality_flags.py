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
