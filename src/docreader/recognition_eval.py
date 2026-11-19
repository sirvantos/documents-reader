"""Quality measurement of recognition: `docreader recognize-eval` (research R-12, task T030).

The analyst keeps verified page texts and control strings in a folder inside the data
folder. This module compares them with what `recognize` and `read` saved, computes the
numbers (character accuracy, requisites, control strings, missing and repeated lines)
and writes them to `reports/recognition-eval-<stamp>.json` and `.csv`.

The pure calculations come first; the folder reading and the database part follow.
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import psycopg

from docreader.config import Settings
from docreader.errors import UserError
from docreader.textnorm import locate, normalize_chars

# --- pure calculations ---------------------------------------------------------------

LINE_MATCH_RATIO = 0.8

VALUE_KINDS = ("inn", "kpp", "ogrn", "amount", "date", "clause")
CONTROL_KINDS = ("number", "amount", "date", "inn", "kpp", "ogrn", "clause", "other")


def levenshtein(a: str, b: str) -> int:
    """Edit distance (insert, delete, substitute), two table rows in memory."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    previous[j] + 1,  # deletion
                    current[j - 1] + 1,  # insertion
                    previous[j - 1] + (ca != cb),  # substitution
                )
            )
        previous = current
    return previous[-1]


def _flat(text: str) -> str:
    """Common normalisation, then every whitespace run (line breaks too) → one space."""
    return " ".join(normalize_chars(text).split())


def _distance_and_length(expected: str, got: str) -> tuple[int, int]:
    flat_expected = _flat(expected)
    return levenshtein(flat_expected, _flat(got)), len(flat_expected)


def char_accuracy(expected: str, got: str) -> float:
    """1 − edit distance / length of the verified text, never below 0."""
    distance, length = _distance_and_length(expected, got)
    if length == 0:
        return 1.0 if distance == 0 else 0.0
    return max(0.0, 1 - distance / length)


_MONTHS = (
    "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
)
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("inn", re.compile(r"ИНН\s*:?\s*(?<!\d)(\d{12}|\d{10})(?!\d)")),
    ("kpp", re.compile(r"КПП\s*:?\s*(?<!\d)(\d{9})(?!\d)")),
    ("ogrn", re.compile(r"ОГРН(?:ИП)?\s*:?\s*(?<!\d)(\d{15}|\d{13})(?!\d)")),
    (
        "amount",
        re.compile(
            r"(?<![\d,.])(\d{1,3}(?: \d{3})+(?:,\d{2})?|\d+,\d{2})(?![\d,])"
        ),
    ),
    ("date", re.compile(r"(?<!\d)(\d{2}\.\d{2}\.\d{4})(?!\d)")),
    (
        "date",
        re.compile(rf"([\"«„]\s*\d{{1,2}}\s*[\"»“”]\s*(?:{_MONTHS})\s+\d{{4}})"),
    ),
)
_CLAUSE = re.compile(r"^(\d+(?:\.\d+)+)\.?(?=\s|$)")
_DATE_NUMBERS = re.compile(r"\d{2}\.\d{2}\.\d{4}")


def extract_values(text: str) -> list[tuple[str, str]]:
    """Requisites and numbers of the verified text as `(kind, value)`, in text order.

    Kinds: inn, kpp, ogrn, amount, date, clause. Bank accounts and БИК are not listed.
    """
    normalized = normalize_chars(text)
    found: list[tuple[int, str, str]] = []
    offset = 0
    for line in normalized.split("\n"):
        match = _CLAUSE.match(line)
        if match and not _DATE_NUMBERS.fullmatch(match.group(1)):
            found.append((offset, "clause", match.group(1)))
        offset += len(line) + 1
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(normalized):
            found.append((match.start(1), kind, " ".join(match.group(1).split())))
    found.sort(key=lambda item: item[0])
    return [(kind, value) for _, kind, value in found]


def _lines(text: str) -> list[str]:
    flat = (" ".join(raw.split()) for raw in normalize_chars(text).split("\n"))
    return [line for line in flat if line]


def _best_match(line: str, candidates: list[str]) -> tuple[str | None, float]:
    best, best_ratio = None, 0.0
    for candidate in candidates:
        if candidate == line:
            return candidate, 1.0
        matcher = difflib.SequenceMatcher(None, line, candidate, autojunk=False)
        if matcher.real_quick_ratio() <= best_ratio or matcher.quick_ratio() <= best_ratio:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best, best_ratio = candidate, ratio
    return best, best_ratio


def line_diffs(expected: str, got: str) -> list[tuple[str, str | None]]:
    """Verified lines that are not in the recognised text exactly.

    `(expected line, closest recognised line)`; the second item is `None` when no
    recognised line is close (ratio below 0.8): the line is missing.
    """
    got_lines = _lines(got)
    diffs: list[tuple[str, str | None]] = []
    for line in _lines(expected):
        match, ratio = _best_match(line, got_lines)
        if match == line:
            continue
        diffs.append((line, match if ratio >= LINE_MATCH_RATIO else None))
    return diffs


def missing_lines(expected: str, got: str) -> list[str]:
    """Verified lines with no close match (ratio ≥ 0.8) among the recognised lines."""
    return [line for line, match in line_diffs(expected, got) if match is None]


def repeated_lines(got: str) -> list[str]:
    """Recognised lines that occur on the page more than once (each listed once)."""
    counts = Counter(_lines(got))
    return [line for line, count in counts.items() if count > 1]


def _value_found(kind: str, value: str, got_flat: str, got_clauses: set[str]) -> bool:
    if kind == "clause":
        return value in got_clauses
    return value in got_flat


# --- result types ----------------------------------------------------------------------


@dataclass(frozen=True)
class PageEval:
    id: str
    page: int
    recognition_run_id: int
    reading_run_id: int | None
    chars: int
    distance: int
    char_accuracy: float
    values: dict[str, tuple[int, int]]
    missing_lines: int
    repeated_lines: int
    diffs: list[tuple[str, str | None]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "page": self.page,
            "recognition_run_id": self.recognition_run_id,
            "reading_run_id": self.reading_run_id,
            "chars": self.chars,
            "char_accuracy": self.char_accuracy,
            "values": {kind: list(pair) for kind, pair in self.values.items()},
            "missing_lines": self.missing_lines,
            "repeated_lines": self.repeated_lines,
        }


@dataclass(frozen=True)
class MissingControl:
    id: str
    string: str
    kind: str


@dataclass(frozen=True)
class EvalResult:
    label: str | None
    engine: str | None
    engine_version: str | None
    dpi: int | None
    settings: dict
    pages: list[PageEval]
    not_recognized: list[tuple[str, int]]
    control_kinds: dict[str, tuple[int, int]]
    control_missing: list[MissingControl]
    flags: dict | None = None
    report_path: Path | None = None
    table_path: Path | None = None

    @property
    def documents(self) -> int:
        return len({p.id for p in self.pages})

    @property
    def chars(self) -> int:
        return sum(p.chars for p in self.pages)

    @property
    def total_accuracy(self) -> float | None:
        if not self.pages:
            return None
        chars = self.chars
        if chars == 0:
            return 1.0 if all(p.distance == 0 for p in self.pages) else 0.0
        return max(0.0, 1 - sum(p.distance for p in self.pages) / chars)

    @property
    def page_accuracies(self) -> list[float]:
        return [p.char_accuracy for p in self.pages]

    @property
    def value_totals(self) -> dict[str, tuple[int, int]]:
        sums: dict[str, tuple[int, int]] = {}
        for page in self.pages:
            for kind, (found, total) in page.values.items():
                old_found, old_total = sums.get(kind, (0, 0))
                sums[kind] = (old_found + found, old_total + total)
        return sums

    @property
    def control_found(self) -> int:
        return sum(found for found, _ in self.control_kinds.values())

    @property
    def control_total(self) -> int:
        return sum(total for _, total in self.control_kinds.values())

    def to_json(self, *, with_missing: bool = False, with_diffs: bool = False) -> dict:
        values = self.value_totals
        values_found = sum(found for found, _ in values.values())
        values_total = sum(total for _, total in values.values())
        control_total = self.control_total
        control: dict = {
            "kinds": {kind: list(pair) for kind, pair in self.control_kinds.items()},
            "found": self.control_found,
            "total": control_total,
            "share": self.control_found / control_total if control_total else None,
        }
        if with_missing:
            control["missing"] = [
                {"id": m.id, "string": m.string, "kind": m.kind} for m in self.control_missing
            ]
        data: dict = {
            "label": self.label,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "dpi": self.dpi,
            "settings": self.settings,
            "pages": [p.to_json() for p in self.pages],
            "totals": {
                "pages": len(self.pages),
                "documents": self.documents,
                "chars": self.chars,
                "char_accuracy": self.total_accuracy,
                "values": {kind: list(pair) for kind, pair in values.items()},
                "values_share": values_found / values_total if values_total else None,
                "missing_lines": sum(p.missing_lines for p in self.pages),
                "repeated_lines": sum(p.repeated_lines for p in self.pages),
            },
            "control": control,
            "not_recognized": [{"id": i, "page": n} for i, n in self.not_recognized],
            "flags": self.flags,
        }
        if with_diffs:
            data["diffs"] = [
                {"id": p.id, "page": p.page, "expected": expected, "recognised": got}
                for p in self.pages
                for expected, got in p.diffs
            ]
        return data


# --- folder reading --------------------------------------------------------------------

_PAGE_FILE = re.compile(r"(D-\d{4,})-p(\d{3,})\.txt")


def _read_text(path: Path, shown: str) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise UserError(f"{shown}: файл не прочитан ({exc})") from exc


def _read_verified_pages(
    conn: psycopg.Connection, folder: Path
) -> dict[tuple[str, int], str]:
    pages_dir = folder / "pages"
    if not pages_dir.is_dir():
        raise UserError(f"В папке замера нет подпапки pages: {pages_dir}")
    verified: dict[tuple[str, int], str] = {}
    for path in sorted(pages_dir.glob("*.txt")):
        shown = f"pages/{path.name}"
        match = _PAGE_FILE.fullmatch(path.name)
        if match is None:
            raise UserError(f"{shown}: имя файла должно быть вида D-0003-p005.txt")
        doc_id, page = match.group(1), int(match.group(2))
        known = conn.execute(
            "SELECT 1 FROM page WHERE document_id = %s AND page_number = %s", (doc_id, page)
        ).fetchone()
        if known is None:
            raise UserError(f"{shown}: в реестре нет страницы {page} документа {doc_id}")
        verified[(doc_id, page)] = _read_text(path, shown)
    return verified


def _read_control(conn: psycopg.Connection, folder: Path) -> list[tuple[str, str, str]]:
    path = folder / "control.csv"
    if not path.is_file():
        return []
    reader = csv.reader(io.StringIO(_read_text(path, "control.csv")), delimiter=";")
    rows: list[tuple[str, str, str]] = []
    header_seen = False
    for row in reader:
        number = reader.line_num
        if not header_seen:
            header_seen = True
            continue
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != 3:
            raise UserError(
                f"control.csv, строка {number}: нужно три поля «документ;строка;вид», "
                f"найдено {len(row)}"
            )
        doc_id, string, kind = (cell.strip() for cell in row)
        if not string:
            raise UserError(f"control.csv, строка {number}: пустая контрольная строка")
        if kind not in CONTROL_KINDS:
            raise UserError(
                f"control.csv, строка {number}: неизвестный вид «{kind}» "
                f"(допустимо: {', '.join(CONTROL_KINDS)})"
            )
        if conn.execute("SELECT 1 FROM document WHERE id = %s", (doc_id,)).fetchone() is None:
            raise UserError(f"control.csv, строка {number}: в реестре нет документа {doc_id}")
        rows.append((doc_id, string, kind))
    return rows


# --- evaluation ------------------------------------------------------------------------


@dataclass(frozen=True)
class _Recognised:
    text: str
    engine: str
    engine_version: str
    dpi: int
    run_id: int


def _load_recognised(conn: psycopg.Connection, doc_id: str, page: int) -> _Recognised | None:
    row = conn.execute(
        "SELECT lines, engine, engine_version, dpi, run_id FROM page_recognition "
        "WHERE document_id = %s AND page_number = %s AND error IS NULL",
        (doc_id, page),
    ).fetchone()
    if row is None:
        return None
    lines, engine, version, dpi, run_id = row
    return _Recognised("\n".join(line["text"] for line in lines), engine, version, dpi, run_id)


def _evaluate_page(
    conn: psycopg.Connection, doc_id: str, page: int, expected: str, rec: _Recognised
) -> PageEval:
    distance, chars = _distance_and_length(expected, rec.text)
    accuracy = char_accuracy(expected, rec.text)
    got_flat = _flat(rec.text)
    got_clauses = {v for kind, v in extract_values(rec.text) if kind == "clause"}
    counts: dict[str, list[int]] = {}
    for kind, value in extract_values(expected):
        pair = counts.setdefault(kind, [0, 0])
        pair[1] += 1
        if _value_found(kind, value, got_flat, got_clauses):
            pair[0] += 1
    diffs = line_diffs(expected, rec.text)
    reading = conn.execute(
        "SELECT run_id FROM page_text WHERE document_id = %s AND page_number = %s",
        (doc_id, page),
    ).fetchone()
    return PageEval(
        id=doc_id,
        page=page,
        recognition_run_id=rec.run_id,
        reading_run_id=reading[0] if reading else None,
        chars=chars,
        distance=distance,
        char_accuracy=accuracy,
        values={kind: (pair[0], pair[1]) for kind, pair in counts.items()},
        missing_lines=sum(1 for _, match in diffs if match is None),
        repeated_lines=len(repeated_lines(rec.text)),
        diffs=diffs,
    )


def _evaluate_control(
    conn: psycopg.Connection, rows: list[tuple[str, str, str]]
) -> tuple[dict[str, tuple[int, int]], list[MissingControl]]:
    texts: dict[str, str] = {}
    kinds: dict[str, list[int]] = {}
    missing: list[MissingControl] = []
    for doc_id, string, kind in rows:
        if doc_id not in texts:
            row = conn.execute(
                "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
            ).fetchone()
            texts[doc_id] = row[0] if row else ""
        pair = kinds.setdefault(kind, [0, 0])
        pair[1] += 1
        if locate(texts[doc_id], string):
            pair[0] += 1
        else:
            missing.append(MissingControl(doc_id, string, kind))
    return {kind: (pair[0], pair[1]) for kind, pair in kinds.items()}, missing


def _inside(folder: Path, data_dir: Path) -> bool:
    return folder.resolve().is_relative_to(data_dir.resolve())


def run_eval(
    conn: psycopg.Connection,
    settings: Settings,
    folder: str | os.PathLike[str],
    *,
    label: str | None = None,
    diff: bool = False,
    now: datetime | None = None,
) -> EvalResult:
    """Measure the saved recognition against the verified texts in `folder`.

    `diff` only decides what the caller prints; the saved JSON always keeps the diffs.
    """
    root = Path(folder)
    if not _inside(root, settings.data_dir):
        raise UserError(
            "Папка замера должна лежать в папке данных "
            "(проверенные тексты — реальные данные)"
        )
    if not root.is_dir():
        raise UserError(f"Папка замера не найдена: {root}")

    verified = _read_verified_pages(conn, root)
    control_rows = _read_control(conn, root)

    pages: list[PageEval] = []
    not_recognized: list[tuple[str, int]] = []
    used: Counter[tuple[str, str, int]] = Counter()
    for (doc_id, page), expected in sorted(verified.items()):
        rec = _load_recognised(conn, doc_id, page)
        if rec is None:
            not_recognized.append((doc_id, page))
            continue
        used[(rec.engine, rec.engine_version, rec.dpi)] += 1
        pages.append(_evaluate_page(conn, doc_id, page, expected, rec))

    engine = version = dpi = None
    if used:
        engine, version, dpi = used.most_common(1)[0][0]
    kinds, missing = _evaluate_control(conn, control_rows)

    result = EvalResult(
        label=label,
        engine=engine,
        engine_version=version,
        dpi=dpi,
        settings=settings.settings_for_run(),
        pages=pages,
        not_recognized=not_recognized,
        control_kinds=kinds,
        control_missing=missing,
        flags=None,  # flags.csv is read once the flag rule is measured (T044)
    )
    return _save(settings, result, now or datetime.now())


def _table_text(result: EvalResult) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        [
            "Документ", "Стр.", "Прогон распознавания", "Прогон чтения", "Знаков",
            "Верных знаков", "Значений найдено", "Значений всего", "Пропущено строк",
            "Повторено строк",
        ]
    )
    for p in result.pages:
        writer.writerow(
            [
                p.id,
                p.page,
                p.recognition_run_id,
                "" if p.reading_run_id is None else p.reading_run_id,
                p.chars,
                f"{p.char_accuracy:.4f}".replace(".", ","),
                sum(found for found, _ in p.values.values()),
                sum(total for _, total in p.values.values()),
                p.missing_lines,
                p.repeated_lines,
            ]
        )
    return buffer.getvalue()


def _atomic_write(target: Path, text: str, encoding: str) -> None:
    tmp = target.with_name(target.name + ".tmp")
    with open(tmp, "w", encoding=encoding, newline="") as fh:
        fh.write(text)
    os.replace(tmp, target)


def _save(settings: Settings, result: EvalResult, now: datetime) -> EvalResult:
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    stem = settings.reports_dir / f"recognition-eval-{now.strftime('%Y%m%d-%H%M%S')}"
    json_path = stem.with_suffix(".json")
    csv_path = stem.with_suffix(".csv")
    document = json.dumps(
        result.to_json(with_missing=True, with_diffs=True), ensure_ascii=False, indent=2
    )
    _atomic_write(json_path, document + "\n", "utf-8")
    _atomic_write(csv_path, _table_text(result), "utf-8-sig")
    return EvalResult(
        label=result.label,
        engine=result.engine,
        engine_version=result.engine_version,
        dpi=result.dpi,
        settings=result.settings,
        pages=result.pages,
        not_recognized=result.not_recognized,
        control_kinds=result.control_kinds,
        control_missing=result.control_missing,
        flags=result.flags,
        report_path=json_path,
        table_path=csv_path,
    )

