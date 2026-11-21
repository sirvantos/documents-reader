"""Page layout (R-3, R-8): rotation, two columns, ruled tables, on hand-made chars and rules."""

from __future__ import annotations

import pytest

from docreader.config import ReadingSettings
from docreader.pagetext import Char, PageLayout, Rule, layout_page

H = 10.0  # char height
W = 5.0  # char width
PAGE_W, PAGE_H = 600.0, 800.0
SETTINGS = ReadingSettings()


def word(text: str, left: float, bottom: float, *, angle: float = 0.0) -> list[Char]:
    return [
        Char(c, (left + i * W, bottom, left + (i + 1) * W, bottom + H), angle=angle)
        for i, c in enumerate(text)
    ]


def row(y: float, *parts: tuple[str, float]) -> list[Char]:
    """One display line: segments `(text, left)` at the same bottom `y`."""
    chars: list[Char] = []
    for text, left in parts:
        chars += word(text, left, y)
    return chars


def layout(
    chars, *, rotation=0, rules=(), continues=False, width=PAGE_W, height=PAGE_H
) -> PageLayout:
    return layout_page(
        chars,
        rotation=rotation,
        width=width,
        height=height,
        rules=list(rules),
        settings=SETTINGS,
        continues_columns=continues,
    )


def texts(result: PageLayout) -> list[str]:
    return [line.text for line in result.lines]


# --- rotation ---------------------------------------------------------------------------


def to_pdf_box(box, rotation: int):
    """Display box -> unrotated PDF box for a page of PAGE_W x PAGE_H (inverse of /Rotate)."""
    left, b, r, t = box
    if rotation == 0:
        return box
    if rotation == 90:
        return (PAGE_W - t, left, PAGE_W - b, r)
    if rotation == 180:
        return (PAGE_W - r, PAGE_H - t, PAGE_W - left, PAGE_H - b)
    return (b, PAGE_H - r, t, PAGE_H - left)  # 270


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_page_rotation_gives_display_order(rotation: int) -> None:
    # display space: page is (w, h) = (PAGE_W, PAGE_H) for 0/180, swapped for 90/270
    disp_w = PAGE_H if rotation in (90, 270) else PAGE_W
    disp_h = PAGE_W if rotation in (90, 270) else PAGE_H
    assert disp_w and disp_h
    chars: list[Char] = []
    for text, y in (("first", disp_h - 100), ("second", disp_h - 200), ("third", disp_h - 300)):
        for ch in word(text, 50, y):
            # text direction in the PDF: clockwise angle of the display text is 0,
            # so the PDF char angle is (0 - rotation) mod 360
            chars.append(Char(ch.text, to_pdf_box(ch.box, rotation), angle=(-rotation) % 360))
    result = layout(chars, rotation=rotation)
    assert texts(result) == ["first", "second", "third"]
    assert result.rotated_lines == 0
    assert all(line.role == "body" for line in result.lines)
    # bbox stays in unrotated PDF space
    first = result.lines[0]
    display_box = (50, disp_h - 100, 50 + 5 * W, disp_h - 100 + H)
    assert first.bbox == pytest.approx(to_pdf_box(display_box, rotation))
    assert first.display_bbox == pytest.approx((50, disp_h - 100, 50 + 5 * W, disp_h - 100 + H))


def test_turned_text_goes_to_the_end_with_role_rotated() -> None:
    chars = row(700, ("Horizontal", 50)) + row(650, ("Next", 50))
    # a block turned 90 degrees counter-clockwise: reads bottom to top, angle 270 clockwise
    turned = []
    for k, text in enumerate(("Aaa", "Bbb")):
        for i, c in enumerate(text):
            left = 300 + k * 20
            bottom = 100 + i * W
            turned.append(Char(c, (left, bottom, left + H, bottom + W), angle=270.0))
    result = layout(turned + chars)
    assert texts(result) == ["Horizontal", "Next", "Aaa", "Bbb"]
    assert [line.role for line in result.lines] == ["body", "body", "rotated", "rotated"]
    assert result.rotated_lines == 2
    assert [line.index for line in result.lines] == [0, 1, 2, 3]


def test_small_angle_is_not_rotated() -> None:
    chars = word("slanted", 50, 700, angle=3.0) + word("wrapped", 50, 600, angle=358.0)
    result = layout(chars)
    assert result.rotated_lines == 0
    assert texts(result) == ["slanted", "wrapped"]


def test_page_rotated_in_properties_with_normal_content_has_no_rotated_lines() -> None:
    # /Rotate 90: the PDF angle of the display text is 270 (clockwise); display angle 0
    chars = [
        Char(c, (PAGE_W - 700 - H + 0.0, 50 + i * W, PAGE_W - 700, 50 + (i + 1) * W), angle=270.0)
        for i, c in enumerate("normal")
    ]
    result = layout(chars, rotation=90)
    assert result.rotated_lines == 0
    assert texts(result) == ["normal"]


# --- two columns ------------------------------------------------------------------------


def two_cols(y_top: float, left: list[str], right: list[str], lx=72.0, rx=320.0) -> list[Char]:
    chars: list[Char] = []
    for k, (a, b) in enumerate(zip(left, right, strict=True)):
        chars += row(y_top - k * 16, (a, lx), (b, rx))
    return chars


def test_two_column_area_is_read_left_then_right() -> None:
    chars = row(700, ("Intro", 72)) + two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    chars += row(550, ("Outro", 72))
    result = layout(chars)
    assert texts(result) == ["Intro", "L1", "L2", "L3", "R1", "R2", "R3", "Outro"]
    assert [line.column for line in result.lines] == [None, 1, 1, 1, 2, 2, 2, None]
    assert result.unresolved_lines == 0
    assert not result.ends_in_columns
    assert not result.has_table
    # the right column line keeps its own box
    assert result.lines[4].bbox[0] == pytest.approx(320.0)


def test_fewer_than_min_lines_is_not_a_column_area() -> None:
    chars = two_cols(650, ["L1", "L2"], ["R1", "R2"])
    result = layout(chars)
    assert texts(result) == ["L1 R1", "L2 R2"]
    assert [line.column for line in result.lines] == [None, None]
    # the two lines split at the same place: rows of a table without rules (T058)
    assert result.unresolved_lines == 0


def test_small_gap_or_drifting_gap_is_not_a_column_area() -> None:
    # gap of 18 pt at a 10 pt line: below the wide gap max(20, 2.5 * 10): a word space,
    # so one part per line — not columns and not unresolved
    narrow = two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"], rx=72 + 2 * W + 18)
    narrow_result = layout(narrow)
    assert all(line.column is None for line in narrow_result.lines)
    assert narrow_result.unresolved_lines == 0
    # right segments drift by 20 pt per line, beyond the 15 pt tolerance
    drift: list[Char] = []
    for k in range(3):
        drift += row(650 - k * 16, ("L", 72), ("R", 320 + 20 * k))
    result = layout(drift)
    assert all(line.column is None for line in result.lines)


def test_column_area_at_the_end_sets_ends_in_columns() -> None:
    chars = row(700, ("Intro", 72)) + two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    assert layout(chars).ends_in_columns


def test_continuation_keeps_columns_with_fewer_lines() -> None:
    chars = two_cols(700, ["L4", "L5"], ["R4", "R5"]) + row(600, ("Sign", 72))
    plain = layout(chars)
    assert [line.column for line in plain.lines] == [None, None, None]
    result = layout(chars, continues=True)
    assert texts(result) == ["L4", "L5", "R4", "R5", "Sign"]
    assert [line.column for line in result.lines] == [1, 1, 2, 2, None]
    assert result.unresolved_lines == 0


def test_continuation_needs_two_segment_first_line() -> None:
    chars = row(700, ("Plain", 72)) + two_cols(650, ["L", "M"], ["R", "S"])
    result = layout(chars, continues=True)
    assert [line.column for line in result.lines] == [None, None, None]


# --- ruled tables -----------------------------------------------------------------------


def grid(xs: list[float], ys: list[float]) -> list[Rule]:
    rules = [Rule(xs[0], y, xs[-1], y) for y in ys]
    rules += [Rule(x, ys[0], x, ys[-1]) for x in xs]
    return rules


def test_grid_is_a_table_read_row_by_row() -> None:
    xs = [72.0, 112.0, 392.0, 535.0]
    ys = [600.0, 576.0, 552.0]  # two rows
    chars = row(700, ("Heading", 72))
    chars += row(580, ("1", 80), ("Work", 120), ("100", 400))
    chars += row(556, ("2", 80), ("More", 120), ("200", 400))
    chars += row(500, ("After", 72))
    result = layout(chars, rules=grid(xs, ys))
    assert texts(result) == ["Heading", "1", "Work", "100", "2", "More", "200", "After"]
    assert result.has_table
    tables = [line.table for line in result.lines]
    assert tables[0] is None and tables[-1] is None
    assert tables[1:7] == [
        {"t": 0, "row": 0, "cell": 0},
        {"t": 0, "row": 0, "cell": 1},
        {"t": 0, "row": 0, "cell": 2},
        {"t": 0, "row": 1, "cell": 0},
        {"t": 0, "row": 1, "cell": 1},
        {"t": 0, "row": 1, "cell": 2},
    ]
    assert all(line.column is None for line in result.lines)
    assert result.unresolved_lines == 0  # three segments per row, but inside a table


def test_two_cell_requisites_table_reads_cell_by_cell() -> None:
    xs = [72.0, 300.0, 523.0]
    ys = [700.0, 600.0]
    chars: list[Char] = []
    for k in range(3):
        chars += row(670 - k * 16, (f"Cust{k}", 80), (f"Cont{k}", 308))
    result = layout(chars, rules=grid(xs, ys))
    assert texts(result) == ["Cust0", "Cust1", "Cust2", "Cont0", "Cont1", "Cont2"]
    assert [line.table["cell"] for line in result.lines] == [0, 0, 0, 1, 1, 1]
    assert {line.table["row"] for line in result.lines} == {0}
    assert result.has_table


def test_multi_line_cell_and_multi_segment_line_inside_a_cell() -> None:
    xs = [72.0, 300.0, 523.0]
    ys = [700.0, 600.0]
    chars = row(670, ("Name", 80), ("Tel.", 160), ("Other", 308)) + row(654, ("Second", 80))
    result = layout(chars, rules=grid(xs, ys))
    assert texts(result) == ["Name Tel.", "Second", "Other"]
    assert [line.table["cell"] for line in result.lines] == [0, 0, 1]


def test_single_cell_box_is_not_a_table() -> None:
    chars = row(650, ("A", 80), ("B", 320))
    result = layout(chars, rules=grid([72.0, 523.0], [700.0, 600.0]))
    assert not result.has_table
    assert result.lines[0].table is None


def test_two_tables_are_numbered_in_order() -> None:
    xs = [72.0, 300.0, 523.0]
    rules = grid(xs, [700.0, 650.0]) + grid(xs, [400.0, 350.0])
    chars = row(670, ("a", 80), ("b", 308)) + row(370, ("c", 80), ("d", 308))
    result = layout(chars, rules=rules)
    assert [line.table["t"] for line in result.lines] == [0, 0, 1, 1]


def test_aligned_lines_with_many_segments_are_table_rows_not_unresolved() -> None:
    # a table without rules: splits within 15 pt of another line's — read row by row,
    # the order is known (T058, 2026-11-22; was 3 unresolved lines)
    chars: list[Char] = []
    for k, xs in enumerate(((72, 250, 420), (72, 262, 411), (72, 244, 431))):
        chars += row(650 - k * 24, ("aa", xs[0]), ("bb", xs[1]), ("cc", xs[2]))
    result = layout(chars)
    assert texts(result) == ["aa bb cc"] * 3
    assert result.unresolved_lines == 0
    assert not result.has_table


def test_lines_with_many_segments_split_at_different_places_are_unresolved() -> None:
    chars: list[Char] = []
    for k, xs in enumerate(((72, 200, 420), (72, 260, 480), (72, 320, 380))):
        chars += row(650 - k * 24, ("aa", xs[0]), ("bb", xs[1]), ("cc", xs[2]))
    assert layout(chars).unresolved_lines == 3


# --- word spaces of justified text and clause numbers (real contracts, 2026-11-18) ---------


def justified(y: float, words: list[str], gap: float, left: float = 72.0) -> list[Char]:
    """One line of words separated by `gap` pt: each word is its own segment."""
    parts: list[tuple[str, float]] = []
    x = left
    for w in words:
        parts.append((w, x))
        x += len(w) * W + gap
    return row(y, *parts)


def test_wide_word_spaces_of_justified_text_are_not_unresolved() -> None:
    # gaps of 16–22 pt at a 10 pt line split segments (over 1.5 char heights) but are word
    # spaces: below max(20, 2.5 * 10)
    chars: list[Char] = []
    for k, gap in enumerate((16.0, 18.0, 22.0, 20.0)):
        chars += justified(700 - k * 16, ["Подрядчик", "обязуется", "выполнить", "работы"], gap)
    result = layout(chars)
    assert all(len(line.segments) == 4 for line in result.lines)
    assert result.unresolved_lines == 0
    assert all(line.column is None for line in result.lines)
    assert texts(result)[0] == "Подрядчик обязуется выполнить работы"


def test_a_really_wide_gap_still_makes_a_line_unresolved() -> None:
    # 40 pt at a 10 pt line: beyond max(20, 25) — a spaced table or a form line
    chars: list[Char] = []
    # the splits are 40 pt apart: no two lines line up, so none is a table row (T058)
    for k, xs in enumerate(((72, 200), (72, 240), (72, 280))):
        chars += row(650 - k * 24, ("Итого", xs[0]), ("1500", xs[1]))
    assert layout(chars).unresolved_lines == 3


def test_clause_number_with_a_tab_stays_with_its_text() -> None:
    # «5.1.» + tab at the same x on three lines: not a two-column area, number then text
    chars: list[Char] = []
    for k, number in enumerate(("5.1.", "5.2.", "5.3.")):
        chars += row(700 - k * 16, (number, 72), ("Текст", 72 + 4 * W + 40))
    result = layout(chars)
    assert texts(result) == ["5.1. Текст", "5.2. Текст", "5.3. Текст"]
    assert all(line.column is None for line in result.lines)
    assert result.unresolved_lines == 0


def test_columns_with_word_spaces_inside_are_still_columns() -> None:
    # requisites in two columns, each column line has a word space wider than 1.5 char
    # heights: the line is two parts, read left column then right column
    chars: list[Char] = []
    for k in range(3):
        y = 650 - k * 16
        chars += justified(y, ["ИНН", f"77{k}"], 17.0, left=72)
        chars += justified(y, ["КПП", f"50{k}"], 17.0, left=320)
    result = layout(chars)
    assert texts(result) == ["ИНН 770", "ИНН 771", "ИНН 772", "КПП 500", "КПП 501", "КПП 502"]
    assert [line.column for line in result.lines] == [1, 1, 1, 2, 2, 2]
    assert result.unresolved_lines == 0


# --- signature blocks: a column with a line more than the other -------------------------


def test_left_only_line_below_the_columns_stays_in_the_left_column() -> None:
    # «От Заказчика» has four lines, «От Подрядчика» three; then a full-width line
    chars = two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    chars += row(650 - 3 * 16, ("L4", 72))
    chars += row(650 - 4 * 16 - 20, ("Signature line across the page", 72))
    result = layout(chars)
    assert texts(result) == ["L1", "L2", "L3", "L4", "R1", "R2", "R3",
                             "Signature line across the page"]
    assert [line.column for line in result.lines] == [1, 1, 1, 1, 2, 2, 2, None]
    assert result.unresolved_lines == 0


def test_right_only_line_stays_in_the_right_column() -> None:
    chars = two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    chars += row(650 - 3 * 16, ("R4", 320))
    result = layout(chars)
    assert texts(result) == ["L1", "L2", "L3", "R1", "R2", "R3", "R4"]
    assert [line.column for line in result.lines] == [1, 1, 1, 2, 2, 2, 2]


def test_one_column_lines_do_not_make_an_area_on_their_own() -> None:
    # two two-part lines and two left-only lines: below column_min_lines = 3
    chars = two_cols(650, ["L1", "L2"], ["R1", "R2"])
    chars += row(650 - 2 * 16, ("L3", 72)) + row(650 - 3 * 16, ("L4", 72))
    result = layout(chars)
    assert [line.column for line in result.lines] == [None, None, None, None]


def test_line_after_a_space_is_not_in_the_column() -> None:
    # a left-aligned short line one blank line below the area starts new text
    chars = two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    chars += row(650 - 2 * 16 - 32, ("Next", 72))
    result = layout(chars)
    assert texts(result)[-1] == "Next"
    assert result.lines[-1].column is None


def test_full_width_line_ends_the_area() -> None:
    chars = two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    long_line = "A long paragraph line that runs over the gap between the columns"
    chars += row(650 - 3 * 16, (long_line, 72))
    result = layout(chars)
    assert result.lines[-1].column is None
    assert texts(result)[-1] == long_line


def test_left_text_close_to_the_right_column_is_still_two_columns() -> None:
    # signature block: one left line runs to 22 pt before the right column — below the
    # wide gap max(20, 2.5 * 10) = 25, but the right segment starts at the cut
    chars = two_cols(650, ["L1", "L2"], ["R1", "R2"])
    long_left = "L" * 45  # 72 + 225 = 297, gap 23 to the right column at 320
    chars += row(650 - 2 * 16, (long_left, 72), ("R3", 320))
    chars += row(650 - 3 * 16, ("L4", 72), ("R4", 320))
    result = layout(chars)
    assert texts(result) == ["L1", "L2", long_left, "L4", "R1", "R2", "R3", "R4"]
    assert [line.column for line in result.lines] == [1, 1, 1, 1, 2, 2, 2, 2]
    assert result.unresolved_lines == 0


def test_close_gap_does_not_start_an_area() -> None:
    # without two-part lines around, a 23 pt gap is a word space
    chars: list[Char] = []
    for k in range(3):
        chars += row(650 - k * 16, ("L" * 45, 72), ("R", 320))
    result = layout(chars)
    assert all(line.column is None for line in result.lines)


def test_justified_line_after_the_area_ends_it() -> None:
    chars = two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    # many segments with even gaps of 21 pt, one of them at the cut
    parts = [(f"word{k}", 78 + 46 * k) for k in range(7)]  # wordN at 78 … 354, 310 at the cut
    chars += row(650 - 3 * 16, *parts)
    result = layout(chars)
    assert result.lines[-1].column is None


def test_narrow_gap_flush_with_the_cut_is_two_columns() -> None:
    # left text 17 pt before the right column (a segment break, below column_min_gap);
    # the right segment starts exactly at the cut
    chars = two_cols(650, ["L1", "L2"], ["R1", "R2"])
    long_left = "L" * 46  # 72 + 230 = 302, gap 18 to the right column at 320
    chars += row(650 - 2 * 16, (long_left, 72), ("R3", 320))
    chars += row(650 - 3 * 16, ("L4", 72), ("R4", 320))
    result = layout(chars)
    assert texts(result) == ["L1", "L2", long_left, "L4", "R1", "R2", "R3", "R4"]
    assert result.unresolved_lines == 0


def test_narrow_gap_off_the_cut_ends_the_area() -> None:
    # a narrow gap of 18 pt, the right segment 10 pt left of the cut at 320
    chars = two_cols(650, ["L1", "L2", "L3"], ["R1", "R2", "R3"])
    chars += row(650 - 3 * 16, ("L" * 44, 72), ("R4", 310))
    result = layout(chars)
    assert result.lines[-1].column is None
