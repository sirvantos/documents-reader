"""Diagnose why lines split into several parts (flag reading_order_unknown).

Run by the analyst on the Mac, on real contracts:

    uv run python tools/segment_gaps.py D-0054 D-0055 D-0056
    uv run python tools/segment_gaps.py --pages D-0056      # one row per page
    uv run python tools/segment_gaps.py --lines D-0054 71   # segments of one page

Prints numbers only — counts and gap sizes, never text of the contract — so the output
may be shared with the coding agent (CLAUDE.md, principle I).

For every line with two or more parts it looks at each break between neighbouring parts:
- the gap in units of the line height (about the font size) and in points;
- whether the break is a «jump back» (the next char starts left of the previous one);
- whether the left part looks like a clause number («5.2.», «3)», «а)»);
- how long the left and right parts are (in chars).
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from itertools import pairwise

from docreader import db
from docreader.config import load_settings
from docreader.ids import parse_document_id
from docreader.pagetext import _parts, build_lines, layout_page, read_page_chars, read_page_rules
from docreader.pdfpages import open_pdf

_CLAUSE_NUMBER = re.compile(r"^(\d+(\.\d+)*\.?|\d+\)|[а-яa-z]\))$", re.IGNORECASE)
_GAP_BUCKETS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0)


def _bucket(value: float, edges: tuple[float, ...]) -> str:
    if value < edges[0]:
        return f"< {edges[0]:g}"
    for low, high in pairwise(edges):
        if value < high:
            return f"{low:g}–{high:g}"
    return f">= {edges[-1]:g}"


def _length_bucket(n: int) -> str:
    return "1–3" if n <= 3 else "4–10" if n <= 10 else "11–30" if n <= 30 else "> 30"


def _object_counts(page) -> Counter[str]:  # page: pypdfium2.PdfPage
    """Top-level page objects by type: text, path (lines, rectangles), image, form."""
    import pypdfium2.raw as raw

    names = {
        raw.FPDF_PAGEOBJ_TEXT: "текст",
        raw.FPDF_PAGEOBJ_PATH: "контуры",
        raw.FPDF_PAGEOBJ_IMAGE: "изображения",
        raw.FPDF_PAGEOBJ_FORM: "формы",
    }
    return Counter(names.get(obj.type, "прочее") for obj in page.get_objects(max_depth=1))


def main(ids: list[str], per_page: bool = False) -> None:
    settings = load_settings()
    conn = db.connect(settings)
    lines_total = multi_lines = multi_part_lines = pages_read = 0
    flagged_pages = 0
    gaps_rel: Counter[str] = Counter()
    gaps_pt: Counter[str] = Counter()
    left_len: Counter[str] = Counter()
    right_len: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    parts_per_line: Counter[int] = Counter()
    for raw_id in ids:
        seq = parse_document_id(raw_id)
        row = conn.execute("SELECT id, copy_path FROM document WHERE seq = %s", (seq,)).fetchone()
        if row is None:
            print(f"{raw_id}: нет в реестре")
            continue
        doc_id, copy_path = row
        text_pages = {
            n
            for (n,) in conn.execute(
                "SELECT page_number FROM page WHERE document_id = %s AND kind = 'text'", (doc_id,)
            )
        }
        pdf = open_pdf(settings.data_dir / copy_path)
        try:
            for number in sorted(text_pages):
                page = pdf[number - 1]
                try:
                    if page.get_rotation() % 360:
                        kinds["страница повёрнута, пропущена"] += 1
                        continue
                    chars = read_page_chars(page)
                    lines = build_lines(chars)
                    if per_page:
                        rules = read_page_rules(page)
                        left, bottom, right, top = page.get_cropbox()
                        layout = layout_page(
                            chars,
                            rotation=0,
                            width=right - left,
                            height=top - bottom,
                            rules=rules,
                            settings=settings.reading,
                        )
                        horizontal = sum(1 for r in rules if abs(r.y1 - r.y0) < abs(r.x1 - r.x0))
                        objects = _object_counts(page)
                finally:
                    page.close()
                pages_read += 1
                wide = sum(1 for line in lines if len(_parts(line, settings.reading)) >= 2)
                if per_page:
                    shown = ", ".join(f"{k} {v}" for k, v in sorted(objects.items()))
                    print(
                        f"{raw_id} стр. {number}: строк {len(lines)}, из частей {wide}, "
                        f"неясных {layout.unresolved_lines}, линий гор./верт. "
                        f"{horizontal}/{len(rules) - horizontal}, "
                        f"таблица {'да' if layout.has_table else 'нет'}; объекты: {shown}"
                    )
                multi_part_lines += wide
                flagged_pages += wide >= 3  # the flag rule before columns and tables
                for line in lines:
                    lines_total += 1
                    if len(line.segments) < 2:
                        continue
                    multi_lines += 1
                    parts_per_line[len(line.segments)] += 1
                    height = max(line.bbox[3] - line.bbox[1], 0.1)
                    for left, right in pairwise(line.segments):
                        gap = right.bbox[0] - left.bbox[2]
                        if right.bbox[0] < left.bbox[0]:
                            kinds["скачок назад"] += 1
                        elif _CLAUSE_NUMBER.match(left.text.strip()):
                            kinds["после номера пункта"] += 1
                        else:
                            kinds["прочие разрывы"] += 1
                        gaps_rel[_bucket(gap / height, _GAP_BUCKETS)] += 1
                        gaps_pt[_bucket(gap, (0.0, 5.0, 10.0, 15.0, 20.0, 40.0, 80.0))] += 1
                        left_len[_length_bucket(len(left.text))] += 1
                        right_len[_length_bucket(len(right.text))] += 1
        finally:
            pdf.close()

    def show(title: str, counter: Counter) -> None:
        print(f"\n{title}")
        for key, count in sorted(counter.items(), key=lambda kv: str(kv[0])):
            print(f"  {key:>14}: {count}")

    print(f"страниц: {pages_read}, строк: {lines_total}, из нескольких отрезков: {multi_lines}")
    print(
        f"по правилу частей (wide_gap_factor = {settings.reading.wide_gap_factor}): "
        f"строк из нескольких частей {multi_part_lines}, "
        f"страниц с 3 и более такими строками {flagged_pages} (до учёта колонок и таблиц)"
    )
    show("частей в строке", parts_per_line)
    show("вид разрыва", kinds)
    show("разрыв / высота строки", gaps_rel)
    show("разрыв, pt", gaps_pt)
    show("длина левой части, знаков", left_len)
    show("длина правой части, знаков", right_len)


def show_lines(raw_id: str, number: int) -> None:
    """Every line of one page: its box and its segments with the gaps between them.

    Numbers only: positions in pt, char counts, gaps in pt and in line heights.
    `частей` and `разрез` are what the column rule sees (`_parts`, `_gap_position`).
    """
    settings = load_settings()
    conn = db.connect(settings)
    seq = parse_document_id(raw_id)
    row = conn.execute("SELECT id, copy_path FROM document WHERE seq = %s", (seq,)).fetchone()
    if row is None:
        sys.exit(f"{raw_id}: нет в реестре")
    pdf = open_pdf(settings.data_dir / row[1])
    try:
        page = pdf[number - 1]
        try:
            lines = build_lines(read_page_chars(page))
        finally:
            page.close()
    finally:
        pdf.close()
    print(f"{raw_id} стр. {number}: строк {len(lines)} (сверху вниз, до раскладки)")
    print(
        "строка: [x0, y0, x1, y1] высота | частей, разрез x | "
        "отрезки x0–x1 (знаков) +разрыв pt/высот"
    )
    for i, line in enumerate(lines):
        x0, y0, x1, y1 = line.bbox
        height = max(y1 - y0, 0.1)
        parts = _parts(line, settings.reading)
        cut = f"{parts[1][0].bbox[0]:.1f}" if len(parts) == 2 else "-"
        pieces = []
        previous = None
        for seg in line.segments:
            piece = f"{seg.bbox[0]:.1f}–{seg.bbox[2]:.1f} ({len(seg.text.strip())})"
            if previous is not None:
                gap = seg.bbox[0] - previous.bbox[2]
                piece = f"+{gap:.1f}/{gap / height:.1f} " + piece
            pieces.append(piece)
            previous = seg
        print(
            f"{i:3}: [{x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f}] {height:.1f} | "
            f"{len(parts)}, {cut} | " + "  ".join(pieces)
        )


if __name__ == "__main__":
    if sys.argv[1:2] == ["--lines"]:
        if len(sys.argv) != 4:
            sys.exit("Укажите документ и страницу: segment_gaps.py --lines D-0054 71")
        show_lines(sys.argv[2], int(sys.argv[3]))
        sys.exit(0)
    args = [a for a in sys.argv[1:] if a != "--pages"]
    if not args:
        sys.exit("Укажите идентификаторы: uv run python tools/segment_gaps.py [--pages] D-0054 …")
    main(args, per_page="--pages" in sys.argv[1:])
