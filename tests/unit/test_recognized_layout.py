"""Recognised lines → page lines in reading order (research R-7, task T015).

`pagetext.lines_from_recognized(lines, *, rotation, width, height, settings,
continues_columns=False) -> PageLayout` takes stored `page_recognition.lines` elements
(`text`, `bbox` in unrotated PDF space, `confidence`) and orders them with the same
column rules as PDF text: fragments on one height become one line, two-column areas are
read left column first. No table detection on scans (`has_table` is always false).
"""

from __future__ import annotations

from docreader.config import ReadingSettings
from docreader.ocr import pdf_point
from docreader.pagetext import Char, build_lines, lines_from_recognized
from docreader.quality import UNRESOLVED_MIN_LINES

W, H = 595.0, 842.0
SETTINGS = ReadingSettings()


def frag(text: str, left: float, top: float, right: float, conf: float = 0.9, h: float = 10):
    return {"text": text, "bbox": [left, top - h, right, top], "confidence": conf}


def layout(lines, rotation: int = 0):
    return lines_from_recognized(
        [{"i": i, **ln} for i, ln in enumerate(lines)],
        rotation=rotation,
        width=W,
        height=H,
        settings=SETTINGS,
    )


def test_fragments_on_one_height_become_one_line_left_to_right() -> None:
    result = layout(
        [
            frag("выполнить", 200, 700, 280),
            frag("Подрядчик обязуется", 50, 701, 190),  # slightly higher: same line
            frag("Второй строкой", 50, 680, 150),
        ]
    )
    assert [ln.text for ln in result.lines] == [
        "Подрядчик обязуется выполнить",
        "Второй строкой",
    ]
    first = result.lines[0]
    assert len(first.segments) == 2
    assert first.bbox == (50, 690, 280, 701)
    assert [ln.index for ln in result.lines] == [0, 1]
    assert result.has_table is False


def test_lines_go_top_to_bottom_whatever_the_engine_order() -> None:
    result = layout(
        [frag("третья", 50, 600, 120), frag("первая", 50, 700, 120), frag("вторая", 50, 650, 120)]
    )
    assert [ln.text for ln in result.lines] == ["первая", "вторая", "третья"]


def test_requisites_in_two_columns_left_column_first() -> None:
    rows = [
        ("Заказчик: ОАО «РЖД»", "Подрядчик: ООО «Строй»"),
        ("ИНН 7708503727", "ИНН 7701234567"),
        ("КПП 997650001", "КПП 770101001"),
        ("ОГРН 1037739877295", "ОГРН 1027700000000"),
        ("р/с 40702810000000000001", "р/с 40702810000000000002"),
    ]
    lines = []
    for n, (left, right) in enumerate(rows):
        top = 700 - 14 * n
        lines += [frag(right, 320, top, 520), frag(left, 50, top, 250)]
    result = layout(lines)
    assert [ln.text for ln in result.lines] == [r[0] for r in rows] + [r[1] for r in rows]
    assert [ln.column for ln in result.lines] == [1] * 5 + [2] * 5
    assert result.unresolved_lines == 0


def test_table_cells_of_a_row_stay_together() -> None:
    cells = [("Наименование работ", "Ед.", "Стоимость, руб.")] + [
        (f"Работа {n}", "шт.", f"{n}00 000,00") for n in range(1, 5)
    ]
    lines = []
    for n, row in enumerate(cells):
        top = 700 - 14 * n
        lines += [
            frag(row[2], 450, top, 560),
            frag(row[0], 50, top, 200),
            frag(row[1], 260, top, 300),
        ]
    result = layout(lines)
    assert [ln.text for ln in result.lines] == [" ".join(row) for row in cells]
    assert all(ln.table is None for ln in result.lines)
    assert result.has_table is False
    assert result.unresolved_lines >= UNRESOLVED_MIN_LINES


def test_page_rotated_by_90_is_read_in_display_order() -> None:
    """Display space of a /Rotate 90 page is 842 × 595; boxes are stored unrotated."""
    display = [("Первая строка", 480.0), ("Вторая строка", 460.0), ("Третья", 440.0)]
    lines = []
    for text, top in reversed(display):
        corners = [pdf_point(x, y, 90, W, H) for x in (60.0, 300.0) for y in (top - 10, top)]
        xs, ys = [c[0] for c in corners], [c[1] for c in corners]
        lines.append(
            {"text": text, "bbox": [min(xs), min(ys), max(xs), max(ys)], "confidence": 0.9}
        )
    result = layout(lines, rotation=90)
    assert [ln.text for ln in result.lines] == [t for t, _ in display]


def test_confidence_is_kept_for_recognised_lines_only() -> None:
    result = layout(
        [frag("Договор", 50, 700, 120, conf=0.8), frag("подряда", 130, 700, 200, conf=0.6)]
    )
    data = result.lines[0].to_json()
    assert data["confidence"] == 0.6  # the weakest fragment of the line
    assert set(data) == {"i", "text", "bbox", "role", "column", "table", "confidence"}

    pdf_lines = build_lines([Char("А", (50, 690, 57, 700)), Char("Б", (57, 690, 64, 700))])
    assert "confidence" not in pdf_lines[0].to_json()


def test_column_parts_keep_their_confidence() -> None:
    lines = []
    for n in range(4):
        top = 700 - 14 * n
        lines += [
            frag(f"лево {n}", 50, top, 250, conf=0.5),
            frag(f"право {n}", 320, top, 520, conf=0.9),
        ]
    result = layout(lines)
    assert {ln.column: ln.to_json()["confidence"] for ln in result.lines} == {1: 0.5, 2: 0.9}


def test_text_is_normalised_as_pdf_text() -> None:
    result = layout([frag("1.1. Подрядчик „Строй“", 50, 700, 300)])
    assert result.lines[0].text == '1.1. Подрядчик "Строй"'


def test_empty_fragments_are_dropped_and_no_lines_is_fine() -> None:
    assert layout([]).lines == []
    result = layout([frag("  ", 50, 700, 60), frag("Текст", 50, 680, 90)])
    assert [ln.text for ln in result.lines] == ["Текст"]
