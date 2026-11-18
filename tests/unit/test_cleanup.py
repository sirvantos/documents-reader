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


# --- headers, footers and page numbers (task T031, R-4) ---

import pytest  # noqa: E402

from docreader.cleanup import PageLines, mark_page_furniture  # noqa: E402
from docreader.config import ReadingSettings  # noqa: E402

HEIGHT = 800.0
TOP = (50.0, 770.0, 300.0, 785.0)  # inside the top band (>= 720)
BOTTOM = (50.0, 20.0, 300.0, 35.0)  # inside the bottom band (<= 80)
MIDDLE = (50.0, 400.0, 300.0, 415.0)


def fline(index: int, text: str, bbox, role: str = "body") -> Line:
    return Line(index=index, text=text, bbox=bbox, role=role)


def make_pages(count: int, top: str | None = None, bottom: str | None = None, number=None):
    pages = []
    for n in range(1, count + 1):
        lines = []
        if top is not None:
            lines.append(fline(0, top, TOP))
        lines.append(fline(1, f"Текст страницы номер {n}", MIDDLE))
        if bottom is not None:
            lines.append(fline(2, bottom, BOTTOM))
        if number is not None:
            lines.append(fline(3, number.format(n=n), (400.0, 20.0, 450.0, 35.0)))
        pages.append(PageLines(n, HEIGHT, lines))
    return pages


def roles(page: PageLines) -> list[str]:
    return [ln.role for ln in page.lines]


def test_repeated_top_and_bottom_lines_are_header_and_footer():
    pages = make_pages(4, top="ДОГОВОР № 15", bottom="ООО «Ромашка»")
    mark_page_furniture(pages, ReadingSettings())
    for page in pages:
        assert roles(page) == ["header", "body", "footer"]


@pytest.mark.parametrize(
    "template",
    ["{n}", "- {n} -", "— {n} —", "Стр. {n}", "стр. {n}", "Страница {n}", "{n} из 10", "Стр. {n} из 10"],
)
def test_page_number_forms(template):
    pages = make_pages(4, number=template)
    mark_page_furniture(pages, ReadingSettings())
    for page in pages:
        assert roles(page) == ["body", "page_number"]


def test_page_number_in_band_on_single_page_still_page_number():
    pages = make_pages(4)
    pages[1].lines.append(fline(3, "Стр. 2", BOTTOM))
    mark_page_furniture(pages, ReadingSettings())
    assert roles(pages[1]) == ["body", "page_number"]


def test_page_number_in_the_middle_is_body():
    pages = make_pages(4)
    pages[0].lines.append(fline(5, "3", MIDDLE))
    mark_page_furniture(pages, ReadingSettings())
    assert roles(pages[0]) == ["body", "body"]


def test_too_few_pages_marks_nothing():
    pages = make_pages(2, top="ДОГОВОР № 15", bottom="ООО «Ромашка»", number="Стр. {n}")
    mark_page_furniture(pages, ReadingSettings())
    for page in pages:
        assert set(roles(page)) == {"body"}


def test_min_pages_setting_is_respected():
    pages = make_pages(2, top="ДОГОВОР № 15")
    mark_page_furniture(pages, ReadingSettings(header_min_pages=2))
    assert roles(pages[0])[0] == "header"


def test_digits_in_header_text_are_normalized():
    pages = [PageLines(n, HEIGHT, [fline(0, f"Приложение {n}   к договору", TOP)]) for n in range(1, 5)]
    mark_page_furniture(pages, ReadingSettings())
    assert all(roles(p) == ["header"] for p in pages)


def test_share_must_be_exceeded():
    # 2 of 4 pages = 0.5, not more than header_min_share 0.5
    pages = make_pages(4)
    for page in pages[:2]:
        page.lines.append(fline(9, "Редкая строка", TOP))
    mark_page_furniture(pages, ReadingSettings())
    assert roles(pages[0]) == ["body", "body"]
    # 3 of 4 pages: header
    pages[2].lines.append(fline(9, "Редкая строка", TOP))
    mark_page_furniture(pages, ReadingSettings())
    assert roles(pages[0]) == ["body", "header"]
    assert roles(pages[3]) == ["body"]


def test_different_position_is_not_a_header():
    pages = make_pages(4)
    for i, page in enumerate(pages):
        x = 50.0 + 30.0 * i
        page.lines.append(fline(9, "Плавающая строка", (x, 770.0, x + 100.0, 785.0)))
    mark_page_furniture(pages, ReadingSettings())
    assert all(roles(p) == ["body", "body"] for p in pages)


def test_repeated_line_outside_band_stays_body():
    pages = [PageLines(n, HEIGHT, [fline(0, "Повтор в середине", MIDDLE)]) for n in range(1, 5)]
    mark_page_furniture(pages, ReadingSettings())
    assert all(roles(p) == ["body"] for p in pages)


def test_signature_sheet_on_last_page_is_never_header():
    pages = make_pages(5, top="ДОГОВОР № 15")
    pages[-1].lines += [
        fline(10, "Номер договора: 15", (50.0, 760.0, 300.0, 775.0)),
        fline(11, "Дата подписания: 01.02.2024", (50.0, 740.0, 300.0, 755.0)),
        fline(12, "ФИО: Иванов Иван Иванович", (50.0, 60.0, 300.0, 75.0)),
    ]
    mark_page_furniture(pages, ReadingSettings())
    assert roles(pages[-1]) == ["header", "body", "body", "body", "body"]


def test_marked_lines_are_kept_but_absent_from_text_and_spans():
    pages = make_pages(4, top="ДОГОВОР № 15", bottom="ООО «Ромашка»", number="Стр. {n}")
    mark_page_furniture(pages, ReadingSettings())
    assert all(len(p.lines) == 4 for p in pages)
    result = build_document_text([(p.page_number, p.lines) for p in pages])
    assert result.text == "\n".join(f"Текст страницы номер {n}" for n in range(1, 5))
    assert len(result.spans) == 4
    assert all(s.line_index == 1 for s in result.spans)


def test_sentence_split_by_page_break_has_no_header_between():
    pages = [
        PageLines(
            n,
            HEIGHT,
            [fline(0, "ДОГОВОР № 15", TOP), fline(1, text, MIDDLE), fline(2, f"Стр. {n}", BOTTOM)],
        )
        for n, text in enumerate(["Поставщик обязуется передать", "товар Покупателю.", "Конец."], start=1)
    ]
    mark_page_furniture(pages, ReadingSettings())
    result = build_document_text([(p.page_number, p.lines) for p in pages])
    assert result.text == "Поставщик обязуется передать\nтовар Покупателю.\nКонец."
