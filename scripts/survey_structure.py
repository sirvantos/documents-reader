"""How are real contracts laid out? Numbers only, for the analyst's Mac (feature 04).

Run from the repository root after reading (`docreader read`); no model runs:

    uv run --env-file .env python scripts/survey_structure.py

It reads the body lines of every document available after reading (stage `reading` in
`done` or `needs_review`, at least one page read) and counts how the text is laid out,
to answer the open questions of `specs/004-structure-parsing/spec.md` before clarify:

1. Numbering: «1. ЗАГОЛОВОК» with «1.1», «Раздел I» / «Статья 5», Roman numerals, headings
   in capitals without a number, flat «1.», «2.», nothing at all; deeper levels and lists.
2. Continuation: how often a «N.M» number is the next one, a repeat, a gap or a restart,
   and what a word section («Статья K») is followed by.
3. The end of a contract: requisites headings and «Приложение N» — where they stand
   against the last clause; the share of text before the first and after the last clause.
4. False starts and risks: lines starting with a date or a sum, table rows starting with
   a number, clause lengths, recognised and unread pages.

Only counts, shares, ranges and document ids are printed and saved (to
`$DOCREADER_DATA_DIR/reports/survey-structure-….txt`): no text, no file names, no
requisites. The summary may be sent to the agent.
"""

from __future__ import annotations

import argparse
import itertools
import re
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# --- line patterns (pure; tested in tests/unit/test_survey_structure.py) ----------------------

DATE = re.compile(r"^\d{1,2}\.\d{1,2}\.\d{2,4}(?!\d)")
SUM = re.compile(
    r"^\d[\d\s]*(?:[.,]\d+)?\s*(?:млн|млрд|тыс|руб|коп|р\.|%|USD|EUR)", re.IGNORECASE
)
MULTI = re.compile(r"^(\d{1,2}(?:\.\d{1,3})+)\.?(?=\s|$)")
SINGLE = re.compile(r"^(\d{1,2})\.(?=\s|$)")
PAREN_NUM = re.compile(r"^\d{1,2}\)")
LETTER = re.compile(r"^[а-яё]\)", re.IGNORECASE)
WORD_SECTION = re.compile(r"^(?:раздел|статья|глава)\s+(?:№\s*)?([IVXLC]+|\d{1,2})\b", re.I)
ROMAN = re.compile(r"^([IVXLC]+)\.(?=\s)")
APPENDIX = re.compile(r"^приложение(?:\s|$)", re.IGNORECASE)
REQUISITES = re.compile(
    r"реквизит|подписи\s+сторон|адреса\s+сторон|юридические\s+адреса", re.IGNORECASE
)
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
TABLE_NUMBER = re.compile(r"^\d{1,3}(?:[.)]|\s|$)")  # «1 Земляные работы», «2.», «3)»

HEADING_MAX_CHARS = 90
TOP_OF_PAGE_LINES = 3  # an «Приложение» line among the first body lines of its page

ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}

# A page recognised by feature 13 (`page_text.source = 'recognized'`) is passed to
# `survey_document` as this pseudo flag next to the real `page_flag` codes.
RECOGNIZED = "recognized"
UNREAD_FLAGS = frozenset({"scan_unread", "scan_no_text", "unreadable"})


def roman_to_int(text: str) -> int:
    """`IV` → 4; a letter outside I, V, X, L, C gives 0."""
    total = 0
    highest = 0
    for char in reversed(text.upper()):
        value = ROMAN_VALUES.get(char, 0)
        if value == 0:
            return 0
        total = total - value if value < highest else total + value
        highest = max(highest, value)
    return total


def is_caps(text: str) -> bool:
    """At least two Cyrillic letters, none of them lower-case."""
    letters = CYRILLIC.findall(text)
    return len(letters) >= 2 and not any(c.islower() for c in letters)


def is_requisites_heading(text: str) -> bool:
    """A short line naming the requisites or signatures, numbered or not."""
    line = text.strip()
    return len(line) <= HEADING_MAX_CHARS and REQUISITES.search(line) is not None


@dataclass(frozen=True)
class Start:
    """What a body line starts with. `number` — the parsed number, if any."""

    kind: str
    number: tuple[int, ...] = ()
    caps_rest: bool = False  # the text after the number is in capitals («1. ПРЕДМЕТ»)


def classify(text: str) -> Start | None:
    """The start of one line; None for ordinary text. Dates and sums win over numbers."""
    line = text.strip()
    if not line:
        return None
    if DATE.match(line):
        return Start("date")
    if SUM.match(line):
        return Start("sum")
    if (m := MULTI.match(line)) is not None:
        parts = tuple(int(p) for p in m.group(1).split("."))
        rest = line[m.end():].strip()
        return Start("multi" if rest else "bare_number", parts, is_caps(rest))
    if (m := SINGLE.match(line)) is not None:
        rest = line[m.end():].strip()
        return Start("single" if rest else "bare_number", (int(m.group(1)),), is_caps(rest))
    if PAREN_NUM.match(line):
        return Start("paren_num")
    if LETTER.match(line):
        return Start("letter")
    if (m := WORD_SECTION.match(line)) is not None:
        raw = m.group(1)
        return Start("word_section", (int(raw) if raw.isdigit() else roman_to_int(raw),))
    if (m := ROMAN.match(line)) is not None and roman_to_int(m.group(1)):
        return Start("roman", (roman_to_int(m.group(1)),))
    if len(line) <= HEADING_MAX_CHARS and APPENDIX.match(line):
        return Start("appendix")
    if len(line) <= HEADING_MAX_CHARS and is_caps(line) and len(line.split()) >= 2:
        return Start("caps_heading")
    return None


def step_kind(previous: tuple[int, ...] | None, current: tuple[int, ...]) -> str:
    """How a depth-2 number follows the last accepted one."""
    if previous is None:
        return "first"
    (pa, pb), (a, b) = previous[:2], current[:2]
    if (a, b) == (pa, pb):
        return "repeat"
    if a == pa and b == pb + 1:
        return "next"
    if a == pa + 1 and b == 1:
        return "new_section"
    if (a == pa and pb + 1 < b <= pb + 5) or (a == pa + 1 and 1 < b <= 5):
        return "gap"
    if (a, b) == (1, 1):
        return "restart"
    if (a, b) < (pa, pb):
        return "backwards"
    return "jump"


def level1_step(previous: int | None, current: int) -> str:
    """How a level-1 «N.» number follows the last accepted one."""
    if previous is None:
        return "first"
    if current == previous + 1:
        return "next"
    if current == previous:
        return "repeat"
    if previous + 1 < current <= previous + 5:
        return "gap"
    if current == 1:
        return "restart"
    return "other"


# --- one document ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Line:
    """One body line in reading order: page, position among the page's body lines, text."""

    page: int
    index_on_page: int
    text: str
    table: bool = False


@dataclass
class DocSurvey:
    """Counts for one document. Holds no text."""

    doc_id: str
    pages: int = 0
    starts: Counter[str] = field(default_factory=Counter)
    level1_caps: int = 0  # «1. ПРЕДМЕТ ДОГОВОРА»
    level1_plain: int = 0  # «1. Подрядчик обязуется…»
    depth: Counter[int] = field(default_factory=Counter)  # «5.2» → 2, «5.2.1» → 3
    table_number_lines: int = 0
    steps: Counter[str] = field(default_factory=Counter)  # depth-2 continuation
    level1_steps: Counter[str] = field(default_factory=Counter)
    word_section_inner: Counter[str] = field(default_factory=Counter)
    requisites_lines: int = 0
    requisites_numbered: bool = False  # the requisites heading carries a clause number
    requisites_after_last: bool = False
    requisites_inside: bool = False  # a requisites line before the last clause
    appendix_top: int = 0
    appendix_other: int = 0
    appendix_before_requisites: bool | None = None
    restart_after_appendix: bool = False
    lines_last_to_tail: int | None = None
    preamble_share: float | None = None
    tail_share: float | None = None
    clause_lengths: list[int] = field(default_factory=list)
    flagged_pages: Counter[str] = field(default_factory=Counter)

    @property
    def style(self) -> str:
        return style_of(self)


def survey_document(
    doc_id: str, lines: Sequence[Line], page_flags: Mapping[int, Iterable[str]], pages: int
) -> DocSurvey:
    """Count the layout of one document. The text is only classified, never kept."""
    s = DocSurvey(doc_id=doc_id, pages=pages)
    for codes in page_flags.values():
        for code in set(codes):
            s.flagged_pages["unread" if code in UNREAD_FLAGS else code] += 1

    offsets = [0]  # offsets[i] — start of line i; offsets[len(lines)] — total length
    for line in lines:
        offsets.append(offsets[-1] + len(line.text) + 1)
    total = offsets[-1]

    starts: list[int] = []  # line indexes of clause starts that continue the numbering
    requisites: list[int] = []
    first_appendix: int | None = None
    previous: tuple[int, ...] | None = None
    previous_level1: int | None = None
    pending_section: int | None = None

    for i, line in enumerate(lines):
        start = classify(line.text)
        if line.table:
            if TABLE_NUMBER.match(line.text.strip()):
                s.table_number_lines += 1
            continue
        if is_requisites_heading(line.text):
            s.requisites_lines += 1
            requisites.append(i)
            if start is not None and start.kind in ("single", "multi"):
                s.requisites_numbered = True
        if start is None:
            continue
        s.starts[start.kind] += 1
        if len(start.number) >= 2 and start.kind in ("multi", "bare_number"):
            s.depth[len(start.number)] += 1
        if start.kind == "word_section":
            pending_section = start.number[0]
        elif start.kind == "appendix":
            if line.index_on_page < TOP_OF_PAGE_LINES:
                s.appendix_top += 1
            else:
                s.appendix_other += 1
            if first_appendix is None:
                first_appendix = i
        elif start.kind == "single":
            if start.caps_rest:
                s.level1_caps += 1
            else:
                s.level1_plain += 1
            step = level1_step(previous_level1, start.number[0])
            s.level1_steps[step] += 1
            if step in ("first", "next"):
                previous_level1 = start.number[0]
                starts.append(i)
        elif start.kind in ("multi", "bare_number") and len(start.number) == 2:
            if pending_section is not None:
                a = start.number[0]
                key = "same_number" if a == pending_section else "from_one" if a == 1 else "other"
                s.word_section_inner[key] += 1
                pending_section = None
            step = step_kind(previous, start.number)
            s.steps[step] += 1
            if step in ("first", "next", "new_section"):
                previous = start.number
                starts.append(i)
            elif step == "restart" and first_appendix is not None:
                s.restart_after_appendix = True

    main = [i for i in starts if first_appendix is None or i < first_appendix]
    if main and total:
        first, last = main[0], main[-1]
        s.preamble_share = offsets[first] / total
        after = [r for r in requisites if r > last]
        s.requisites_after_last = bool(after)
        s.requisites_inside = any(r < last for r in requisites)
        # The last clause ends at the first requisites heading or appendix after it.
        marks = [*after[:1], *([first_appendix] if first_appendix is not None else [])]
        end = min(marks) if marks else len(lines)
        s.tail_share = (total - offsets[end]) / total
        if marks:
            s.lines_last_to_tail = end - last
        bounds = [*main, end]
        s.clause_lengths = [
            offsets[b] - offsets[a] for a, b in itertools.pairwise(bounds) if b > a
        ]
    if requisites and first_appendix is not None:
        s.appendix_before_requisites = first_appendix < requisites[0]
    return s


def style_of(s: DocSurvey) -> str:
    """One label for the numbering style of a document."""
    multi = s.steps["next"] + s.steps["new_section"] >= 3
    if multi and s.level1_caps >= 2:
        return "«N. ЗАГОЛОВОК» и «N.M»"
    if multi and s.starts["word_section"] >= 2:
        return "«Раздел/Статья/Глава K» и «N.M»"
    if multi and s.starts["roman"] >= 2:
        return "римские «I.» и «N.M»"
    if multi and s.starts["caps_heading"] >= 2:
        return "заголовки прописными без номера и «N.M»"
    if multi and s.level1_plain >= 2:
        return "«N. обычный текст» и «N.M»"
    if multi:
        return "только «N.M»"
    if s.starts["word_section"] >= 2:
        return "«Статья K» без «N.M»"
    if s.level1_caps + s.level1_plain >= 3:
        return "сквозная «N.» без «N.M»"
    return "нумерация не найдена"


# --- summary --------------------------------------------------------------------------------


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


_SHARES = ((0.0, 0.05, "< 5%"), (0.05, 0.2, "5–20%"), (0.2, 0.5, "20–50%"), (0.5, 2.0, "≥ 50%"))


def share_buckets(values: Iterable[float]) -> str:
    """`< 5%: 3, 5–20%: 1` — how many documents fall into each share range."""
    counts: Counter[str] = Counter()
    for v in values:
        for low, high, name in _SHARES:
            if low <= v < high:
                counts[name] += 1
                break
    parts = [f"{name}: {counts[name]}" for _, _, name in _SHARES if counts[name]]
    return ", ".join(parts) if parts else "—"


_COUNTS: tuple[tuple[int, int | None], ...] = ((1, 1), (2, 3), (4, 10), (11, 50), (51, None))


def count_buckets(values: Iterable[int]) -> str:
    """`1: 4, 2–3: 1, > 50: 2` — how many values fall into each range."""
    counts: Counter[tuple[int, int | None]] = Counter()
    for v in values:
        for low, high in _COUNTS:
            if v >= low and (high is None or v <= high):
                counts[(low, high)] += 1
                break
    parts = []
    for low, high in _COUNTS:
        if counts[(low, high)]:
            name = str(low) if high == low else f"{low}–{high}" if high else f"> {low - 1}"
            parts.append(f"{name}: {counts[(low, high)]}")
    return ", ".join(parts) if parts else "—"


def _ids(docs: Iterable[DocSurvey], limit: int = 12) -> str:
    ids = [d.doc_id for d in docs]
    if not ids:
        return "—"
    more = f" и ещё {len(ids) - limit}" if len(ids) > limit else ""
    return ", ".join(ids[:limit]) + more


def _docs_lines(docs: Sequence[DocSurvey], kind: str) -> str:
    return (
        f"{sum(1 for d in docs if d.starts[kind])} док., {sum(d.starts[kind] for d in docs)} строк"
    )


_STEP_NAMES = {
    "first": "первый номер",
    "next": "следующий (5.1→5.2)",
    "new_section": "новый раздел (5.3→6.1)",
    "repeat": "повтор (5.2→5.2)",
    "gap": "пропуск (5.1→5.3)",
    "restart": "заново с 1.1",
    "backwards": "назад",
    "jump": "скачок",
}

_KINDS = (
    ("single", "«N. …» (уровень 1)"),
    ("multi", "«N.M …» и глубже"),
    ("word_section", "«Раздел/Статья/Глава K»"),
    ("roman", "«I. …» римские"),
    ("caps_heading", "заголовок прописными без номера"),
    ("bare_number", "номер на отдельной строке"),
    ("paren_num", "перечень «1)»"),
    ("letter", "перечень «а)»"),
)


def summary_lines(docs: Sequence[DocSurvey]) -> list[str]:
    """The report. Counts, shares, ranges and document ids only."""
    n = len(docs)
    out = [f"Документов: {n}; страниц: {sum(d.pages for d in docs)}", ""]
    if not n:
        return [*out, "Нет документов, доступных после чтения."]

    out.append("1. Нумерация")
    out.append("   Стиль документа:")
    for style, count in Counter(d.style for d in docs).most_common():
        members = [d for d in docs if d.style == style]
        out.append(f"     {style}: {count} ({_pct(count, n)}) — {_ids(members)}")
    out.append("   Строки вида (вне таблиц):")
    for kind, name in _KINDS:
        out.append(f"     {name}: {_docs_lines(docs, kind)}")
    out.append(
        f"     «N. ЗАГОЛОВОК ПРОПИСНЫМИ»: {sum(1 for d in docs if d.level1_caps)} док.; "
        f"«N. обычный текст»: {sum(1 for d in docs if d.level1_plain)} док."
    )
    for depth, example in ((3, "5.2.1"), (4, "5.2.1.1")):
        out.append(
            f"     номера глубины {depth} («{example}»): "
            f"{sum(1 for d in docs if d.depth[depth])} док., "
            f"{sum(d.depth[depth] for d in docs)} строк"
        )

    out += ["", "2. Продолжение нумерации (вне таблиц)"]
    steps: Counter[str] = Counter()
    for d in docs:
        steps.update(d.steps)
    out.append("   «N.M» после последнего принятого номера:")
    for key, name in _STEP_NAMES.items():
        if steps[key]:
            with_key = sum(1 for d in docs if d.steps[key])
            out.append(
                f"     {name}: {steps[key]} ({_pct(steps[key], sum(steps.values()))}), "
                f"{with_key} док."
            )
    level1: Counter[str] = Counter()
    for d in docs:
        level1.update(d.level1_steps)
    level1_text = ", ".join(f"{k}: {v}" for k, v in sorted(level1.items())) or "—"
    out.append(f"   «N.» уровня 1: {level1_text}")
    inner: Counter[str] = Counter()
    for d in docs:
        inner.update(d.word_section_inner)
    if inner:
        out.append(
            "   первый «N.M» после «Раздел/Статья K»: "
            f"N = K: {inner['same_number']}, N = 1: {inner['from_one']}, иначе: {inner['other']}"
        )

    out += ["", "3. Конец договора"]
    with_req = [d for d in docs if d.requisites_lines]
    out.append(
        f"   строка о реквизитах/подписях: {len(with_req)} док.; с номером пункта: "
        f"{sum(1 for d in docs if d.requisites_numbered)}; после последнего пункта: "
        f"{sum(1 for d in docs if d.requisites_after_last)}; до последнего пункта: "
        f"{sum(1 for d in docs if d.requisites_inside)}"
    )
    with_app = [d for d in docs if d.appendix_top or d.appendix_other]
    out.append(
        f"   «Приложение…»: {len(with_app)} док.; вверху страницы: "
        f"{sum(1 for d in docs if d.appendix_top)} док., не вверху: "
        f"{sum(1 for d in docs if d.appendix_other)} док."
    )
    both = [d for d in docs if d.appendix_before_requisites is not None]
    out.append(
        f"   и приложение, и реквизиты: {len(both)} док.; приложение раньше реквизитов: "
        f"{sum(1 for d in both if d.appendix_before_requisites)}"
    )
    out.append(
        "   нумерация «1.1» заново после приложения: "
        f"{sum(1 for d in docs if d.restart_after_appendix)} док."
    )
    neither = [
        d for d in docs if not d.requisites_lines and not (d.appendix_top or d.appendix_other)
    ]
    out.append(f"   ни реквизитов, ни приложения: {len(neither)} док. — {_ids(neither)}")
    out.append(
        "   строк от начала последнего пункта до реквизитов/приложения: "
        + count_buckets(d.lines_last_to_tail for d in docs if d.lines_last_to_tail is not None)
    )
    out.append(
        "   доля текста до первого пункта (преамбула): "
        + share_buckets(d.preamble_share for d in docs if d.preamble_share is not None)
    )
    out.append(
        "   доля текста после последнего пункта (хвост): "
        + share_buckets(d.tail_share for d in docs if d.tail_share is not None)
    )

    out += ["", "4. Ложные начала и риски"]
    out.append(f"   строка начинается с даты: {_docs_lines(docs, 'date')}")
    out.append(f"   строка начинается с суммы: {_docs_lines(docs, 'sum')}")
    out.append(
        "   строка таблицы начинается с номера: "
        f"{sum(1 for d in docs if d.table_number_lines)} док., "
        f"{sum(d.table_number_lines for d in docs)} строк"
    )
    ratios = []
    for d in docs:
        if len(d.clause_lengths) >= 5 and statistics.median(d.clause_lengths) > 0:
            ratios.append(max(d.clause_lengths) / statistics.median(d.clause_lengths))
    if ratios:
        ranges = ", ".join(f"≥ {k}×: {sum(1 for r in ratios if r >= k)}" for k in (3, 5, 10, 20))
        out.append(
            f"   самый длинный пункт / медиана пунктов документа ({len(ratios)} док.): "
            f"медиана {statistics.median(ratios):.1f}; {ranges}"
        )
    for code, name in (
        (RECOGNIZED, "распознаны (фича 13)"),
        ("ocr_text", "текстовый слой от распознавания"),
        ("low_recognition_quality", "низкое качество распознавания"),
        ("unread", "не прочитаны (скан, нет текста, нечитаемо)"),
    ):
        out.append(
            f"   страницы «{name}»: {sum(d.flagged_pages[code] for d in docs)} стр., "
            f"{sum(1 for d in docs if d.flagged_pages[code])} док."
        )
    return out


# --- database -------------------------------------------------------------------------------


def load_documents(conn: Any) -> list[DocSurvey]:
    """Survey every document available after reading."""
    doc_ids = [
        row[0]
        for row in conn.execute(
            "SELECT dt.document_id FROM document_text dt"
            " JOIN stage_status ss ON ss.document_id = dt.document_id AND ss.stage = 'reading'"
            " WHERE ss.state IN ('done', 'needs_review') AND dt.read_pages > 0"
            " ORDER BY dt.document_id"
        ).fetchall()
    ]
    docs = []
    for doc_id in doc_ids:
        lines: list[Line] = []
        flags: dict[int, list[str]] = {}
        rows = conn.execute(
            "SELECT page_number, source, lines FROM page_text WHERE document_id = %s"
            " ORDER BY page_number",
            (doc_id,),
        ).fetchall()
        for page_number, source, page_lines in rows:
            if source == "recognized":
                flags.setdefault(page_number, []).append(RECOGNIZED)
            body = [ln for ln in page_lines if ln.get("role") == "body"]
            for k, ln in enumerate(body):
                lines.append(Line(page_number, k, ln.get("text", ""), ln.get("table") is not None))
        for page_number, code in conn.execute(
            "SELECT page_number, code FROM page_flag WHERE document_id = %s", (doc_id,)
        ).fetchall():
            flags.setdefault(page_number, []).append(code)
        docs.append(survey_document(doc_id, lines, flags, len(rows)))
    return docs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Обзор структуры договоров (фича 04): только цифры."
    )
    parser.parse_args(argv)

    from docreader import db
    from docreader.config import load_settings
    from docreader.errors import EnvironmentProblem, UserError

    try:
        settings = load_settings()
        conn = db.connect(settings)
        db.ensure_schema_current(conn)
        docs = load_documents(conn)
    except (EnvironmentProblem, UserError) as exc:
        print(f"\nОстановлено: {exc}", file=sys.stderr)
        return 1
    lines = [
        "Обзор структуры договоров, фича 04 — только цифры",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        "",
        *summary_lines(docs),
    ]
    text = "\n".join(lines) + "\n"
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"survey-structure-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
