"""Why are some scans read badly? Numbers only, for the analyst's Mac.

Run from the repository root (the engine runs, so `DOCREADER_FORBID_MODELS` must be unset):

    uv run --group ocr --env-file .env python scripts/diagnose_scans.py D-0056 D-0027

Part 1 — the `reading_order_unknown` flag over all read pages (database only, seconds):
which rule raises it (rotated text or lines of several parts outside columns and tables),
on PDF-text pages or on recognised scans, how many lines, which documents.

Part 2 — every scan page of the named documents again (about 10 s a page): page size and
rotation, the embedded image (pixels, dpi, bits per pixel, compression), ink share, the raw
answer of Tesseract's orientation detector, quality and the share of Russian words at
0°/90°/180°/270°, text height and the share of vertical lines, and quality at a higher dpi.
Tesseract reads a quarter-turned page by itself (vertical lines), so 0° and 90° often score
the same: what matters is whether some turn beats the stored quality. A document with good
quality (D-0027 above) gives a baseline.

Only numbers, document ids, page numbers, rotation degrees, the OSD script name (Cyrillic,
Latin…) and PDF compression filter names are printed and saved (to
`$DOCREADER_DATA_DIR/reports/diag-scans-….txt`): no text, no file names, no requisites.
The summary may be sent to the agent.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

ROTATED = re.compile(r"(\d+) \S+ повёрнутого текста")
UNRESOLVED = re.compile(r"(\d+) \S+ из нескольких частей")
TURNS = (0, 90, 180, 270)
OSD_MIN_CONFIDENCE = 5.0  # the same cut as docreader.ocr_engines
TURN_GAIN = 0.10  # a turn this much better than the stored quality points at orientation


# --- part 1: the reading-order flag (pure; tested in tests/unit/test_diagnose_scans.py) ------


def parse_layout_reason(reason: str | None) -> tuple[int, int]:
    """(rotated lines, unresolved lines) from a `reading_order_unknown` reason; (0, 0) if none."""
    if not reason:
        return 0, 0
    rotated = ROTATED.search(reason)
    unresolved = UNRESOLVED.search(reason)
    return (int(rotated.group(1)) if rotated else 0, int(unresolved.group(1)) if unresolved else 0)


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "—"


def _median(values: Sequence[float]) -> str:
    return f"{statistics.median(values):.2f}" if values else "—"


_EDGES: tuple[tuple[int, int | None], ...] = ((1, 2), (3, 5), (6, 10), (11, 20), (21, None))


def buckets(values: Iterable[int]) -> str:
    """`3–5: 4, > 20: 1` — how many values fall into each range; `—` for none."""
    counts: Counter[tuple[int, int | None]] = Counter()
    for v in values:
        for low, high in _EDGES:
            if v >= low and (high is None or v <= high):
                counts[(low, high)] += 1
                break
    parts = [
        f"{low}–{high}: {counts[(low, high)]}" if high else f"> {low - 1}: {counts[(low, high)]}"
        for low, high in _EDGES
        if counts[(low, high)]
    ]
    return ", ".join(parts) or "—"


def reading_order_lines(rows: Iterable[tuple[str, str, int, str | None]]) -> list[str]:
    """Rows: (document id, page source `pdf`/`recognized`, lines on the page, flag reason)."""
    pages: Counter[str] = Counter()
    flagged: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
    per_doc: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for doc_id, source, n_lines, reason in rows:
        pages[source] += 1
        per_doc[doc_id][0] += 1
        if reason is not None:
            rotated, unresolved = parse_layout_reason(reason)
            flagged[source].append((rotated, unresolved, n_lines))
            per_doc[doc_id][1] += 1

    lines = ["Часть 1 — флаг «порядок чтения не определён» (reading_order_unknown)"]
    for source, title in (("pdf", "текстовый слой PDF"), ("recognized", "распознанные сканы")):
        found = flagged.get(source, [])
        lines.append(
            f"  {title}: страниц {pages[source]}, с флагом {len(found)} "
            f"({_pct(len(found), pages[source])})"
        )
        if not found:
            continue
        only_rot = sum(1 for r, u, _ in found if r and not u)
        only_unr = sum(1 for r, u, _ in found if u and not r)
        both = sum(1 for r, u, _ in found if r and u)
        unresolved_counts = [u for _, u, _ in found if u]
        rotated_counts = [r for r, _, _ in found if r]
        shares = [u / n for _, u, n in found if u and n]
        lines += [
            f"    только повёрнутый текст {only_rot}, только строки из частей {only_unr}, "
            f"оба {both}",
            f"    строк из частей на странице: {buckets(unresolved_counts)}; "
            f"медиана доли от строк страницы {_median(shares)}",
            f"    строк повёрнутого текста на странице: {buckets(rotated_counts)}",
        ]
    worst = sorted(
        ((doc_id, total, bad) for doc_id, (total, bad) in per_doc.items() if bad),
        key=lambda item: (-item[2] / item[1], item[0]),
    )[:10]
    lines.append("  документы с наибольшей долей флага (id: страниц, с флагом)")
    lines += [f"    {doc_id}: {total}, {bad}" for doc_id, total, bad in worst] or ["    нет"]
    return lines


# --- part 2: one scan page measured again (pure formatting, tested) ------------------------


@dataclass
class PageDiag:
    page: int
    size_pt: tuple[float, float]
    rotate: int
    image_px: tuple[int, int] | None
    image_dpi: float | None
    image_bpp: int | None
    image_filters: tuple[str, ...]
    ink: float
    stored_turn: int | None = None
    stored_quality: float | None = None
    osd_deg: int | None = None
    osd_conf: float | None = None
    osd_script: str | None = None
    osd_script_conf: float | None = None
    quality: dict[int, float | None] = field(default_factory=dict)  # turn → page quality
    score: dict[int, float] = field(default_factory=dict)  # turn → orientation_score
    line_count: dict[int, int] = field(default_factory=dict)
    text_height_px: float | None = None  # median of min(line width, height) at the best turn
    vertical_share: float | None = None  # lines taller than wide at the best turn
    extra_quality: float | None = None  # best turn at the extra dpi
    errors: list[str] = field(default_factory=list)

    @property
    def best_turn(self) -> int:
        """Highest quality; on a tie (to 0.01) the stored turn, then the smaller turn."""
        return max(
            TURNS,
            key=lambda t: (round(self.quality.get(t) or 0.0, 2), t == self.stored_turn, -t),
        )

    @property
    def gain(self) -> float | None:
        """How much the best turn beats the stored quality."""
        best = self.quality.get(self.best_turn)
        if best is None or self.stored_quality is None:
            return None
        return best - self.stored_quality


def _q(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


def page_line(d: PageDiag) -> str:
    image = (
        f"{d.image_px[0]}×{d.image_px[1]} px, "
        f"{f'{d.image_dpi:.0f}' if d.image_dpi else '?'} dpi, {d.image_bpp} бит, "
        f"{'+'.join(d.image_filters) or '—'}"
        if d.image_px
        else "картинки нет"
    )
    osd = (
        f"{d.osd_deg}° ув. {d.osd_conf:.1f}, {d.osd_script} {d.osd_script_conf or 0:.1f}"
        if d.osd_deg is not None and d.osd_conf is not None
        else "нет ответа"
    )
    turns = " ".join(
        f"{t}:{_q(d.quality.get(t))}/{_q(d.score.get(t))}{'*' if t == d.best_turn else ''}"
        for t in TURNS
    )
    height = f"{d.text_height_px:.0f}" if d.text_height_px is not None else "—"
    vertical = f"{100 * d.vertical_share:.0f}%" if d.vertical_share is not None else "—"
    stored = f"{d.stored_turn}°/{_q(d.stored_quality)}" if d.stored_turn is not None else "—"
    text = (
        f"  стр. {d.page}: {d.size_pt[0]:.0f}×{d.size_pt[1]:.0f} pt, /Rotate {d.rotate}; {image}; "
        f"чернила {100 * d.ink:.1f}%; OSD {osd}; качество/рус. {turns}; "
        f"строк {d.line_count.get(d.best_turn, 0)}, высота текста {height} px, "
        f"вертикальных {vertical}; "
        f"доп. dpi {_q(d.extra_quality)}; в базе {stored}"
    )
    if d.errors:
        text += f"; ошибки: {', '.join(d.errors)}"
    return text


def document_lines(doc_id: str, pages: Sequence[PageDiag], dpi: int, extra_dpi: int) -> list[str]:
    head = f"Документ {doc_id}: страниц-сканов {len(pages)}, dpi {dpi}, доп. dpi {extra_dpi or '—'}"
    if not pages:
        return [head, "  страниц-сканов нет"]
    osd = Counter(
        f"{p.osd_deg}°"
        if p.osd_deg is not None and (p.osd_conf or 0.0) >= OSD_MIN_CONFIDENCE
        else "нет ответа"
        for p in pages
    )
    best = Counter(f"{p.best_turn}°" for p in pages)
    better = sum(1 for p in pages if (g := p.gain) is not None and g >= TURN_GAIN)
    dpis = [p.image_dpi for p in pages if p.image_dpi]
    heights = [p.text_height_px for p in pages if p.text_height_px is not None]
    vertical = [100 * p.vertical_share for p in pages if p.vertical_share is not None]
    stored = [p.stored_quality for p in pages if p.stored_quality is not None]
    at_best = [q for p in pages if (q := p.quality.get(p.best_turn)) is not None]
    extra = [p.extra_quality for p in pages if p.extra_quality is not None]
    bpp = Counter(str(p.image_bpp) for p in pages if p.image_bpp is not None)
    filters = Counter("+".join(p.image_filters) or "—" for p in pages if p.image_px)
    return [
        head,
        f"  OSD: {dict(osd)}; лучший поворот по качеству: {dict(best)}; "
        f"другой поворот поднял бы качество на ≥ {TURN_GAIN:.2f}: {better}",
        f"  качество: в базе медиана {_median(stored)}, при лучшем повороте {_median(at_best)}, "
        f"при доп. dpi {_median(extra)}",
        f"  картинка: dpi медиана {statistics.median(dpis):.0f} (мин. {min(dpis):.0f})"
        if dpis
        else "  картинка: нет данных о dpi",
        f"  бит на пиксель {dict(bpp)}; сжатие {dict(filters)}",
        f"  высота текста при {dpi} dpi, px: медиана {_median(heights)}; "
        f"вертикальных строк медиана {_median(vertical)}%; "
        f"чернила медиана {_median([100 * p.ink for p in pages])}%",
        "  по страницам (качество/доля русских слов; * — лучший поворот по качеству):",
        *(page_line(p) for p in pages),
    ]


# --- the run (needs the engine; checked by hand on synthetic files) -------------------------


class Stop(Exception):
    """A precondition failed; the message says what to do."""


def _clockwise(image: Any, turn: int) -> Any:
    from PIL import Image

    method = {
        90: Image.Transpose.ROTATE_270,
        180: Image.Transpose.ROTATE_180,
        270: Image.Transpose.ROTATE_90,
    }
    return image if turn == 0 else image.transpose(method[turn])


def _main_image(page: Any) -> tuple[tuple[int, int] | None, float | None, int | None, tuple]:
    """Pixels, dpi, bits per pixel and filters of the largest image on the page."""
    import pypdfium2.raw as pdfium_c

    from docreader.pdfpages import MAX_OBJECT_DEPTH

    best: tuple[int, Any, Any] | None = None
    for obj in page.get_objects(max_depth=MAX_OBJECT_DEPTH):
        if obj.type != pdfium_c.FPDF_PAGEOBJ_IMAGE:
            continue
        meta = obj.get_metadata()
        if best is None or meta.width * meta.height > best[0]:
            best = (meta.width * meta.height, obj, meta)
    if best is None:
        return None, None, None, ()
    _, obj, meta = best
    dpi = (meta.horizontal_dpi + meta.vertical_dpi) / 2 or None
    try:
        filters = tuple(obj.get_filters())
    except Exception:
        filters = ()
    return (meta.width, meta.height), dpi, meta.bits_per_pixel, filters


def _osd_api(settings: Any) -> Any:
    """Tesseract's orientation detector, created only after load_engine passed its guards."""
    import tesserocr

    if settings.recognition.model_dir:
        path, languages = tesserocr.get_languages(settings.recognition.model_dir)
    else:
        path, languages = tesserocr.get_languages()
    if "osd" not in languages:
        return None
    return tesserocr.PyTessBaseAPI(path=path, lang="osd", psm=tesserocr.PSM.OSD_ONLY)


def measure_page(
    pdf: Any,
    number: int,
    engine: Any,
    osd: Any,
    dpi: int,
    extra_dpi: int,
    stored: tuple[int, float | None] | None,
) -> PageDiag:
    from docreader.ocr import ink_share, orientation_score, page_quality, render_page

    page = pdf[number - 1]
    try:
        size = page.get_size()
        rotate = page.get_rotation() % 360
        image_px, image_dpi, bpp, filters = _main_image(page)
        image = render_page(page, dpi)
        extra_image = render_page(page, extra_dpi) if extra_dpi else None
    finally:
        page.close()
    diag = PageDiag(
        page=number,
        size_pt=(size[0], size[1]),
        rotate=rotate,
        image_px=image_px,
        image_dpi=image_dpi,
        image_bpp=bpp,
        image_filters=filters,
        ink=ink_share(image),
        stored_turn=stored[0] if stored else None,
        stored_quality=stored[1] if stored else None,
    )
    if osd is not None:
        try:
            osd.SetImage(image)
            found = osd.DetectOrientationScript()
        except RuntimeError as exc:
            found = None
            diag.errors.append(f"OSD {type(exc).__name__}")
        if found:
            diag.osd_deg = int(found["orient_deg"])
            diag.osd_conf = float(found["orient_conf"])
            diag.osd_script = str(found.get("script_name"))
            diag.osd_script_conf = float(found.get("script_conf", 0.0))
    boxes: dict[int, list[tuple[float, float]]] = {}
    for turn in TURNS:
        try:
            output = engine.recognize(_clockwise(image, turn))
        except Exception as exc:
            diag.errors.append(f"{turn}° {type(exc).__name__}")
            continue
        diag.quality[turn] = page_quality(output.lines)
        diag.score[turn] = orientation_score(output.lines)
        diag.line_count[turn] = len(output.lines)
        boxes[turn] = [(ln.box[2] - ln.box[0], ln.box[3] - ln.box[1]) for ln in output.lines]
    best = diag.best_turn
    if boxes.get(best):
        diag.text_height_px = statistics.median(min(w, h) for w, h in boxes[best])
        diag.vertical_share = sum(1 for w, h in boxes[best] if h > w) / len(boxes[best])
    if extra_image is not None:
        try:
            extra = engine.recognize(_clockwise(extra_image, best))
            diag.extra_quality = page_quality(extra.lines)
        except Exception as exc:
            diag.errors.append(f"доп. dpi {type(exc).__name__}")
    return diag


def measure_document(
    conn: Any, settings: Any, doc_id: str, engine: Any, osd: Any, extra_dpi: int, max_pages: int
) -> list[PageDiag]:
    from docreader.pdfpages import KIND_SCAN, open_pdf

    row = conn.execute("SELECT copy_path FROM document WHERE id = %s", (doc_id,)).fetchone()
    if row is None:
        raise Stop(f"документ {doc_id} не найден — список: docreader list")
    path = settings.data_dir / row[0]
    if not path.is_file():
        raise Stop(f"нет копии {doc_id} — docreader verify {doc_id}")
    numbers = [
        r[0]
        for r in conn.execute(
            "SELECT page_number FROM page WHERE document_id = %s AND kind = %s"
            " AND image_coverage > 0 ORDER BY page_number",
            (doc_id, KIND_SCAN),
        )
    ]
    if max_pages and len(numbers) > max_pages:  # evenly spread over the document
        step = len(numbers) / max_pages
        numbers = [numbers[int(i * step)] for i in range(max_pages)]
    stored = {
        n: (t, q)
        for n, t, q in conn.execute(
            "SELECT page_number, turn, quality FROM page_recognition"
            " WHERE document_id = %s AND error IS NULL",
            (doc_id,),
        )
    }
    pdf = open_pdf(path)
    try:
        result = []
        for i, number in enumerate(numbers, 1):
            started = time.monotonic()
            result.append(
                measure_page(
                    pdf, number, engine, osd, settings.recognition.dpi, extra_dpi,
                    stored.get(number),
                )
            )
            print(
                f"  {doc_id} стр. {number} ({i}/{len(numbers)}) "
                f"{time.monotonic() - started:.1f} с",
                file=sys.stderr,
                flush=True,
            )
        return result
    finally:
        pdf.close()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Разбор плохо распознанных сканов: только цифры.")
    parser.add_argument("ids", nargs="*", metavar="ID", help="документы для части 2 (D-0056…)")
    parser.add_argument(
        "--extra-dpi", type=int, default=400,
        help="повторить лучший поворот при этом dpi (0 — не повторять)",
    )
    parser.add_argument(
        "--max-pages", type=int, default=0,
        help="не больше стольких страниц на документ, равномерно (0 — все)",
    )
    args = parser.parse_args(argv)

    from docreader import db, ocr_engines
    from docreader.config import load_settings
    from docreader.errors import EnvironmentProblem, UserError
    from docreader.ids import format_document_id, parse_document_id

    try:
        settings = load_settings()
        ids = [format_document_id(parse_document_id(raw)) for raw in args.ids]
        conn = db.connect(settings)
        db.ensure_schema_current(conn)
        rows = conn.execute(
            "SELECT pt.document_id, pt.source, jsonb_array_length(pt.lines), pf.reason"
            " FROM page_text pt LEFT JOIN page_flag pf ON pf.document_id = pt.document_id"
            " AND pf.page_number = pt.page_number AND pf.code = 'reading_order_unknown'"
            " ORDER BY pt.document_id, pt.page_number"
        ).fetchall()
        lines = [
            "Разбор сканов, фича 13 — только цифры",
            f"Дата: {datetime.now().isoformat(timespec='minutes')}",
            "",
            *reading_order_lines(rows),
        ]
        if ids:
            print("Часть 2: распознавание страниц заново…", file=sys.stderr, flush=True)
            engine = ocr_engines.load_engine(settings.recognition, settings.data_dir)
            osd = _osd_api(settings)
            lines += [
                "",
                f"Часть 2 — страницы-сканы заново ({engine.name} {engine.version}; "
                f"OSD {'есть' if osd is not None else 'нет'})",
            ]
            for doc_id in ids:
                pages = measure_document(
                    conn, settings, doc_id, engine, osd, args.extra_dpi, args.max_pages
                )
                lines += document_lines(doc_id, pages, settings.recognition.dpi, args.extra_dpi)
    except (Stop, EnvironmentProblem, UserError, ValueError) as exc:
        print(f"\nОстановлено: {exc}", file=sys.stderr)
        return 1
    text = "\n".join(lines) + "\n"
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"diag-scans-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
