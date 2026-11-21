"""Quickstart Б6 (task T053), step 1: prepare the folder the analyst checks by hand.

Run once on the analyst's Mac from the repository root, after quickstart Б5:

    uv run --group ocr --env-file .env python scripts/prepare_b6.py

It creates `$DOCREADER_DATA_DIR/ocr-eval/` (never overwrites a file that is there):

- `pages/D-XXXX-pNNN.txt` — the recognised text of ~20 scan pages from ≥ 10 documents,
  a draft the analyst corrects to what is printed (SC-002, SC-004);
- `control.csv` — draft control strings found in those drafts (SC-003);
- `flags.csv` — 20 flagged and 20 unflagged pages with an empty «плохая» column (SC-007);
- `review/` — for every chosen page: the page image, the recognised text, a list of
  suspicious places (low-confidence lines, ИНН/ОГРН with a wrong check digit, impossible
  dates, lines that change at 400 dpi); for 10 pages also the image with line boxes
  (SC-005); and `index.csv` saying which page is for what.

Everything stays in the data folder. The terminal gets only counts and shares: no text,
no file names. `--no-engine` skips the 400 dpi comparison (then no engine is needed).
"""

from __future__ import annotations

import argparse
import csv
import io
import random
import re
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

PREVIEW_DPI = 150
COMPARE_DPI = 400
BOX_INK_FACTOR = 1.5  # a box lies on text if its dark share is this many times the page's
BOX_MIN_INK = 0.02  # … and at least this share of its pixels is dark


# --- suspicious values (pure; tested in tests/unit/test_prepare_b6.py) ---------------------


def inn_valid(inn: str) -> bool:
    """Check digits of a Russian ИНН (10 digits for an organisation, 12 for a person)."""
    if not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(c) for c in inn]

    def check(weights: Sequence[int]) -> int:
        return sum(w * x for w, x in zip(weights, d, strict=False)) % 11 % 10

    if len(d) == 10:
        return check((2, 4, 10, 3, 5, 9, 4, 6, 8)) == d[9]
    return (
        check((7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == d[10]
        and check((3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == d[11]
    )


def ogrn_valid(ogrn: str) -> bool:
    """Check digit of ОГРН (13 digits) or ОГРНИП (15 digits)."""
    if not ogrn.isdigit() or len(ogrn) not in (13, 15):
        return False
    body, last = int(ogrn[:-1]), int(ogrn[-1])
    return body % (11 if len(ogrn) == 13 else 13) % 10 == last


def date_valid(text: str) -> bool:
    """`дд.мм.гггг` is a real calendar date between 1990 and 2040."""
    if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
        return False
    day, month, year = (int(part) for part in text.split("."))
    try:
        date(year, month, day)
    except ValueError:
        return False
    return 1990 <= year <= 2040


# letters an engine puts for digits (О/O for 0, З for 3, б/Б for 6) are caught as well
_DIGITISH = r"[\dOoОоЗзбБ]"
_INN = re.compile(rf"ИНН\s*:?\s*({_DIGITISH}{{9,13}})")
_OGRN = re.compile(rf"ОГРН(?:ИП)?\s*:?\s*({_DIGITISH}{{12,16}})")
_KPP = re.compile(rf"КПП\s*:?\s*({_DIGITISH}{{7,11}})")
_DATE = re.compile(r"(?<![\d.])(\d{1,2}\.\d{1,2}\.\d{2,4})(?![\d.])")


def suspicious_values(text: str) -> list[str]:
    """Requisites and dates of a recognised text that cannot be right, as short notes."""
    notes: list[str] = []
    for match in _INN.finditer(text):
        if not inn_valid(match.group(1)):
            notes.append(f"ИНН «{match.group(1)}»: неверная длина, буквы или контрольная цифра")
    for match in _OGRN.finditer(text):
        if not ogrn_valid(match.group(1)):
            notes.append(f"ОГРН «{match.group(1)}»: неверная длина, буквы или контрольная цифра")
    for match in _KPP.finditer(text):
        value = match.group(1)
        if not (value.isdigit() and len(value) == 9):
            notes.append(f"КПП «{value}»: должно быть 9 цифр")
    for match in _DATE.finditer(text):
        if not date_valid(match.group(1)):
            notes.append(f"дата «{match.group(1)}»: такой даты нет или формат сломан")
    return notes


# --- choosing pages (pure, tested) ---------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    doc_id: str
    page: int
    quality: float | None
    flagged: bool
    lines: int
    requisites: bool  # ИНН, КПП or ОГРН on the page
    amount: bool


def _round_robin(
    groups: Mapping[str, list[Candidate]],
    n: int,
    rng: random.Random,
    taken: set[tuple[str, int]] | None = None,
) -> list[Candidate]:
    """Up to `n` candidates, one per document in turn; documents in random order."""
    skip = taken or set()
    queues = {
        doc: [c for c in items if (c.doc_id, c.page) not in skip] for doc, items in groups.items()
    }
    for items in queues.values():
        rng.shuffle(items)
    docs = sorted(queues)
    rng.shuffle(docs)
    chosen: list[Candidate] = []
    while len(chosen) < n and any(queues[d] for d in docs):
        for doc in docs:
            if queues[doc] and len(chosen) < n:
                chosen.append(queues[doc].pop())
    return chosen


def select_eval_pages(candidates: Sequence[Candidate], n_pages: int, seed: int) -> list[Candidate]:
    """Pages to verify: a requisites page and an amount page (from different documents)
    first, then one page per document in turn, new documents before used ones."""
    rng = random.Random(seed)
    usable = sorted((c for c in candidates if c.lines >= 5), key=lambda c: (c.doc_id, c.page))
    chosen: list[Candidate] = []
    for wanted in ("requisites", "amount"):
        used = {c.doc_id for c in chosen}
        pool = [c for c in usable if getattr(c, wanted) and c.doc_id not in used]
        if pool and len(chosen) < n_pages:
            chosen.append(rng.choice(pool))
    used = {c.doc_id for c in chosen}
    fresh: dict[str, list[Candidate]] = defaultdict(list)
    for c in usable:
        if c.doc_id not in used:
            fresh[c.doc_id].append(c)
    taken = {(c.doc_id, c.page) for c in chosen}
    chosen += _round_robin(fresh, min(len(fresh), n_pages - len(chosen)), rng, taken)
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for c in usable:
        groups[c.doc_id].append(c)
    taken = {(c.doc_id, c.page) for c in chosen}
    chosen += _round_robin(groups, n_pages - len(chosen), rng, taken)
    return sorted(chosen, key=lambda c: (c.doc_id, c.page))


def select_flag_pages(
    candidates: Sequence[Candidate], per_group: int, seed: int
) -> list[Candidate]:
    """`per_group` flagged and `per_group` unflagged pages, spread over the documents."""
    rng = random.Random(seed + 1)
    chosen: list[Candidate] = []
    for flagged in (True, False):
        groups: dict[str, list[Candidate]] = defaultdict(list)
        for c in sorted(candidates, key=lambda c: (c.doc_id, c.page)):
            if c.flagged == flagged:
                groups[c.doc_id].append(c)
        chosen += _round_robin(groups, per_group, rng)
    return sorted(chosen, key=lambda c: (c.doc_id, c.page))


def control_rows(
    drafts: Mapping[tuple[str, int], str], per_doc: int = 6
) -> list[tuple[str, str, str]]:
    """Draft `control.csv` rows: requisites and numbers found in the drafts, per document."""
    from docreader.recognition_eval import extract_values

    rows: list[tuple[str, str, str]] = []
    seen: dict[str, set[str]] = defaultdict(set)
    for (doc_id, _page), text in sorted(drafts.items()):
        for kind, value in extract_values(text):
            if value in seen[doc_id] or len(seen[doc_id]) >= per_doc:
                continue
            seen[doc_id].add(value)
            rows.append((doc_id, value, kind))
    return rows


def csv_text(header: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def check_notes(
    lines: Sequence[Mapping], low: float, other: Sequence[str] | None
) -> str:
    """The `review/….check.txt` text: places to look at first on one page."""
    from docreader.recognition_eval import line_diffs
    from docreader.textnorm import normalize_chars

    head = [
        "Что проверить в первую очередь (номер строки — как в файле pages/ и review/*.txt)",
        "",
    ]
    notes: list[str] = []
    for n, line in enumerate(lines, 1):
        if line["confidence"] < low and any(ch.isalnum() for ch in line["text"]):
            notes.append(f"строка {n}: уверенность {line['confidence']:.2f} — {line['text']}")
    text = "\n".join(line["text"] for line in lines)
    notes += suspicious_values(text)
    if other is not None:
        # line_diffs compares normalised lines; map them back to line numbers of the file
        numbers = {
            " ".join(normalize_chars(ln["text"]).split()): n for n, ln in enumerate(lines, 1)
        }
        for verified, match in line_diffs(text, "\n".join(other)):
            # rules and blanks without a letter or digit are not worth a look
            if match != verified and any(ch.isalnum() for ch in verified):
                where = numbers.get(verified, "?")
                notes.append(
                    f"строка {where}: при {COMPARE_DPI} dpi читается иначе — «{match or 'нет'}»"
                )
    if not notes:
        notes.append("подозрительного не найдено — прочитайте страницу целиком")
    return "\n".join(head + notes) + "\n"


# --- boxes on the image (pure, tested) -----------------------------------------------------


def pdf_box_to_image(
    bbox: Sequence[float], crop: Sequence[float], rotation: int, scale: float
) -> tuple[float, float, float, float]:
    """`(left, bottom, right, top)` in unrotated PDF space → image pixels `(l, t, r, b)`
    of the page rendered in display orientation at `scale` pixels per point."""
    from docreader.ocr import display_point

    width, height = crop[2] - crop[0], crop[3] - crop[1]
    disp_h = width if rotation in (90, 270) else height
    xs, ys = [], []
    for x in (bbox[0], bbox[2]):
        for y in (bbox[1], bbox[3]):
            dx, dy = display_point(x - crop[0], y - crop[1], rotation, width, height)
            xs.append(dx * scale)
            ys.append((disp_h - dy) * scale)
    return min(xs), min(ys), max(xs), max(ys)


def ink_threshold(image: Any) -> int:
    """Grey level between the background (median) and the darkest 0.1% of a grey image.

    A faded scan has grey text that never goes below 128; a fixed cut would see no ink.
    Without contrast (a blank page) the usual 128 is kept.
    """
    histogram = image.histogram()
    total = sum(histogram)
    if total == 0:
        return 128
    seen, darkest, median = 0, None, None
    for level, count in enumerate(histogram):
        seen += count
        if darkest is None and seen >= 0.001 * total:
            darkest = level
        if median is None and seen >= 0.5 * total:
            median = level
            break
    assert darkest is not None and median is not None
    return 128 if median - darkest < 30 else (median + darkest) // 2


def dark_share(image: Any, box: Sequence[float] | None = None, threshold: int = 128) -> float:
    """Share of pixels darker than `threshold` in a grey image, or in a box of it."""
    if box is None:
        region = image
    else:
        left, top, right, bottom = (round(v) for v in box)
        region = image.crop((left, top, max(right, left + 1), max(bottom, top + 1)))
    total = region.size[0] * region.size[1]
    return sum(region.histogram()[:threshold]) / total if total > 0 else 0.0


def box_on_ink(image: Any, box: Sequence[float], page_ink: float, threshold: int = 128) -> bool:
    share = dark_share(image, box, threshold)
    return share >= BOX_MIN_INK and share >= BOX_INK_FACTOR * page_ink


# --- the run (needs the data; checked by hand on synthetic files) --------------------------


class Stop(Exception):
    """A precondition failed; the message says what to do."""


def _write_new(path: Path, data: str | bytes, counts: dict[str, int]) -> None:
    if path.exists():
        counts["kept"] += 1
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")
    counts["written"] += 1


def _png(image: Any) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _load_candidates(conn: Any, settings: Any) -> tuple[list[Candidate], dict]:
    from docreader.quality import LOW_QUALITY, recognition_flags
    from docreader.recognition_eval import extract_values

    rows = conn.execute(
        "SELECT pr.document_id, pr.page_number, pr.lines, pr.quality, pr.ink_share,"
        " pr.orientation_unknown FROM page_recognition pr"
        " JOIN page p ON p.document_id = pr.document_id AND p.page_number = pr.page_number"
        " WHERE pr.error IS NULL AND p.kind = 'scan' ORDER BY pr.document_id, pr.page_number"
    ).fetchall()
    candidates, lines_by_page = [], {}
    for doc_id, page, lines, quality, ink, unknown in rows:
        flags = recognition_flags(lines, quality, ink, unknown, settings.recognition)
        kinds = {kind for kind, _ in extract_values("\n".join(ln["text"] for ln in lines))}
        candidates.append(
            Candidate(
                doc_id=doc_id,
                page=page,
                quality=quality,
                flagged=any(f.code == LOW_QUALITY for f in flags),
                lines=len(lines),
                requisites=bool(kinds & {"inn", "kpp", "ogrn"}),
                amount="amount" in kinds,
            )
        )
        lines_by_page[(doc_id, page)] = lines
    return candidates, lines_by_page


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подготовка ручной проверки Б6 (T053).")
    parser.add_argument("--folder", help="папка замера (по умолчанию <папка данных>/ocr-eval)")
    parser.add_argument("--pages", type=int, default=20, help="страниц на выверку (20)")
    parser.add_argument("--flags", type=int, default=20, help="страниц в группе флага (20)")
    parser.add_argument("--boxes", type=int, default=10, help="страниц с рамками строк (10)")
    parser.add_argument("--seed", type=int, default=13, help="зерно случайного выбора")
    parser.add_argument(
        "--no-engine", action="store_true", help=f"не сравнивать с {COMPARE_DPI} dpi"
    )
    args = parser.parse_args(argv)

    from PIL import ImageDraw

    from docreader import db
    from docreader.config import load_settings
    from docreader.errors import EnvironmentProblem
    from docreader.ocr import render_page
    from docreader.pdfpages import open_pdf

    try:
        settings = load_settings()
        folder = Path(args.folder) if args.folder else settings.data_dir / "ocr-eval"
        if not folder.resolve().is_relative_to(settings.data_dir.resolve()):
            raise Stop("папка замера должна лежать в папке данных (там реальные тексты)")
        conn = db.connect(settings)
        db.ensure_schema_current(conn)
        candidates, lines_by_page = _load_candidates(conn, settings)
        if not candidates:
            raise Stop("распознанных страниц-сканов нет — сначала quickstart Б5")
        eval_pages = select_eval_pages(candidates, args.pages, args.seed)
        flag_pages = select_flag_pages(candidates, args.flags, args.seed)
        box_pages = eval_pages[: args.boxes]
        engine = None
        if not args.no_engine:
            from docreader import ocr_engines

            engine = ocr_engines.load_engine(settings.recognition, settings.data_dir)
    except (Stop, EnvironmentProblem) as exc:
        print(f"\nОстановлено: {exc}", file=sys.stderr)
        return 1

    # the same page pipeline as `recognize`, so the 400 dpi text is comparable
    from docreader.recognition import _recognize_page

    purposes: dict[tuple[str, int], list[str]] = defaultdict(list)
    for group, label in ((eval_pages, "выверка"), (flag_pages, "флаг"), (box_pages, "рамки")):
        for c in group:
            purposes[(c.doc_id, c.page)].append(label)
    chosen = {(c.doc_id, c.page): c for c in eval_pages + flag_pages}
    by_doc: dict[str, list[int]] = defaultdict(list)
    for doc_id, page in chosen:
        by_doc[doc_id].append(page)

    counts = {"written": 0, "kept": 0}
    review = folder / "review"
    drafts: dict[tuple[str, int], str] = {}
    on_ink: list[float] = []
    low = settings.recognition.line_min_confidence
    for i, doc_id in enumerate(sorted(by_doc), 1):
        copy = db.fetch_row(
            conn.execute("SELECT copy_path FROM document WHERE id = %s", (doc_id,))
        )[0]
        pdf = open_pdf(settings.data_dir / copy)
        try:
            for page in sorted(by_doc[doc_id]):
                name = f"{doc_id}-p{page:03d}"
                lines = lines_by_page[(doc_id, page)]
                text = "\n".join(line["text"] for line in lines) + "\n"
                todo = purposes[(doc_id, page)]
                if "выверка" in todo:
                    drafts[(doc_id, page)] = text
                    _write_new(folder / "pages" / f"{name}.txt", text, counts)
                _write_new(review / f"{name}.txt", text, counts)
                pdf_page = pdf[page - 1]
                try:
                    crop = tuple(pdf_page.get_cropbox())
                    rotation = pdf_page.get_rotation() % 360
                    image = render_page(pdf_page, PREVIEW_DPI)
                finally:
                    pdf_page.close()
                _write_new(review / f"{name}.png", _png(image), counts)
                other = None
                if engine is not None and "выверка" in todo:
                    result = _recognize_page(pdf, page, engine, COMPARE_DPI, settings.recognition)
                    other = [line["text"] for line in result.lines]
                _write_new(review / f"{name}.check.txt", check_notes(lines, low, other), counts)
                if "рамки" in todo:
                    reading = conn.execute(
                        "SELECT lines FROM page_text WHERE document_id = %s AND page_number = %s",
                        (doc_id, page),
                    ).fetchone()
                    shown = reading[0] if reading else lines
                    boxes = [
                        pdf_box_to_image(ln["bbox"], crop, rotation, PREVIEW_DPI / 72)
                        for ln in shown
                    ]
                    threshold = ink_threshold(image)
                    page_ink = dark_share(image, None, threshold)
                    hits = [box_on_ink(image, box, page_ink, threshold) for box in boxes]
                    if hits:
                        on_ink.append(sum(hits) / len(hits))
                    drawn = image.convert("RGB")
                    pen = ImageDraw.Draw(drawn)
                    for box, hit in zip(boxes, hits, strict=True):
                        pen.rectangle(box, outline=(0, 160, 0) if hit else (220, 0, 0), width=2)
                    _write_new(review / f"{name}-boxes.png", _png(drawn), counts)
                print(f"  {doc_id} стр. {page} (док. {i}/{len(by_doc)})", file=sys.stderr,
                      flush=True)
        finally:
            pdf.close()

    _write_new(
        folder / "control.csv", csv_text(("документ", "строка", "вид"), control_rows(drafts)),
        counts,
    )
    _write_new(
        folder / "flags.csv",
        csv_text(("документ", "страница", "плохая"), ((c.doc_id, c.page, "") for c in flag_pages)),
        counts,
    )
    index_rows = (
        (d, p, " + ".join(purposes[(d, p)]),
         f"{c.quality:.2f}" if c.quality is not None else "", "да" if c.flagged else "нет")
        for (d, p), c in sorted(chosen.items())
    )
    _write_new(
        review / "index.csv",
        csv_text(("документ", "страница", "для чего", "оценка", "флаг сейчас"), index_rows),
        counts,
    )

    boxes_line = (
        f"{100 * statistics.mean(on_ink):.1f}% рамок (мин. по странице {100 * min(on_ink):.1f}%)"
        if on_ink
        else "—"
    )
    summary = [
        "Подготовка Б6 (T053) — только цифры",
        f"  на выверку: {len(eval_pages)} стр. из {len({c.doc_id for c in eval_pages})} док.; "
        f"с реквизитами {sum(c.requisites for c in eval_pages)}, "
        f"с суммами {sum(c.amount for c in eval_pages)}",
        f"  на флаг: {sum(c.flagged for c in flag_pages)} с флагом, "
        f"{sum(not c.flagged for c in flag_pages)} без флага, "
        f"из {len({c.doc_id for c in flag_pages})} док.",
        f"  рамки: {len(box_pages)} стр.; лежат на тексте {boxes_line}",
        f"  сравнение с {COMPARE_DPI} dpi: {'нет' if engine is None else 'да'}",
        f"  файлов записано {counts['written']}, уже были и не тронуты {counts['kept']}",
    ]
    print("\n" + "\n".join(summary) + f"\n\nПапка: {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
