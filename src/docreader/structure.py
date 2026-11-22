"""The structure rule: cleaned text lines → preamble, sections, clauses, tail (feature 04).

Pure functions, no database (research R-1…R-5, R-7 of specs/004-structure-parsing).
A record starts at a line whose number continues the numbering; everything else stays
in the text of the record it falls into, so no text is lost (FR-006).
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Sequence
from dataclasses import dataclass

from docreader.config import StructureSettings
from docreader.ids import PREAMBLE_KEY, TAIL_KEY, clause_key

# A number at the start of a line: parts of 1–3 digits without a leading zero, joined by
# dots, an optional final dot; then a space, the end or a letter («5.2Оплата», R-2).
_NUMBER = re.compile(r"(?P<num>[1-9]\d{0,2}(?:\.[1-9]\d{0,2})*)(?P<dot>\.?)(?=\s|$|[^\W\d_])")
# A unit right after the number makes it an amount, not a clause («5.3 млн», R-2).
_UNIT = re.compile(r"(?:млн|млрд|тыс|руб|коп|р\.|%|кг|тонн|км|мм|см|м²|м³|м2|м3|шт)", re.I)

NO_NUMBERING = "no_numbering"
NO_TAIL = "no_tail"
AFTER_TAIL = "after_tail"
GAP = "gap"
REPEAT = "repeat"
OUT_OF_ORDER = "out_of_order"
HEADING_AFTER_CLAUSE = "heading_after_clause"
UNREAD = "unread"
# The kinds in the order of the reason (research R-7) and how each is written: a prefix
# before its items joined with ", "; kinds without items are the prefix alone.
_REASON: dict[str, str] = {
    NO_NUMBERING: "нумерация не найдена",
    NO_TAIL: "раздел реквизитов не найден",
    AFTER_TAIL: "",
    GAP: "пропуск: ",
    REPEAT: "повтор: ",
    OUT_OF_ORDER: "номер вне порядка: ",
    HEADING_AFTER_CLAUSE: "",
    UNREAD: "не прочитана страница внутри основного текста: ",
}
_KIND_ORDER = tuple(_REASON)
_WITHOUT_ITEMS = frozenset({NO_NUMBERING, NO_TAIL})


@dataclass(frozen=True)
class Line:
    """One span of the cleaned text: [start, end), its page, text and marks (R-1)."""

    start: int
    end: int
    page: int
    text: str
    table: bool = False
    line_start: bool = True  # False for a span glued to the previous one (hyphenation)


@dataclass(frozen=True)
class Candidate:
    number: tuple[int, ...]
    printed: str
    rest: str


@dataclass(frozen=True)
class ClauseRecord:
    """One record of the `clause` table; `start`/`end` — its own text."""

    ordinal: int
    key: str
    kind: str  # preamble, section, clause, tail
    number: tuple[int, ...] | None
    number_printed: str | None
    depth: int
    parent_key: str | None
    title: str | None
    section_number: int | None
    section_title: str | None
    start: int
    end: int
    first_page: int
    last_page: int


@dataclass(frozen=True)
class Finding:
    kind: str
    text: str  # one item of the reason; "" for kinds without items


@dataclass(frozen=True)
class ParseResult:
    records: tuple[ClauseRecord, ...]
    findings: tuple[Finding, ...]
    reason: str | None  # None when there are no findings (state `done`)


def candidate(text: str) -> Candidate | None:
    """The number a line starts with, if it may start a record (R-2)."""
    m = _NUMBER.match(text)
    if m is None:
        return None
    number = tuple(int(part) for part in m.group("num").split("."))
    if len(number) == 1 and not m.group("dot"):
        return None  # «5 Цена», «5)»: a single number needs its dot
    rest = text[m.end() :].strip()
    if _UNIT.match(rest):
        return None
    return Candidate(number, m.group("num") + m.group("dot"), rest)


def _step(current: tuple[int, ...], number: tuple[int, ...], max_step: int) -> int | None:
    """Size of the step from `current` to `number` if it continues the numbering (R-3).

    1 is the next number, 2…max_step a gap; None — not a continuation.
    """
    for level in range(1, len(current) + 1):
        if len(number) >= level and number[: level - 1] == current[: level - 1]:
            step = number[level - 1] - current[level - 1]
            if 1 <= step <= max_step and all(n == 1 for n in number[level:]):
                return step
    depth = len(current)
    if len(number) > depth and number[:depth] == current:
        first = number[depth]
        if 1 <= first <= max_step and all(n == 1 for n in number[depth + 1 :]):
            return first
    return None


def _after(number: tuple[int, ...]) -> str:
    return "в начале" if number == (0,) else f"после {clause_key(number)}"


@dataclass(frozen=True)
class _Start:
    line: Line
    number: tuple[int, ...]
    printed: str
    rest: str


def parse_lines(
    lines: Sequence[Line],
    text_length: int,
    settings: StructureSettings,
    unread_pages: Sequence[int] = (),
) -> ParseResult:
    """Split the text into records and findings. `lines` are in text order."""
    requisites = re.compile(settings.requisites_pattern, re.IGNORECASE)
    max_step = settings.max_gap + 1
    findings: list[Finding] = []
    starts: list[_Start] = []
    accepted: set[tuple[int, ...]] = set()
    headed_sections: set[int] = set()
    unheaded_sections: dict[int, str] = {}  # section number -> key of its first clause
    current: tuple[int, ...] = (0,)
    tail: Line | None = None
    tail_number = 0
    after_tail_checked = False

    for line in lines:
        if not line.line_start or line.table:
            continue
        cand = candidate(line.text)
        if cand is None:
            continue
        number = cand.number
        where = f"(стр. {line.page})"
        if tail is not None:
            # Only the first section number after the tail start is checked (R-4).
            if len(number) == 1 and not after_tail_checked:
                after_tail_checked = True
                if tail_number < number[0] <= tail_number + max_step:
                    text = f"после начала хвоста идёт раздел {number[0]} {where}"
                    findings.append(Finding(AFTER_TAIL, text))
            continue
        if starts and len(number) == 1 and number[0] > current[0] and requisites.search(cand.rest):
            if number[0] > current[0] + 1:
                findings.append(Finding(GAP, f"{_after(current)} идёт {number[0]} {where}"))
            tail, tail_number = line, number[0]
            continue
        step = _step(current, number, max_step)
        if step is not None:
            if step > 1:
                text = f"{_after(current)} идёт {clause_key(number)} {where}"
                findings.append(Finding(GAP, text))
            starts.append(_Start(line, number, cand.printed, cand.rest))
            accepted.add(number)
            if len(number) == 1:
                headed_sections.add(number[0])
            elif number[0] not in headed_sections:
                unheaded_sections.setdefault(number[0], clause_key(number))
            current = number
        elif number in accepted:
            findings.append(Finding(REPEAT, f"{clause_key(number)} {where}"))
        elif len(number) == 1 and number[0] == current[0] and number[0] in unheaded_sections:
            first = unheaded_sections[number[0]]
            text = f"заголовок раздела {number[0]} после пункта {first} {where}"
            findings.append(Finding(HEADING_AFTER_CLAUSE, text))
        elif number > current:
            text = f"{clause_key(number)} после {clause_key(current)} {where}"
            findings.append(Finding(OUT_OF_ORDER, text))
        # A number backwards (a reference, an amount) stays in the text silently (R-3).

    records = _records(starts, tail, text_length, _PageIndex(lines))
    if not starts:
        findings = [Finding(NO_NUMBERING, "")]
    else:
        if tail is None:
            findings.append(Finding(NO_TAIL, ""))
        main = [r for r in records if r.kind in ("section", "clause")]
        first_page, last_page = main[0].first_page, main[-1].last_page
        for page in sorted(set(unread_pages)):
            if first_page < page < last_page:
                findings.append(Finding(UNREAD, f"стр. {page}"))
    ordered = tuple(sorted(findings, key=lambda f: _KIND_ORDER.index(f.kind)))
    return ParseResult(records, ordered, _reason(ordered))


class _PageIndex:
    """Page of a text offset: the page of the last line starting at or before it."""

    def __init__(self, lines: Sequence[Line]) -> None:
        self._starts = [line.start for line in lines]
        self._pages = [line.page for line in lines]

    def page_at(self, offset: int) -> int:
        i = bisect.bisect_right(self._starts, offset) - 1
        return self._pages[max(i, 0)]


def _records(
    starts: Sequence[_Start], tail: Line | None, text_length: int, pages: _PageIndex
) -> tuple[ClauseRecord, ...]:
    records: list[ClauseRecord] = []

    def add(
        key: str,
        kind: str,
        start: int,
        end: int,
        number: tuple[int, ...] | None = None,
        printed: str | None = None,
        parent: str | None = None,
        title: str | None = None,
        section: int | None = None,
        section_title: str | None = None,
    ) -> None:
        records.append(
            ClauseRecord(
                ordinal=len(records),
                key=key,
                kind=kind,
                number=number,
                number_printed=printed,
                depth=len(number) if number else 0,
                parent_key=parent,
                title=title,
                section_number=section,
                section_title=section_title,
                start=start,
                end=end,
                first_page=pages.page_at(start),
                last_page=pages.page_at(end - 1),
            )
        )

    if not starts:
        if text_length > 0:
            add(PREAMBLE_KEY, "preamble", 0, text_length)
        return tuple(records)

    main_end = tail.start if tail is not None else text_length
    if starts[0].line.start > 0:
        add(PREAMBLE_KEY, "preamble", 0, starts[0].line.start)
    titles: dict[int, str] = {}
    keys: set[str] = set()
    for i, s in enumerate(starts):
        end = starts[i + 1].line.start if i + 1 < len(starts) else main_end
        key = clause_key(s.number)
        is_section = len(s.number) == 1
        if is_section:
            titles[s.number[0]] = s.rest
        ancestors = (clause_key(s.number[:d]) for d in range(len(s.number) - 1, 0, -1))
        parent = next((k for k in ancestors if k in keys), None)
        section = s.number[0] if s.number[0] in titles else None
        add(
            key,
            "section" if is_section else "clause",
            s.line.start,
            end,
            number=s.number,
            printed=s.printed,
            parent=parent,
            title=s.rest if is_section else None,
            section=section,
            section_title=titles[section] if section is not None else None,
        )
        keys.add(key)
    if tail is not None:
        add(TAIL_KEY, "tail", tail.start, text_length)
    return tuple(records)


def _reason(findings: Sequence[Finding]) -> str | None:
    """All findings as one reason: kinds in the order of R-7, items of a kind joined."""
    parts: list[str] = []
    for kind in _KIND_ORDER:
        items = [f.text for f in findings if f.kind == kind]
        if items:
            prefix = _REASON[kind]
            parts.append(prefix if kind in _WITHOUT_ITEMS else prefix + ", ".join(items))
    return "; ".join(parts) if parts else None
