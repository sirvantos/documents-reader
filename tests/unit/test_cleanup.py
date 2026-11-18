"""Tests for the clean document text and the span map (task T010)."""

from __future__ import annotations

import hashlib

from docreader.cleanup import TEXT_ROLES, DocumentText, Span, build_document_text
from docreader.pagetext import Line

BOX = (0.0, 0.0, 100.0, 10.0)


def line(index: int, text: str, role: str = "body") -> Line:
    return Line(index=index, text=text, bbox=BOX, role=role)


def test_text_roles():
    assert TEXT_ROLES == {"body", "rotated"}


def test_empty_input():
    result = build_document_text([])
    assert isinstance(result, DocumentText)
    assert result.text == ""
    assert result.spans == []
    assert result.read_pages == 0
    assert result.sha256 == hashlib.sha256(b"").hexdigest()


def test_pages_without_lines():
    result = build_document_text([(1, []), (2, [])])
    assert result.text == ""
    assert result.spans == []
    assert result.read_pages == 0


def test_joins_lines_and_pages_with_newline():
    pages = [
        (1, [line(0, "Договор"), line(1, "поставки")]),
        (2, [line(0, "Статья 1")]),
    ]
    result = build_document_text(pages)
    assert result.text == "Договор\nпоставки\nСтатья 1"
    assert result.read_pages == 2
    assert result.sha256 == hashlib.sha256(result.text.encode("utf-8")).hexdigest()


def test_spans_point_to_line_text():
    pages = [
        (1, [line(0, "Договор"), line(1, "поставки")]),
        (3, [line(0, "Статья 1"), line(1, "Предмет", role="rotated")]),
    ]
    result = build_document_text(pages)
    lines_by_key = {(p, ln.index): ln for p, lns in pages for ln in lns}
    assert len(result.spans) == 4
    previous_end = 0
    for span in result.spans:
        assert isinstance(span, Span)
        source = lines_by_key[(span.page_number, span.line_index)]
        assert result.text[span.start : span.end] == source.text
        assert span.start >= previous_end
        previous_end = span.end
    assert [(s.page_number, s.line_index) for s in result.spans] == [(1, 0), (1, 1), (3, 0), (3, 1)]


def test_non_text_roles_and_empty_lines_are_skipped():
    pages = [
        (
            1,
            [
                line(0, "Верхний колонтитул", role="header"),
                line(1, "Текст"),
                line(2, ""),
                line(3, "Нижний колонтитул", role="footer"),
                line(4, "1", role="page_number"),
                line(5, "Ещё текст"),
            ],
        )
    ]
    result = build_document_text(pages)
    assert result.text == "Текст\nЕщё текст"
    assert [s.line_index for s in result.spans] == [1, 5]


def test_page_with_only_empty_line_is_not_read():
    result = build_document_text([(1, [line(0, "")]), (2, [line(0, "Текст")])])
    assert result.read_pages == 1
    assert result.text == "Текст"
    assert result.spans == [Span(0, 5, 2, 0)]


def test_header_only_page_counts_as_read_but_adds_no_text():
    result = build_document_text([(1, [line(0, "Колонтитул", role="header")]), (2, [line(0, "Текст")])])
    assert result.read_pages == 2
    assert result.text == "Текст"
    assert [s.page_number for s in result.spans] == [2]


def test_no_text_lines_at_all():
    result = build_document_text([(1, [line(0, "Колонтитул", role="footer")])])
    assert result.text == ""
    assert result.spans == []
    assert result.read_pages == 1
    assert result.sha256 == hashlib.sha256(b"").hexdigest()


def test_deterministic():
    pages = [(1, [line(0, "Договор"), line(1, "поставки")]), (2, [line(0, "Статья 1")])]
    assert build_document_text(pages) == build_document_text(pages)
