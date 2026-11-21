"""Automatic recognition check on pages that have a real PDF text layer (helps T053).

Run on the analyst's Mac from the repository root (the engine runs):

    uv run --group ocr --env-file .env python scripts/auto_eval_textlayer.py

Each text page of the set (clean text layer, no reading flags, ≥ 300 characters) is
rendered and recognised by the same page pipeline as `recognize`; the result is compared
with the page's own text layer as the reference:

- share of correct characters, the same formula as `recognize-eval` (order-sensitive),
  and the share of reference words found (order-free);
- requisites and numbers of the reference (ИНН, КПП, ОГРН, sums, dates, clause numbers)
  found verbatim in the recognised text;
- line boxes: recognised boxes that lie on a text-layer line, and text-layer lines
  covered by a recognised box (SC-005 by machine);
- how often the «низкое качество» flag fires on these clean pages.

A rendered page is cleaner than a real scan (no noise, skew or fading), so the numbers
are an upper bound and do not replace the hand check of scans. Nothing is written to the
database. Printed and saved (`$DOCREADER_DATA_DIR/reports/auto-eval-textlayer-….txt`):
only numbers and document ids with page numbers — no text. May be sent to the agent.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

BOX_COVER = 0.5  # a box "lies on" another when this share of its area is inside it
MIN_CHARS = 300
SKIP_FLAGS = ("unreadable", "ocr_text", "maybe_not_russian", "empty")


# --- pure part (tested in tests/unit/test_auto_eval_textlayer.py) --------------------------


def word_recall(expected: str, got: str) -> float:
    """Share of the reference words (with repeats) that the recognised text contains."""
    from docreader.textnorm import normalize_chars

    def words(text: str) -> Counter[str]:
        return Counter(w.strip(".,;:()«»\"'") for w in normalize_chars(text).lower().split())

    want, have = words(expected), words(got)
    want.pop("", None)
    total = sum(want.values())
    if total == 0:
        return 1.0
    return sum(min(n, have[w]) for w, n in want.items()) / total


Box = Sequence[float]  # left, bottom, right, top


def _area(b: Box) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def covered(box: Box, others: Sequence[Box]) -> bool:
    """`box` has at least BOX_COVER of its area inside one of `others`."""
    area = _area(box)
    if area <= 0:
        return False
    for o in others:
        inter = _area((max(box[0], o[0]), max(box[1], o[1]), min(box[2], o[2]), min(box[3], o[3])))
        if inter / area >= BOX_COVER:
            return True
    return False


def _grown(b: Box, pad: float) -> Box:
    return (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)


def box_match(recognised: Sequence[Box], reference: Sequence[Box], pad: float = 2.0
              ) -> tuple[int, int, int, int]:
    """(recognised boxes on a reference line, recognised, reference lines covered, reference).

    Boxes are grown by `pad` points: text-layer boxes are tight glyph boxes, engine boxes
    are pixel boxes, both are fine for highlighting a line.
    """
    ref = [_grown(b, pad) for b in reference]
    rec = [_grown(b, pad) for b in recognised]
    on = sum(1 for b in rec if covered(b, ref))
    hit = sum(1 for b in ref if covered(b, rec))
    return on, len(rec), hit, len(ref)


@dataclass
class PageResult:
    doc_id: str
    page: int
    chars: int
    distance: int
    words: float
    values: dict[str, tuple[int, int]] = field(default_factory=dict)
    boxes: tuple[int, int, int, int] = (0, 0, 0, 0)
    flagged: bool = False
    seconds: float = 0.0
    error: str | None = None

    @property
    def accuracy(self) -> float:
        return max(0.0, 1 - self.distance / self.chars) if self.chars else 1.0


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "—"


def summary_lines(results: Sequence[PageResult], dpi: int, engine: str) -> list[str]:
    done = [r for r in results if r.error is None]
    lines = [
        "Автозамер на страницах с текстовым слоем — только цифры",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        f"Движок: {engine}, {dpi} dpi; страниц {len(results)}, из них с ошибкой "
        f"{len(results) - len(done)}; документов {len({r.doc_id for r in results})}",
        "Оценка сверху: отрисованная страница чище настоящего скана.",
    ]
    if not done:
        return [*lines, "Распознанных страниц нет"]
    chars = sum(r.chars for r in done)
    distance = sum(r.distance for r in done)
    accuracies = [r.accuracy for r in done]
    values: dict[str, list[int]] = {}
    for r in done:
        for kind, (found, total) in r.values.items():
            pair = values.setdefault(kind, [0, 0])
            pair[0] += found
            pair[1] += total
    v_found = sum(p[0] for p in values.values())
    v_total = sum(p[1] for p in values.values())
    on = sum(r.boxes[0] for r in done)
    rec = sum(r.boxes[1] for r in done)
    hit = sum(r.boxes[2] for r in done)
    ref = sum(r.boxes[3] for r in done)
    kinds = ", ".join(f"{k} {p[0]}/{p[1]}" for k, p in sorted(values.items())) or "—"
    worst = sorted(done, key=lambda r: r.accuracy)[:10]
    lines += [
        "",
        f"Верных знаков (как recognize-eval, зависит от порядка строк): "
        f"{_pct(chars - distance, chars)} (по страницам: мин. {100 * min(accuracies):.1f}%, "
        f"медиана {100 * statistics.median(accuracies):.1f}%)",
        f"Найдено слов (без учёта порядка): медиана "
        f"{100 * statistics.median(r.words for r in done):.1f}%, "
        f"мин. {100 * min(r.words for r in done):.1f}%",
        f"Реквизиты и числа без ошибок: {_pct(v_found, v_total)} ({kinds})",
        f"Рамки: распознанных на строке текстового слоя {_pct(on, rec)} ({on} из {rec}); "
        f"строк текстового слоя под рамкой {_pct(hit, ref)} ({hit} из {ref})",
        f"Флаг «низкое качество» на этих чистых страницах: "
        f"{sum(r.flagged for r in done)} из {len(done)}",
        f"Время: медиана {statistics.median(r.seconds for r in done):.1f} с/стр.",
        "",
        "Худшие страницы по знакам (id стр.: знаки, слова, рамки на строке)",
        *(
            f"  {r.doc_id} стр. {r.page}: {100 * r.accuracy:.1f}%, {100 * r.words:.1f}%, "
            f"{_pct(r.boxes[0], r.boxes[1])}"
            for r in worst
        ),
    ]
    return lines


# --- the run (needs the engine; checked by hand on synthetic files) -------------------------


def _pages(conn: Any, max_pages: int, min_chars: int) -> list[tuple[str, int, str]]:
    from docreader.pdfpages import KIND_TEXT

    rows = conn.execute(
        "SELECT p.document_id, p.page_number, d.copy_path FROM page p"
        " JOIN document d ON d.id = p.document_id"
        " JOIN page_text pt ON pt.document_id = p.document_id AND pt.page_number = p.page_number"
        " WHERE p.kind = %s AND pt.source = 'pdf' AND p.char_count >= %s"
        " AND NOT EXISTS (SELECT 1 FROM page_flag f WHERE f.document_id = p.document_id"
        "   AND f.page_number = p.page_number AND f.code = ANY(%s))"
        " ORDER BY d.seq, p.page_number",
        (KIND_TEXT, min_chars, list(SKIP_FLAGS)),
    ).fetchall()
    if max_pages and len(rows) > max_pages:  # evenly spread over the set
        step = len(rows) / max_pages
        rows = [rows[int(i * step)] for i in range(max_pages)]
    return [(r[0], r[1], r[2]) for r in rows]


def measure(conn: Any, settings: Any, engine: Any, pdf: Any, doc_id: str, page: int
            ) -> PageResult:
    from docreader.quality import LOW_QUALITY, recognition_flags
    from docreader.recognition import _recognize_page
    from docreader.recognition_eval import _distance_and_length, _flat, _value_found, extract_values

    reference = conn.execute(
        "SELECT lines FROM page_text WHERE document_id = %s AND page_number = %s",
        (doc_id, page),
    ).fetchone()[0]
    expected = "\n".join(line["text"] for line in reference)
    started = time.monotonic()
    result = _recognize_page(pdf, page, engine, settings.recognition.dpi, settings.recognition)
    seconds = time.monotonic() - started
    distance, chars = _distance_and_length(expected, "")
    if result.error is not None:
        return PageResult(doc_id, page, chars, distance, 0.0, seconds=seconds,
                          error=result.error)
    got = "\n".join(line["text"] for line in result.lines)
    distance, chars = _distance_and_length(expected, got)
    got_flat = _flat(got)
    got_clauses = {v for kind, v in extract_values(got) if kind == "clause"}
    values: dict[str, list[int]] = {}
    for kind, value in extract_values(expected):
        pair = values.setdefault(kind, [0, 0])
        pair[1] += 1
        pair[0] += _value_found(kind, value, got_flat, got_clauses)
    flags = recognition_flags(result.lines, result.quality, result.ink_share,
                              result.orientation_unknown, settings.recognition)
    return PageResult(
        doc_id=doc_id,
        page=page,
        chars=chars,
        distance=distance,
        words=word_recall(expected, got),
        values={k: (p[0], p[1]) for k, p in values.items()},
        boxes=box_match([ln["bbox"] for ln in result.lines], [ln["bbox"] for ln in reference]),
        flagged=any(f.code == LOW_QUALITY for f in flags),
        seconds=seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Автозамер распознавания по текстовому слою.")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="не больше стольких страниц, равномерно по набору (0 — все)")
    parser.add_argument("--min-chars", type=int, default=MIN_CHARS,
                        help=f"страницы не короче стольких знаков ({MIN_CHARS})")
    args = parser.parse_args(argv)

    from docreader import db, ocr_engines
    from docreader.config import load_settings
    from docreader.errors import EnvironmentProblem
    from docreader.pdfpages import open_pdf

    try:
        settings = load_settings()
        conn = db.connect(settings)
        db.ensure_schema_current(conn)
        pages = _pages(conn, args.max_pages, args.min_chars)
        if not pages:
            print("Остановлено: страниц с текстовым слоем нет", file=sys.stderr)
            return 1
        engine = ocr_engines.load_engine(settings.recognition, settings.data_dir)
    except EnvironmentProblem as exc:
        print(f"\nОстановлено: {exc}", file=sys.stderr)
        return 1

    results: list[PageResult] = []
    open_docs: dict[str, Any] = {}
    try:
        for i, (doc_id, page, copy_path) in enumerate(pages, 1):
            if doc_id not in open_docs:
                for pdf in open_docs.values():
                    pdf.close()
                open_docs = {doc_id: open_pdf(settings.data_dir / copy_path)}
            results.append(measure(conn, settings, engine, open_docs[doc_id], doc_id, page))
            print(f"  {doc_id} стр. {page} ({i}/{len(pages)}) {results[-1].seconds:.1f} с",
                  file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        print("\nПрервано — сводка по уже проверенным страницам", file=sys.stderr)
    finally:
        for pdf in open_docs.values():
            pdf.close()

    text = "\n".join(
        summary_lines(results, settings.recognition.dpi, f"{engine.name} {engine.version}")
    ) + "\n"
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    target = settings.reports_dir / f"auto-eval-textlayer-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
