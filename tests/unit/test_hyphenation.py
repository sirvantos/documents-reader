"""Tests for the hyphenation join in build_document_text (task T032, R-6)."""

from __future__ import annotations

import pytest

from docreader.cleanup import build_document_text
from docreader.pagetext import HYPHEN_MARKER, Line

BOX = (0.0, 0.0, 100.0, 10.0)
KNOWN = {"монтажные", "договор"}


def is_known(word: str) -> bool:
    return word in KNOWN


def line(index: int, text: str, role: str = "body") -> Line:
    return Line(index=index, text=text, bbox=BOX, role=role)


def build(*texts: str, known=is_known):
    return build_document_text([(1, [line(i, t) for i, t in enumerate(texts)])], known)


def test_known_word_is_joined_without_hyphen():
    result = build("Работы мон-", "тажные проводятся")
    assert result.text == "Работы монтажные проводятся"


def test_unknown_word_keeps_hyphen_without_line_break():
    result = build("строительно-", "монтажные работы")
    assert result.text == "строительно-монтажные работы"


def test_hyphen_marker_known_word():
    result = build(f"Работы мон{HYPHEN_MARKER}", "тажные проводятся")
    assert result.text == "Работы монтажные проводятся"


def test_hyphen_marker_unknown_word_becomes_hyphen():
    result = build(f"строительно{HYPHEN_MARKER}", "монтажные работы")
    assert result.text == "строительно-монтажные работы"


def test_marker_without_candidate_becomes_hyphen():
    result = build(f"Текст{HYPHEN_MARKER}", "Следующая")
    assert result.text == "Текст-\nСледующая"
    assert result.spans[0].end - result.spans[0].start == len("Текст-")


def test_spans_are_adjacent_and_cover_emitted_text():
    result = build("Работы мон-", "тажные проводятся", "Конец")
    a, b, c = result.spans
    assert result.text[a.start : a.end] == "Работы мон"
    assert result.text[b.start : b.end] == "тажные проводятся"
    assert a.end == b.start
    assert c.start == b.end + 1
    assert result.text[c.start : c.end] == "Конец"


def test_unknown_word_spans_adjacent():
    result = build("строительно-", "монтажные")
    a, b = result.spans
    assert result.text[a.start : a.end] == "строительно-"
    assert a.end == b.start


def test_join_across_pages():
    pages = [(1, [line(0, "Работы мон-")]), (2, [line(0, "тажные проводятся")])]
    result = build_document_text(pages, is_known)
    assert result.text == "Работы монтажные проводятся"
    assert [s.page_number for s in result.spans] == [1, 2]


def test_skipped_lines_in_between_are_ignored():
    pages = [
        (1, [line(0, "Работы мон-"), line(1, "Стр. 1", role="page_number")]),
        (2, [line(0, "Шапка", role="header"), line(1, "тажные проводятся")]),
    ]
    assert build_document_text(pages, is_known).text == "Работы монтажные проводятся"


def test_capital_letter_digit_and_latin_are_untouched():
    assert build("Работы мон-", "Тажные").text == "Работы мон-\nТажные"
    assert build("Пункт 5-", "1 договора").text == "Пункт 5-\n1 договора"
    assert build("Работы мон-", "tажные").text == "Работы мон-\ntажные"


def test_hyphen_not_after_cyrillic_letter_is_untouched():
    assert build("Пункт 5 -", "тажные").text == "Пункт 5 -\nтажные"
    assert build("мон -", "тажные").text == "мон -\nтажные"


def test_hyphen_inside_line_is_untouched():
    assert build("строительно-монтажные", "работы").text == "строительно-монтажные\nработы"


def test_without_is_known_nothing_is_joined():
    result = build("Работы мон-", "тажные", known=None)
    assert result.text == "Работы мон-\nтажные"


def test_chain_of_hyphenated_lines():
    result = build("дого-", "вор по-", "ставки")
    assert result.text == "договор по-ставки"


def test_real_pymorphy3_dictionary():
    pymorphy3 = pytest.importorskip("pymorphy3")
    morph = pymorphy3.MorphAnalyzer()

    def known(word: str) -> bool:
        return morph.word_is_known(word)

    assert build("мон-", "тажные", known=known).text == "монтажные"
    assert build("строительно-", "монтажные", known=known).text == "строительно-монтажные"
