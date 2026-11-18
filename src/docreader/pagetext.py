"""Page text from PDFium chars: chars → segments → lines in reading order (R-2, R-3, R-8).

Pure functions work on simple records (`Char`), not on pypdfium2 objects; reading
PDFium is the thin function `read_page_chars`.

Coordinates are PDF page space, unrotated, as PDFium gives them:
a box is `(left, bottom, right, top)`.
"""

from __future__ import annotations

import ctypes
import math
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, field

from docreader.config import ReadingSettings
from docreader.textnorm import normalize_chars

Box = tuple[float, float, float, float]  # (left, bottom, right, top)

ROLE_BODY = "body"
ROLE_ROTATED = "rotated"

SEGMENT_GAP_FACTOR = 1.5  # x gap above this many char heights starts a new segment
LINE_OVERLAP_SHARE = 0.5  # vertical overlap needed, share of the smaller height
DUPLICATE_MAX_OFFSET = 1.0  # pt; same char closer than this in x and y is fake bold
HYPHEN_MARKER = "\ufffe"  # PDFium's mark for a hyphen at a line end


@dataclass(frozen=True)
class Char:
    """One char of the PDFium text page."""

    text: str  # one code point
    box: Box
    angle: float = 0.0  # degrees, as FPDFText_GetCharAngle gives it
    generated: bool = False  # inserted by PDFium (spaces, line breaks)
    map_error: bool = False  # FPDFText_HasUnicodeMapError


@dataclass(frozen=True)
class Segment:
    """A run of chars on one line without a large horizontal gap."""

    text: str
    bbox: Box


@dataclass
class Line:
    """One line of the page; `to_json` gives the `page_text.lines` element (data-model)."""

    index: int
    text: str
    bbox: Box
    role: str = ROLE_BODY
    column: int | None = None
    table: dict | None = None
    segments: tuple[Segment, ...] = field(default=(), compare=False)
    # Box in display space (after /Rotate); `bbox` stays in unrotated PDF space.
    display_bbox: Box | None = field(default=None, compare=False)

    def to_json(self) -> dict:
        return {
            "i": self.index,
            "text": self.text,
            "bbox": [round(v, 2) for v in self.bbox],
            "role": self.role,
            "column": self.column,
            "table": self.table,
        }


def _line_text(raw: str) -> str:
    """Stored line text: R-5 normalization, PDFium's line-end hyphen mark shown as «-».

    The PDF shows a hyphen there; hyphenation (cleanup.py) treats both forms alike.
    """
    return normalize_chars(raw).replace(HYPHEN_MARKER, "-")


def _height(box: Box) -> float:
    return box[3] - box[1]


def _union(a: Box, b: Box) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _collapse_spaces(text: str) -> str:
    return " ".join(text.split())


def _build_segments(chars: Sequence[Char]) -> list[Segment]:
    """Splits chars into segments: break on a large x gap or a line break char."""
    segments: list[Segment] = []
    parts: list[str] = []
    bbox: Box | None = None
    prev: Char | None = None  # last visible char of the current segment

    def flush() -> None:
        nonlocal parts, bbox, prev
        text = _collapse_spaces("".join(parts))
        if text and bbox is not None:
            segments.append(Segment(text, bbox))
        parts, bbox, prev = [], None, None

    for ch in chars:
        if ch.text in ("\r", "\n"):
            flush()
            continue
        if ch.text.isspace():
            parts.append(" ")
            continue
        if prev is not None:
            gap = ch.box[0] - prev.box[2]
            limit = SEGMENT_GAP_FACTOR * max(_height(ch.box), _height(prev.box))
            # a char that starts left of the previous one is a jump back: new segment
            if gap > limit or ch.box[0] < prev.box[0]:
                flush()
        parts.append(ch.text)
        bbox = ch.box if bbox is None else _union(bbox, ch.box)
        prev = ch
    flush()
    return segments


def _drop_duplicate_chars(chars: Sequence[Char]) -> list[Char]:
    """Drops fake-bold duplicates: a char with the same text as an already kept one,
    within `DUPLICATE_MAX_OFFSET` in both left and bottom. Whitespace is never dropped.

    Kept chars sit in a grid of 1 pt cells keyed by (text, int(left), int(bottom)),
    so each char checks only the 3x3 neighbour cells.
    """
    grid: dict[tuple[str, int, int], list[tuple[float, float]]] = {}
    kept: list[Char] = []
    for ch in chars:
        if ch.text.isspace():
            kept.append(ch)
            continue
        left, bottom = ch.box[0], ch.box[1]
        cx, cy = math.floor(left), math.floor(bottom)
        duplicate = any(
            abs(left - kl) < DUPLICATE_MAX_OFFSET and abs(bottom - kb) < DUPLICATE_MAX_OFFSET
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for kl, kb in grid.get((ch.text, cx + dx, cy + dy), ())
        )
        if duplicate:
            continue
        grid.setdefault((ch.text, cx, cy), []).append((left, bottom))
        kept.append(ch)
    return kept


def _same_line(a: Box, b: Box) -> bool:
    overlap = min(a[3], b[3]) - max(a[1], b[1])
    smaller = min(_height(a), _height(b))
    return smaller > 0 and overlap >= LINE_OVERLAP_SHARE * smaller


def build_lines(chars: Sequence[Char]) -> list[Line]:
    """Chars → segments → lines, top to bottom; indices from 0.

    Line text is normalized (R-5); a line that is empty afterwards is dropped.
    """
    segments = _build_segments(_drop_duplicate_chars(chars))
    groups: list[list[Segment]] = []
    boxes: list[Box] = []
    for seg in sorted(segments, key=lambda s: (-s.bbox[3], s.bbox[0])):
        for k, box in enumerate(boxes):
            if _same_line(box, seg.bbox):
                groups[k].append(seg)
                boxes[k] = _union(box, seg.bbox)
                break
        else:
            groups.append([seg])
            boxes.append(seg.bbox)
    order = sorted(range(len(groups)), key=lambda k: (-boxes[k][3], boxes[k][0]))
    lines: list[Line] = []
    for k in order:
        members = tuple(sorted(groups[k], key=lambda s: s.bbox[0]))
        text = _line_text(" ".join(s.text for s in members))
        if not text:
            continue
        lines.append(
            Line(
                index=len(lines),
                text=text,
                bbox=boxes[k],
                segments=members,
            )
        )
    return lines


def read_page_chars(pdf_page) -> list[Char]:  # noqa: ANN001 - pypdfium2.PdfPage
    """All chars of a pypdfium2 page via the raw PDFium API; every handle is closed."""
    import pypdfium2.raw as raw

    textpage = raw.FPDFText_LoadPage(pdf_page.raw)
    if not textpage:
        return []
    chars: list[Char] = []
    try:
        left, right = ctypes.c_double(), ctypes.c_double()
        bottom, top = ctypes.c_double(), ctypes.c_double()
        for i in range(raw.FPDFText_CountChars(textpage)):
            code = raw.FPDFText_GetUnicode(textpage, i)
            if code == 0 or 0xD800 <= code <= 0xDFFF or code > 0x10FFFF:
                continue
            if code == 0x02:  # PDFium's other form of the line-end hyphen mark
                code = ord(HYPHEN_MARKER)
            if not raw.FPDFText_GetCharBox(
                textpage,
                i,
                ctypes.byref(left),
                ctypes.byref(right),
                ctypes.byref(bottom),
                ctypes.byref(top),
            ):
                continue
            chars.append(
                Char(
                    text=chr(code),
                    box=(left.value, bottom.value, right.value, top.value),
                    angle=math.degrees(raw.FPDFText_GetCharAngle(textpage, i)),
                    generated=bool(raw.FPDFText_IsGenerated(textpage, i)),
                    map_error=bool(raw.FPDFText_HasUnicodeMapError(textpage, i)),
                )
            )
    finally:
        raw.FPDFText_ClosePage(textpage)
    return chars


# --- layout: rotation, two columns, ruled tables (R-3, R-8) ---------------------------------

RULE_MAX_THICKNESS = 2.0  # pt; a thinner path object is a ruling line
RULE_MIN_LENGTH = 2.0  # pt; a shorter path piece is not a ruling segment
COORD_TOLERANCE = 1.5  # pt; grid coordinates closer than this are one line
JOIN_TOLERANCE = 2.0  # pt; rules this close to each other's span intersect


@dataclass(frozen=True)
class Rule:
    """One horizontal or vertical ruling segment in PDF page space."""

    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class PageLayout:
    lines: list[Line]  # reading order, indices 0..n-1
    rotated_lines: int = 0
    unresolved_lines: int = 0
    has_table: bool = False
    ends_in_columns: bool = False


def _display_point(x: float, y: float, rotation: int, width: float, height: float) -> tuple[float, float]:
    if rotation == 90:
        return y, width - x
    if rotation == 180:
        return width - x, height - y
    if rotation == 270:
        return height - y, x
    return x, y


def _pdf_point(x: float, y: float, rotation: int, width: float, height: float) -> tuple[float, float]:
    if rotation == 90:
        return width - y, x
    if rotation == 180:
        return width - x, height - y
    if rotation == 270:
        return y, height - x
    return x, y


def _map_box(box: Box, fn) -> Box:  # noqa: ANN001 - point mapping function
    points = [fn(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _chars_to_display(chars: Sequence[Char], rotation: int, width: float, height: float) -> list[Char]:
    if rotation == 0:
        return list(chars)
    return [
        Char(
            ch.text,
            _map_box(ch.box, lambda x, y: _display_point(x, y, rotation, width, height)),
            angle=ch.angle,
            generated=ch.generated,
            map_error=ch.map_error,
        )
        for ch in chars
    ]


def _rotated_keys(chars: Sequence[Char], rotation: int, min_angle: float) -> list[int | None]:
    """Per char: None for text that reads normally on the display, else its display angle
    in whole degrees. Angles are clockwise, as FPDFText_GetCharAngle gives them, so the
    display angle is `(char angle + /Rotate) mod 360`. Chars generated by PDFium follow
    the char before them (the one after for a leading run)."""
    keys: list[int | None] = [None] * len(chars)
    known = [False] * len(chars)
    for i, ch in enumerate(chars):
        if ch.generated:
            continue
        known[i] = True
        angle = (ch.angle + rotation) % 360
        if min(angle, 360 - angle) > min_angle:
            keys[i] = round(angle) % 360
    last: int | None = None
    seen = False
    for i in range(len(chars)):
        if known[i]:
            last, seen = keys[i], True
        elif seen:
            keys[i] = last
    following: int | None = None
    for i in range(len(chars) - 1, -1, -1):
        if known[i]:
            following = keys[i]
        elif not seen or all(not known[k] for k in range(i)):
            keys[i] = following
    return keys


def _turn(box: Box, degrees: float) -> Box:
    """Bounding box of `box` turned counter-clockwise by `degrees` around the origin."""
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    return _map_box(box, lambda x, y: (x * c - y * s, x * s + y * c))


def _rotated_lines(chars: Sequence[Char], angle: int) -> list[tuple[Line, Box]]:
    """Lines of text turned by the clockwise display `angle`: the chars are turned back so
    the text reads left to right, lines are built, and their boxes turned into display space."""
    back = angle  # a counter-clockwise turn by `angle` undoes a clockwise turn by `angle`
    flat = [
        Char(ch.text, _turn(ch.box, back), generated=ch.generated, map_error=ch.map_error)
        for ch in chars
    ]
    return [(line, _turn(line.bbox, -back)) for line in build_lines(flat)]


def _distinct(values: Sequence[float]) -> list[float]:
    merged: list[float] = []
    for v in sorted(values):
        if merged and v - merged[-1] <= COORD_TOLERANCE:
            continue
        merged.append(v)
    return merged


@dataclass
class _Table:
    box: Box  # display space
    xs: list[float]  # vertical grid coordinates, ascending
    ys: list[float]  # horizontal grid coordinates, ascending

    def contains(self, x: float, y: float) -> bool:
        return (
            self.box[0] - COORD_TOLERANCE <= x <= self.box[2] + COORD_TOLERANCE
            and self.box[1] - COORD_TOLERANCE <= y <= self.box[3] + COORD_TOLERANCE
        )

    def cell(self, x: float, y: float) -> tuple[int, int]:
        """(row from the top, cell from the left) of the grid cell holding the point."""
        rows, cols = len(self.ys) - 1, len(self.xs) - 1
        col = min(max(bisect_right(self.xs, x) - 1, 0), cols - 1)
        row_from_bottom = min(max(bisect_right(self.ys, y) - 1, 0), rows - 1)
        return rows - 1 - row_from_bottom, col


def _find_tables(rules: Sequence[Rule], rotation: int, width: float, height: float) -> list[_Table]:
    """Grids of intersecting ruling lines in display space (R-8): at least three vertical and
    two horizontal lines (1 x 2 cells and up) form a table."""
    horizontal: list[tuple[float, float, float]] = []  # (y, x0, x1)
    vertical: list[tuple[float, float, float]] = []  # (x, y0, y1)
    for rule in rules:
        x0, y0 = _display_point(rule.x0, rule.y0, rotation, width, height)
        x1, y1 = _display_point(rule.x1, rule.y1, rotation, width, height)
        if abs(y1 - y0) <= abs(x1 - x0):
            horizontal.append(((y0 + y1) / 2, min(x0, x1), max(x0, x1)))
        else:
            vertical.append(((x0 + x1) / 2, min(y0, y1), max(y0, y1)))
    nodes = [("h", i) for i in range(len(horizontal))] + [("v", i) for i in range(len(vertical))]
    parent = {node: node for node in nodes}

    def find(node):  # noqa: ANN001, ANN202
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for hi, (y, hx0, hx1) in enumerate(horizontal):
        for vi, (x, vy0, vy1) in enumerate(vertical):
            if hx0 - JOIN_TOLERANCE <= x <= hx1 + JOIN_TOLERANCE and vy0 - JOIN_TOLERANCE <= y <= vy1 + JOIN_TOLERANCE:
                parent[find(("h", hi))] = find(("v", vi))
    components: dict[tuple[str, int], list[tuple[str, int]]] = {}
    for node in nodes:
        components.setdefault(find(node), []).append(node)
    tables: list[_Table] = []
    for members in components.values():
        hs = [horizontal[i] for kind, i in members if kind == "h"]
        vs = [vertical[i] for kind, i in members if kind == "v"]
        ys = _distinct([h[0] for h in hs])
        xs = _distinct([v[0] for v in vs])
        if len(xs) < 3 or len(ys) < 2:
            continue
        box = (xs[0], ys[0], xs[-1], ys[-1])
        tables.append(_Table(box, xs, ys))
    tables.sort(key=lambda t: (-t.box[3], t.box[0]))
    return tables


def _gap_position(line: Line, min_gap: float) -> float | None:
    """Left edge of the right segment when the line has exactly two segments far apart."""
    if len(line.segments) != 2:
        return None
    left, right = line.segments
    if right.bbox[0] - left.bbox[2] < min_gap:
        return None
    return right.bbox[0]


def layout_page(
    chars: Sequence[Char],
    *,
    rotation: int,
    width: float,
    height: float,
    rules: Sequence[Rule],
    settings: ReadingSettings,
    continues_columns: bool = False,
) -> PageLayout:
    """Chars → lines in reading order with roles, columns and table cells (R-3, R-8).

    `width` and `height` are the unrotated page box. Line `bbox` is unrotated PDF space,
    `display_bbox` and the segments are display space.
    """

    def to_pdf(box: Box) -> Box:
        return _map_box(box, lambda x, y: _pdf_point(x, y, rotation, width, height))

    disp_h = width if rotation in (90, 270) else height

    keys = _rotated_keys(chars, rotation, settings.rotated_min_angle)
    display = _chars_to_display(chars, rotation, width, height)
    normal = [ch for ch, k in zip(display, keys) if k is None]
    lines = build_lines(normal)
    for line in lines:
        line.display_bbox = line.bbox
        line.bbox = to_pdf(line.bbox)

    turned: list[Line] = []
    for angle in sorted({k for k in keys if k is not None}):
        group = [ch for ch, k in zip(display, keys) if k == angle]
        for line, disp_box in _rotated_lines(group, angle):
            turned.append(
                Line(
                    index=0,
                    text=line.text,
                    bbox=to_pdf(disp_box),
                    role=ROLE_ROTATED,
                    display_bbox=disp_box,
                )
            )

    tables = _find_tables(rules, rotation, width, height)
    table_of: list[int | None] = []
    for line in lines:
        box = line.display_bbox
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        table_of.append(next((k for k, t in enumerate(tables) if t.contains(cx, cy)), None))

    areas = _column_areas(lines, table_of, disp_h, settings, continues_columns)
    area_at = {start: end for start, end in areas}
    in_area = {i for start, end in areas for i in range(start, end)}

    ordered: list[Line] = []
    emitted_tables: set[int] = set()
    i = 0
    while i < len(lines):
        k = table_of[i]
        if i in area_at:
            end = area_at[i]
            for side in (0, 1):
                for line in lines[i:end]:
                    part = _column_part(line, side, to_pdf)
                    if part is not None:
                        ordered.append(part)
            i = end
            continue
        if k is not None:
            if k not in emitted_tables:
                emitted_tables.add(k)
                members = [line for line, kk in zip(lines, table_of) if kk == k]
                ordered.extend(_table_lines(members, k, tables[k], to_pdf))
            i += 1
            continue
        ordered.append(lines[i])
        i += 1

    unresolved = sum(
        1
        for i, line in enumerate(lines)
        if len(line.segments) >= 2 and i not in in_area and table_of[i] is None
    )
    band = disp_h * settings.header_band
    # the last body line: single lines of the footer band after the area do not count
    last = len(lines) - 1
    while last > 0 and lines[last].display_bbox[1] <= band and last not in in_area:
        last -= 1
    ends_in_columns = last in in_area

    ordered.extend(turned)
    for n, line in enumerate(ordered):
        line.index = n
    return PageLayout(
        lines=ordered,
        rotated_lines=len(turned),
        unresolved_lines=unresolved,
        has_table=bool(tables),
        ends_in_columns=ends_in_columns,
    )


def _column_areas(
    lines: Sequence[Line],
    table_of: Sequence[int | None],
    disp_h: float,
    settings: ReadingSettings,
    continues: bool,
) -> list[tuple[int, int]]:
    """Index ranges `[start, end)` of two-column areas (R-3 p. 4-5)."""
    n = len(lines)
    positions = [
        None if table_of[i] is not None else _gap_position(lines[i], settings.column_min_gap)
        for i in range(n)
    ]

    def run_end(start: int) -> int:
        anchor = positions[start]
        end = start + 1
        while end < n and positions[end] is not None and abs(positions[end] - anchor) <= settings.column_gap_tolerance:
            end += 1
        return end

    areas: list[tuple[int, int]] = []
    i = 0
    if continues:
        # the area starts at the first line, past single lines of the running header band
        top_limit = disp_h * (1 - settings.header_band)
        for first in range(n):
            if positions[first] is not None:
                areas.append((first, run_end(first)))
                i = areas[0][1]
                break
            if lines[first].display_bbox[3] < top_limit:
                break
    while i < n:
        if positions[i] is None:
            i += 1
            continue
        end = run_end(i)
        if end - i >= settings.column_min_lines:
            areas.append((i, end))
            i = end
        else:
            i += 1
    return areas


def _column_part(line: Line, side: int, to_pdf) -> Line | None:  # noqa: ANN001
    segment = line.segments[side]
    text = _line_text(segment.text)
    if not text:
        return None
    return Line(
        index=0,
        text=text,
        bbox=to_pdf(segment.bbox),
        column=side + 1,
        segments=(segment,),
        display_bbox=segment.bbox,
    )


def _table_lines(members: Sequence[Line], t: int, table: _Table, to_pdf) -> list[Line]:  # noqa: ANN001
    """Cell lines of one table: row by row, cell by cell, lines of a cell top to bottom.
    A page line is cut at the cell borders; its parts inside one cell are joined."""
    parts: dict[tuple[int, int, int], list[Segment]] = {}
    for order, line in enumerate(members):
        segments = line.segments or (Segment(line.text, line.display_bbox),)
        for seg in segments:
            cx, cy = (seg.bbox[0] + seg.bbox[2]) / 2, (seg.bbox[1] + seg.bbox[3]) / 2
            row, cell = table.cell(cx, cy)
            parts.setdefault((row, cell, order), []).append(seg)
    result: list[Line] = []
    for (row, cell, _order), segs in sorted(parts.items()):
        text = _line_text(" ".join(s.text for s in segs))
        if not text:
            continue
        box = segs[0].bbox
        for s in segs[1:]:
            box = _union(box, s.bbox)
        result.append(
            Line(
                index=0,
                text=text,
                bbox=to_pdf(box),
                table={"t": t, "row": row, "cell": cell},
                segments=tuple(segs),
                display_bbox=box,
            )
        )
    return result


# --- ruling lines from path objects (R-8) -------------------------------------------------


def _path_rules(obj, matrices) -> list[Rule]:  # noqa: ANN001 - pypdfium2.PdfObject
    """Horizontal and vertical segments of one path object in page space."""
    import pypdfium2.raw as raw

    from docreader.pdfpages import _apply, _transform_rect

    left, bottom, right, top = _transform_rect(obj.get_bounds(), matrices)
    width, height = right - left, top - bottom
    if height <= RULE_MAX_THICKNESS < width:
        y = (bottom + top) / 2
        return [Rule(left, y, right, y)]
    if width <= RULE_MAX_THICKNESS < height:
        x = (left + right) / 2
        return [Rule(x, bottom, x, top)]
    if width <= RULE_MAX_THICKNESS and height <= RULE_MAX_THICKNESS:
        return []
    fill, stroke = ctypes.c_int(), ctypes.c_int()
    if not raw.FPDFPath_GetDrawMode(obj.raw, ctypes.byref(fill), ctypes.byref(stroke)) or not stroke.value:
        return []  # a filled area (cell background) is not a ruling
    count = raw.FPDFPath_CountSegments(obj.raw)
    if count <= 0:
        return [
            Rule(left, bottom, right, bottom),
            Rule(left, top, right, top),
            Rule(left, bottom, left, top),
            Rule(right, bottom, right, top),
        ]
    object_matrix = tuple(obj.get_matrix().get())
    chain = [object_matrix, *matrices]

    def point(segment) -> tuple[float, float]:  # noqa: ANN001
        x, y = ctypes.c_float(), ctypes.c_float()
        raw.FPDFPathSegment_GetPoint(segment, ctypes.byref(x), ctypes.byref(y))
        px, py = x.value, y.value
        for m in chain:
            px, py = _apply(m, px, py)
        return px, py

    rules: list[Rule] = []

    def add(a: tuple[float, float], b: tuple[float, float]) -> None:
        dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
        if dy <= RULE_MAX_THICKNESS / 2 and dx > RULE_MIN_LENGTH:
            rules.append(Rule(a[0], a[1], b[0], b[1]))
        elif dx <= RULE_MAX_THICKNESS / 2 and dy > RULE_MIN_LENGTH:
            rules.append(Rule(a[0], a[1], b[0], b[1]))

    current: tuple[float, float] | None = None
    start: tuple[float, float] | None = None
    for i in range(count):
        segment = raw.FPDFPath_GetPathSegment(obj.raw, i)
        if not segment:
            continue
        kind = raw.FPDFPathSegment_GetType(segment)
        if kind == raw.FPDF_SEGMENT_MOVETO:
            current = start = point(segment)
        elif kind == raw.FPDF_SEGMENT_LINETO:
            nxt = point(segment)
            if current is not None:
                add(current, nxt)
            current = nxt
        else:  # a curve: no ruling
            current = point(segment)
        if raw.FPDFPathSegment_GetClose(segment) and current is not None and start is not None:
            add(current, start)
            current = start
    return rules


def read_page_rules(pdf_page) -> list[Rule]:  # noqa: ANN001 - pypdfium2.PdfPage
    """Ruling segments of the page: path objects (also inside forms) as H/V segments in
    page space; form matrices are applied as in `pdfpages._page_metrics`."""
    import pypdfium2.raw as raw

    from docreader.pdfpages import MAX_OBJECT_DEPTH

    rules: list[Rule] = []
    form_stack: list[tuple[float, ...]] = []
    for obj in pdf_page.get_objects(max_depth=MAX_OBJECT_DEPTH):
        del form_stack[obj.level :]
        if obj.type == raw.FPDF_PAGEOBJ_FORM:
            form_stack.append(tuple(obj.get_matrix().get()))
        elif obj.type == raw.FPDF_PAGEOBJ_PATH:
            rules.extend(_path_rules(obj, list(reversed(form_stack))))
    return rules
