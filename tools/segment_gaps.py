"""Diagnose why lines split into several parts (flag reading_order_unknown).

Run by the analyst on the Mac, on real contracts:

    uv run python tools/segment_gaps.py D-0054 D-0055 D-0056

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
from docreader.pagetext import build_lines, read_page_chars
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


def main(ids: list[str]) -> None:
    settings = load_settings()
    conn = db.connect(settings)
    lines_total = multi_lines = pages_read = 0
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
                    lines = build_lines(read_page_chars(page))
                finally:
                    page.close()
                pages_read += 1
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

    print(f"страниц: {pages_read}, строк: {lines_total}, строк из нескольких частей: {multi_lines}")
    show("частей в строке", parts_per_line)
    show("вид разрыва", kinds)
    show("разрыв / высота строки", gaps_rel)
    show("разрыв, pt", gaps_pt)
    show("длина левой части, знаков", left_len)
    show("длина правой части, знаков", right_len)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Укажите идентификаторы: uv run python tools/segment_gaps.py D-0054 …")
    main(sys.argv[1:])
