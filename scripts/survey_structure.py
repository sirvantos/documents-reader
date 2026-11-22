"""How are real contracts laid out? Numbers only, for the analyst's Mac (feature 04).

Run from the repository root after reading (`docreader read`); no model runs:

    uv run --env-file .env python scripts/survey_structure.py

It reads the body lines of every document available after reading (stage `reading` in
`done` or `needs_review`, at least one page read) and counts how the text is laid out,
to answer the open questions of `specs/004-structure-parsing/spec.md` before clarify.

Each document is split first: the preamble (before the first numbered line), the main
text, and the tail. The main text ends at the requisites heading (a level-1 «N.» line or
a line in capitals naming requisites or signatures) or, without one, at an «Приложение»
line among the first lines of a page. Everything is then counted for the main text only,
so numbering inside appendices (estimates, schedules) does not mix in:

1. The boundary: how it was found, the share of text in each part, the size of the
   requisites section, «Приложение» lines at the top of a page before the boundary.
2. Numbering: level-1 «N.» lines that are headings (followed by «N.1») or sentences,
   «N.M» and deeper, word sections, Roman numerals, headings in capitals, lists.
3. Continuation of «N.M» and «N.»: next, new section, repeat, gap, restart, jumps;
   numbers damaged by recognition («5,2», «5.2Оплата»).
4. Risks in the main text: lines starting with a date or a sum, numbers on their own
   line, table rows, clause lengths, recognised and low-quality pages.

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
# Numbers that recognition may have damaged: «5,2 Оплата», «5.2Оплата».
COMMA_NUMBER = re.compile(r"^\d{1,2},\d{1,2}\.?\s")
GLUED_NUMBER = re.compile(r"^\d{1,2}\.\d{1,2}\.?[А-Яа-яЁё]")

HEADING_MAX_CHARS = 90
TITLE_MAX_CHARS = 60  # a level-1 «N. Предмет договора» heading is at most this long
TOP_OF_PAGE_LINES = 3  # an «Приложение» line among the first body lines of its page
NEXT_NUMBER_WINDOW = 3  # a heading is followed by «N.1» within this many lines

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
    """A short line naming the requisites or signatures."""
    line = text.strip()
    return len(line) <= HEADING_MAX_CHARS and REQUISITES.search(line) is not None


@dataclass(frozen=True)
class Start:
    """What a body line starts with. `number` — the parsed number, if any."""

    kind: str
    number: tuple[int, ...] = ()
    caps_rest: bool = False  # the text after the number is in capitals («1. ПРЕДМЕТ»)
    rest_chars: int = 0  # length of the text after the number


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
        return Start("multi" if rest else "bare_number", parts, is_caps(rest), len(rest))
    if (m := SINGLE.match(line)) is not None:
        rest = line[m.end():].strip()
        kind = "single" if rest else "bare_number"
        return Start(kind, (int(m.group(1)),), is_caps(rest), len(rest))
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


@dataclass(frozen=True)
class Boundary:
    """Where the preamble ends and where the main text ends (line indexes)."""

    first: int | None  # first numbered line; None — no numbering at all
    end: int  # first line of the tail; len(lines) — no tail
    how: str  # "requisites_numbered", "requisites_caps", "appendix", "none"
    appendix_after: int | None  # first top-of-page «Приложение» after the end, if any
    appendix_before: int  # top-of-page «Приложение» lines between `first` and `end`


def find_boundary(lines: Sequence[Line]) -> Boundary:
    """The end of the main text: the requisites heading, else an appendix at a page top."""
    starts = [classify(line.text) if not line.table else None for line in lines]
    first = next(
        (i for i, s in enumerate(starts) if s is not None and s.kind in ("single", "multi")), None
    )
    if first is None:
        return Boundary(None, len(lines), "none", None, 0)

    def top_appendix(i: int) -> bool:
        s = starts[i]
        return s is not None and s.kind == "appendix" and lines[i].index_on_page < TOP_OF_PAGE_LINES

    end, how = len(lines), "none"
    for i in range(first + 1, len(lines)):
        s = starts[i]
        if lines[i].table or not is_requisites_heading(lines[i].text):
            continue
        if s is not None and s.kind == "single":
            end, how = i, "requisites_numbered"
            break
        if is_caps(lines[i].text) and (s is None or s.kind == "caps_heading"):
            end, how = i, "requisites_caps"
            break
    if how == "none":
        end = next((i for i in range(first + 1, len(lines)) if top_appendix(i)), len(lines))
        how = "appendix" if end < len(lines) else "none"
    after = next((i for i in range(end + 1, len(lines)) if top_appendix(i)), None)
    if how == "appendix":
        after = end
    before = sum(1 for i in range(first, end) if top_appendix(i))
    return Boundary(first, end, how, after, before)


@dataclass
class DocSurvey:
    """Counts for one document; everything but the boundary is for the main text. No text."""

    doc_id: str
    pages: int = 0
    how: str = "none"
    appendix_top_before_end: int = 0
    requisites_section_lines: int | None = None
    preamble_share: float = 0.0
    main_share: float = 0.0
    requisites_share: float = 0.0
    appendix_share: float = 0.0
    starts: Counter[str] = field(default_factory=Counter)
    level1_heading: int = 0  # «N. …» followed by «N.1» within a few lines
    level1_sentence: int = 0  # «N. …» not followed by «N.1»
    level1_short: int = 0  # at most TITLE_MAX_CHARS after the number
    level1_caps: int = 0
    depth: Counter[int] = field(default_factory=Counter)  # «5.2» → 2, «5.2.1» → 3
    steps: Counter[str] = field(default_factory=Counter)  # depth-2 continuation
    level1_steps: Counter[str] = field(default_factory=Counter)
    damaged_numbers: Counter[str] = field(default_factory=Counter)  # "comma", "glued"
    table_lines: int = 0
    table_number_lines: int = 0
    clause_lengths: list[int] = field(default_factory=list)
    main_pages: int = 0
    main_flagged_pages: Counter[str] = field(default_factory=Counter)

    @property
    def style(self) -> str:
        return style_of(self)


def _share(offsets: Sequence[int], start: int, end: int) -> float:
    total = offsets[-1]
    return (offsets[end] - offsets[start]) / total if total and end > start else 0.0


def survey_document(
    doc_id: str, lines: Sequence[Line], page_flags: Mapping[int, Iterable[str]], pages: int
) -> DocSurvey:
    """Count the layout of one document. The text is only classified, never kept."""
    s = DocSurvey(doc_id=doc_id, pages=pages)
    offsets = [0]  # offsets[i] — start of line i; offsets[len(lines)] — total length
    for line in lines:
        offsets.append(offsets[-1] + len(line.text) + 1)

    b = find_boundary(lines)
    s.how = b.how
    s.appendix_top_before_end = b.appendix_before
    if b.first is None:
        s.preamble_share = 1.0 if offsets[-1] else 0.0
        return s
    s.preamble_share = _share(offsets, 0, b.first)
    s.main_share = _share(offsets, b.first, b.end)
    if b.how.startswith("requisites"):
        stop = b.appendix_after if b.appendix_after is not None else len(lines)
        s.requisites_share = _share(offsets, b.end, stop)
        s.requisites_section_lines = stop - b.end
        s.appendix_share = _share(offsets, stop, len(lines))
    else:
        s.appendix_share = _share(offsets, b.end, len(lines))

    main = range(b.first, b.end)
    main_pages = {lines[i].page for i in main}
    s.main_pages = len(main_pages)
    for page in main_pages:
        for code in set(page_flags.get(page, ())):
            s.main_flagged_pages["unread" if code in UNREAD_FLAGS else code] += 1

    starts = {i: classify(lines[i].text) for i in main if not lines[i].table}
    clause_starts: list[int] = []
    previous: tuple[int, ...] | None = None
    previous_level1: int | None = None
    for i in main:
        line = lines[i]
        if line.table:
            s.table_lines += 1
            if TABLE_NUMBER.match(line.text.strip()):
                s.table_number_lines += 1
            continue
        text = line.text.strip()
        if COMMA_NUMBER.match(text):
            s.damaged_numbers["comma"] += 1
        elif GLUED_NUMBER.match(text):
            s.damaged_numbers["glued"] += 1
        start = starts[i]
        if start is None:
            continue
        s.starts[start.kind] += 1
        if len(start.number) >= 2 and start.kind in ("multi", "bare_number"):
            s.depth[len(start.number)] += 1
        if start.kind == "single":
            n = start.number[0]
            followed = any(
                (nxt := starts.get(j)) is not None
                and nxt.kind in ("multi", "bare_number")
                and nxt.number[:2] == (n, 1)
                for j in range(i + 1, min(i + 1 + NEXT_NUMBER_WINDOW, b.end))
            )
            if followed:
                s.level1_heading += 1
            else:
                s.level1_sentence += 1
            if start.rest_chars <= TITLE_MAX_CHARS:
                s.level1_short += 1
            if start.caps_rest:
                s.level1_caps += 1
            step = level1_step(previous_level1, n)
            s.level1_steps[step] += 1
            if step in ("first", "next"):
                previous_level1 = n
                clause_starts.append(i)
        elif start.kind in ("multi", "bare_number") and len(start.number) == 2:
            step = step_kind(previous, start.number)
            s.steps[step] += 1
            if step in ("first", "next", "new_section"):
                previous = start.number
                clause_starts.append(i)

    bounds = [*sorted(clause_starts), b.end]
    s.clause_lengths = [
        offsets[y] - offsets[x] for x, y in itertools.pairwise(bounds) if y > x
    ]
    return s


def style_of(s: DocSurvey) -> str:
    """One label for the numbering style of the main text."""
    multi = s.steps["next"] + s.steps["new_section"] >= 3
    if multi and s.level1_heading >= 2:
        return "«N. Заголовок» и «N.M»"
    if multi and s.starts["word_section"] >= 2:
        return "«Раздел/Статья/Глава K» и «N.M»"
    if multi and s.starts["roman"] >= 2:
        return "римские «I.» и «N.M»"
    if multi and s.starts["caps_heading"] >= 2:
        return "заголовки прописными без номера и «N.M»"
    if multi:
        return "только «N.M»"
    if s.starts["word_section"] >= 2:
        return "«Статья K» без «N.M»"
    if s.level1_sentence >= 3:
        return "сквозная «N.» без «N.M»"
    return "нумерация не найдена"


# --- summary --------------------------------------------------------------------------------


def _pct(part: float, whole: float) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "—"


_SHARES = (
    (0.0, 1e-9, "0"),
    (1e-9, 0.05, "< 5%"),
    (0.05, 0.2, "5–20%"),
    (0.2, 0.5, "20–50%"),
    (0.5, 0.8, "50–80%"),
    (0.8, 2.0, "≥ 80%"),
)


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


_COUNTS: tuple[tuple[int, int | None], ...] = (
    (0, 0), (1, 1), (2, 3), (4, 10), (11, 50), (51, 200), (201, None),
)


def count_buckets(values: Iterable[int]) -> str:
    """`0: 2, 1: 4, 2–3: 1` — how many values fall into each range."""
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
    with_kind = [d for d in docs if d.starts[kind]]
    return f"{len(with_kind)} док., {sum(d.starts[kind] for d in docs)} строк"


_HOW = {
    "requisites_numbered": "заголовок реквизитов с номером «N.»",
    "requisites_caps": "заголовок реквизитов прописными без номера",
    "appendix": "«Приложение» вверху страницы (реквизитов не найдено)",
    "none": "не найдена (хвоста нет)",
}

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

_LEVEL1_NAMES = {
    "first": "первый",
    "next": "следующий",
    "repeat": "повтор",
    "gap": "пропуск",
    "restart": "заново с 1",
    "other": "иначе",
}

_KINDS = (
    ("word_section", "«Раздел/Статья/Глава K»"),
    ("roman", "«I. …» римские"),
    ("caps_heading", "заголовок прописными без номера"),
    ("bare_number", "номер на отдельной строке"),
    ("paren_num", "перечень «1)»"),
    ("letter", "перечень «а)»"),
    ("appendix", "строка начинается с «Приложение»"),
    ("date", "строка начинается с даты"),
    ("sum", "строка начинается с суммы"),
)


def _steps_lines(docs: Sequence[DocSurvey], attr: str, names: Mapping[str, str]) -> list[str]:
    total: Counter[str] = Counter()
    for d in docs:
        total.update(getattr(d, attr))
    whole = sum(total.values())
    out = []
    for key, name in names.items():
        if total[key]:
            with_key = sum(1 for d in docs if getattr(d, attr)[key])
            out.append(f"     {name}: {total[key]} ({_pct(total[key], whole)}), {with_key} док.")
    return out or ["     —"]


def summary_lines(docs: Sequence[DocSurvey]) -> list[str]:
    """The report. Counts, shares, ranges and document ids only."""
    n = len(docs)
    out = [f"Документов: {n}; страниц: {sum(d.pages for d in docs)}", ""]
    if not n:
        return [*out, "Нет документов, доступных после чтения."]

    out.append("1. Граница основного текста")
    for how, name in _HOW.items():
        members = [d for d in docs if d.how == how]
        if members:
            out.append(f"   {name}: {len(members)} док. — {_ids(members)}")
    early = [d for d in docs if d.appendix_top_before_end]
    out.append(
        f"   «Приложение» вверху страницы внутри основного текста: {len(early)} док. — "
        f"{_ids(early)}"
    )
    out.append(
        "   строк в разделе реквизитов (до приложения или конца): "
        + count_buckets(
            d.requisites_section_lines for d in docs if d.requisites_section_lines is not None
        )
    )
    for attr, name in (
        ("preamble_share", "преамбула"),
        ("main_share", "основной текст"),
        ("requisites_share", "раздел реквизитов"),
        ("appendix_share", "приложения"),
    ):
        out.append(f"   доля текста — {name}: " + share_buckets(getattr(d, attr) for d in docs))

    out += ["", "2. Нумерация в основном тексте"]
    out.append("   Стиль документа:")
    for style, count in Counter(d.style for d in docs).most_common():
        members = [d for d in docs if d.style == style]
        out.append(f"     {style}: {count} ({_pct(count, n)}) — {_ids(members)}")
    heading = sum(d.level1_heading for d in docs)
    sentence = sum(d.level1_sentence for d in docs)
    out.append(
        f"   «N. …» уровня 1: {heading + sentence} строк; за ними «N.1» (заголовок раздела): "
        f"{heading}; без «N.1»: {sentence}"
    )
    out.append(
        f"     короче {TITLE_MAX_CHARS + 1} знаков: {sum(d.level1_short for d in docs)}; "
        f"прописными: {sum(d.level1_caps for d in docs)}"
    )
    out.append(
        "     строк «N.» без «N.1» на документ: "
        + count_buckets(d.level1_sentence for d in docs)
    )
    for depth, example in ((2, "5.2"), (3, "5.2.1"), (4, "5.2.1.1")):
        out.append(
            f"   номера глубины {depth} («{example}»): "
            f"{sum(1 for d in docs if d.depth[depth])} док., "
            f"{sum(d.depth[depth] for d in docs)} строк"
        )
    for kind, name in _KINDS[:6]:
        out.append(f"   {name}: {_docs_lines(docs, kind)}")

    out += ["", "3. Продолжение нумерации в основном тексте"]
    out.append("   «N.M» после последнего принятого номера:")
    out += _steps_lines(docs, "steps", _STEP_NAMES)
    out.append("   «N.» после последнего принятого номера:")
    out += _steps_lines(docs, "level1_steps", _LEVEL1_NAMES)
    for key, name in (("comma", "«5,2 …» (запятая)"), ("glued", "«5.2Текст» (без пробела)")):
        out.append(
            f"   номер, возможно испорченный распознаванием, {name}: "
            f"{sum(1 for d in docs if d.damaged_numbers[key])} док., "
            f"{sum(d.damaged_numbers[key] for d in docs)} строк"
        )

    out += ["", "4. Риски в основном тексте"]
    for kind, name in _KINDS[6:]:
        out.append(f"   {name}: {_docs_lines(docs, kind)}")
    out.append(
        f"   строки таблиц: {sum(1 for d in docs if d.table_lines)} док., "
        f"{sum(d.table_lines for d in docs)} строк; из них начинаются с номера: "
        f"{sum(d.table_number_lines for d in docs)}"
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
    pages = sum(d.main_pages for d in docs)
    out.append(f"   страниц основного текста: {pages}")
    for code, name in (
        (RECOGNIZED, "распознаны (фича 13)"),
        ("low_recognition_quality", "низкое качество распознавания"),
        ("ocr_text", "текстовый слой от распознавания"),
        ("unread", "не прочитаны (скан, нет текста, нечитаемо)"),
    ):
        count = sum(d.main_flagged_pages[code] for d in docs)
        out.append(
            f"     «{name}»: {count} стр. ({_pct(count, pages)}), "
            f"{sum(1 for d in docs if d.main_flagged_pages[code])} док."
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
        "Обзор структуры договоров, фича 04 — только цифры (версия 2)",
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
