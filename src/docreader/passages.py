"""Passages and labels from parse records (feature 07, research R-3, R-4).

Pure functions on the cleaned text and the parse records of one document (feature 04):
no database, no model. Critical part (plan.md «Критические части»).

- `cut` — one passage per record with own text: the preamble, a clause or subclause, a
  section's text after its heading line, the tail up to the first «Приложение» line
  (`tail_end`, from `extraction_text.shown_end`, the same rule as feature 05). Bounds
  are trimmed of whitespace; a record with nothing left gives no passage.
- `label` — «D-0001 · раздел 5. Ответственность сторон · пункт 5.2».
- `coverage` — the SC-001 check: non-whitespace characters that should be in a passage
  but are not, and characters inside two passages.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

SEPARATOR = " · "
_PARTS = {"preamble": "preamble", "section": "main", "clause": "main", "tail": "tail"}


@dataclass(frozen=True)
class ClauseRecord:
    """A parse record (table `clause`, feature 04) as the cutting rule needs it."""

    key: str
    kind: str  # preamble, section, clause, tail
    depth: int
    start: int
    end: int
    section_number: int | None = None
    section_title: str | None = None


@dataclass(frozen=True)
class PassageSpan:
    key: str
    part: str  # preamble, main, tail
    start: int
    end: int


def _wanted_range(text: str, record: ClauseRecord, tail_end: int) -> tuple[int, int]:
    """The part of a record's own text that belongs in its passage (before trimming)."""
    start, end = record.start, record.end
    if record.kind == "section":
        newline = text.find("\n", start, end)
        start = end if newline < 0 else newline + 1
    elif record.kind == "tail":
        end = max(start, min(end, tail_end))
    return start, end


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def cut(text: str, records: Sequence[ClauseRecord], tail_end: int) -> list[PassageSpan]:
    """The passages of a document, in text order."""
    spans = []
    for record in sorted(records, key=lambda r: r.start):
        start, end = _trim(text, *_wanted_range(text, record, tail_end))
        if end > start:
            spans.append(PassageSpan(record.key, _PARTS[record.kind], start, end))
    return spans


def label(document_id: str, record: ClauseRecord) -> str:
    """The context label of a record's passage (research R-4)."""
    if record.kind == "preamble":
        return f"{document_id}{SEPARATOR}преамбула"
    if record.kind == "tail":
        return f"{document_id}{SEPARATOR}реквизиты"
    parts = [document_id]
    if record.section_number is not None:
        title = (record.section_title or "").strip()
        parts.append(f"раздел {record.section_number}. {title}" if title
                     else f"раздел {record.section_number}")
    if record.kind != "section":
        parts.append(f"пункт {record.key}")
    return SEPARATOR.join(parts)


def coverage(
    text: str, records: Sequence[ClauseRecord], tail_end: int, spans: Sequence[PassageSpan]
) -> tuple[int, int]:
    """(uncovered, doubled): non-whitespace characters of the records' own texts — without
    section heading lines and the appendices of the tail — that lie in no passage, and
    non-whitespace characters that lie in two passages or more."""
    hits = [0] * len(text)
    for span in spans:
        for i in range(span.start, span.end):
            hits[i] += 1
    uncovered = 0
    for record in records:
        start, end = _wanted_range(text, record, tail_end)
        uncovered += sum(1 for i in range(start, end) if not text[i].isspace() and not hits[i])
    doubled = sum(1 for i, n in enumerate(hits) if n > 1 and not text[i].isspace())
    return uncovered, doubled
