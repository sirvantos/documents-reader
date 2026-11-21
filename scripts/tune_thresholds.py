"""Quickstart Б6 (task T053), step 4: pick the [recognition] flag thresholds by SC-007.

Run on the analyst's Mac after `flags.csv` in the evaluation folder is filled:

    uv run --env-file .env python scripts/tune_thresholds.py

The flag «низкое качество распознавания» is recomputed with the same function `read`
uses (`docreader.quality.recognition_flags`) from the stored recognition results, for
every combination of `page_min_quality`, `line_min_confidence` and `max_low_line_share`
on a grid. Nothing is recognised or read again, nothing in the database changes.

Printed and saved (to `$DOCREADER_DATA_DIR/reports/tune-thresholds-….txt`): only counts,
shares and threshold values — no text. The result may be sent to the agent.
Ranking: share of correct flags, then fewer missed bad pages, then closeness to the
current values. With 40 marked pages a difference of one page is 2.5 points.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

MARKS = {"да": True, "нет": False}
GRID = {
    "page_min_quality": [round(0.50 + 0.05 * i, 2) for i in range(10)],  # 0.50 … 0.95
    "line_min_confidence": [round(0.30 + 0.05 * i, 2) for i in range(13)],  # 0.30 … 0.90
    "max_low_line_share": [round(0.05 * i, 2) for i in range(1, 11)],  # 0.05 … 0.50
}
TARGET = 0.80  # SC-007


# --- pure part (tested in tests/unit/test_tune_thresholds.py) ------------------------------


def parse_flags(text: str) -> tuple[list[tuple[str, int, bool]], list[str]]:
    """Rows of `flags.csv` and the problems found (line number and what is wrong)."""
    rows: list[tuple[str, int, bool]] = []
    problems: list[str] = []
    reader = csv.reader(io.StringIO(text), delimiter=";")
    for number, row in enumerate(reader, 1):
        if number == 1 or not any(cell.strip() for cell in row):
            continue
        if len(row) != 3:
            problems.append(f"строка {number}: нужно три поля «документ;страница;плохая»")
            continue
        doc_id, page, mark = (cell.strip() for cell in row)
        if mark not in MARKS:
            problems.append(f"строка {number}: «плохая» — «{mark}», нужно да или нет")
            continue
        if not page.isdigit():
            problems.append(f"строка {number}: номер страницы «{page}» неверен")
            continue
        rows.append((doc_id, int(page), MARKS[mark]))
    return rows, problems


@dataclass(frozen=True)
class Stored:
    lines: Sequence[Mapping]
    quality: float | None
    ink_share: float | None
    orientation_unknown: bool


@dataclass(frozen=True)
class Score:
    values: tuple[float, float, float]  # page_min_quality, line_min_confidence, share
    correct: int
    false_positive: int
    false_negative: int

    @property
    def checked(self) -> int:
        return self.correct + self.false_positive + self.false_negative

    @property
    def accuracy(self) -> float:
        return self.correct / self.checked if self.checked else 0.0


def flagged(page: Stored, settings: Any) -> bool:
    from docreader.quality import LOW_QUALITY, recognition_flags

    flags = recognition_flags(
        page.lines, page.quality, page.ink_share, page.orientation_unknown, settings
    )
    return any(flag.code == LOW_QUALITY for flag in flags)


def _with(base: Any, values: tuple[float, float, float]) -> Any:
    return replace(
        base, page_min_quality=values[0], line_min_confidence=values[1],
        max_low_line_share=values[2],
    )


def score(marked: Iterable[tuple[Stored, bool]], base: Any,
          values: tuple[float, float, float]) -> Score:
    settings = _with(base, values)
    correct = fp = fn = 0
    for page, bad in marked:
        got = flagged(page, settings)
        if got == bad:
            correct += 1
        elif got:
            fp += 1
        else:
            fn += 1
    return Score(values, correct, fp, fn)


def rank(scores: Iterable[Score], current: tuple[float, float, float]) -> list[Score]:
    def distance(s: Score) -> float:
        return sum(abs(a - b) for a, b in zip(s.values, current, strict=True))

    return sorted(scores, key=lambda s: (-s.accuracy, s.false_negative, distance(s)))


def _fmt(s: Score) -> str:
    q, c, share = s.values
    return (
        f"page_min_quality {q:.2f}, line_min_confidence {c:.2f}, max_low_line_share "
        f"{share:.2f}: верен {100 * s.accuracy:.1f}% ({s.correct} из {s.checked}), "
        f"ложных {s.false_positive}, пропущено {s.false_negative}"
    )


def report_lines(
    marked: Sequence[tuple[Stored, bool]],
    base: Any,
    everything: Sequence[Stored],
    top: int = 10,
) -> list[str]:
    current = (base.page_min_quality, base.line_min_confidence, base.max_low_line_share)
    grid = [
        (q, c, share)
        for q in GRID["page_min_quality"]
        for c in GRID["line_min_confidence"]
        for share in GRID["max_low_line_share"]
    ]
    ranked = rank((score(marked, base, v) for v in grid), current)
    now = score(marked, base, current)
    only_quality = rank(
        (score(marked, base, (q, current[1], current[2])) for q in GRID["page_min_quality"]),
        current,
    )
    best = ranked[0]

    def share_flagged(values: tuple[float, float, float]) -> str:
        settings = _with(base, values)
        n = sum(flagged(p, settings) for p in everything)
        return f"{n} из {len(everything)} ({100 * n / len(everything):.1f}%)" if everything else "—"

    bad = sum(1 for _, b in marked if b)
    lines = [
        "Подбор порогов флага «низкое качество» (SC-007) — только цифры",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        f"Размечено страниц: {len(marked)} (плохих {bad}, хороших {len(marked) - bad}); "
        f"цель — верен не меньше {100 * TARGET:.0f}%",
        "",
        "Сейчас: " + _fmt(now),
        f"  доля страниц-сканов с флагом в наборе: {share_flagged(current)}",
        "",
        "Лучшее сочетание: " + _fmt(best),
        f"  доля страниц-сканов с флагом в наборе: {share_flagged(best.values)}",
        "",
        "Только page_min_quality (остальное как сейчас), лучшее: " + _fmt(only_quality[0]),
        "",
        f"Первые {top} сочетаний:",
        *(f"  {_fmt(s)}" for s in ranked[:top]),
        "",
        "Для settings.toml (лучшее сочетание):",
        "  [recognition]",
        f"  page_min_quality = {best.values[0]:.2f}",
        f"  line_min_confidence = {best.values[1]:.2f}",
        f"  max_low_line_share = {best.values[2]:.2f}",
    ]
    if best.accuracy < TARGET:
        lines.append(
            f"Внимание: даже лучшее сочетание ниже {100 * TARGET:.0f}% — SC-007 не выполнен"
        )
    return lines


# --- the run --------------------------------------------------------------------------------


def _stored(conn: Any, doc_id: str, page: int) -> Stored | None:
    row = conn.execute(
        "SELECT lines, quality, ink_share, orientation_unknown FROM page_recognition"
        " WHERE document_id = %s AND page_number = %s AND error IS NULL",
        (doc_id, page),
    ).fetchone()
    return Stored(*row) if row else None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подбор порогов флага по flags.csv (SC-007).")
    parser.add_argument("--folder", help="папка замера (по умолчанию <папка данных>/ocr-eval)")
    args = parser.parse_args(argv)

    from docreader import db
    from docreader.config import load_settings

    settings = load_settings()
    folder = Path(args.folder) if args.folder else settings.data_dir / "ocr-eval"
    path = folder / "flags.csv"
    if not path.is_file():
        print(f"Остановлено: нет файла {path} — сначала scripts/prepare_b6.py", file=sys.stderr)
        return 1
    rows, problems = parse_flags(path.read_text(encoding="utf-8-sig"))
    if problems:
        print("Остановлено: flags.csv заполнен не до конца:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    if not rows:
        print("Остановлено: в flags.csv нет размеченных страниц", file=sys.stderr)
        return 1
    conn = db.connect(settings)
    db.ensure_schema_current(conn)
    marked, missing = [], []
    for doc_id, page, bad in rows:
        stored = _stored(conn, doc_id, page)
        if stored is None:
            missing.append(f"{doc_id} стр. {page}")
        else:
            marked.append((stored, bad))
    if missing:
        print("Остановлено: нет результата распознавания для " + ", ".join(missing),
              file=sys.stderr)
        return 1
    everything = [
        Stored(*row)
        for row in conn.execute(
            "SELECT pr.lines, pr.quality, pr.ink_share, pr.orientation_unknown"
            " FROM page_recognition pr JOIN page p ON p.document_id = pr.document_id"
            " AND p.page_number = pr.page_number WHERE pr.error IS NULL AND p.kind = 'scan'"
        )
    ]
    text = "\n".join(report_lines(marked, settings.recognition, everything)) + "\n"
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    target = settings.reports_dir / f"tune-thresholds-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print(text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
