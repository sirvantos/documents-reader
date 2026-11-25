"""The program check of the model's answer and the state of a document (feature 05).

Research R-5 (quote → place, clause, pages) and R-8 (result of a field, state and reason).
Pure functions on a `TextIndex`; no database and no model (principle III: the program,
not the model, decides whether a quote is in the contract and holds the value).

The quote is looked up with `textnorm.locate`, the one search for quotes (tech-context
«Договорённости между этапами»), only inside the part shown to the model. The clause
and the pages come from where the quote is, the clause the model named is only a hint
when the quote occurs more than once.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from docreader.fields import PROTOTYPE_FIELDS, FieldSpec, Result
from docreader.ids import format_clause_id
from docreader.stages import State
from docreader.textnorm import locate
from docreader.values import ValueNotNormalized, find_in_quote, normalize

NO_QUOTE = "нет цитаты"
QUOTE_NOT_FOUND = "цитата не найдена"
VALUE_NOT_CONFIRMED = "значение не подтверждено цитатой"
PARTIES = "состав сторон не соответствует допущению"

_LABELS = {f.name: f.label for f in PROTOTYPE_FIELDS}
_CLAUSE_HINT = re.compile(r"^(?:п\.|пп\.|пункт|подпункт)\s*", re.IGNORECASE)


class FieldAnswerLike(Protocol):
    """One field of the model's answer (extraction_prompt.FieldAnswer)."""

    found: bool
    value: str | None
    quote: str | None
    clause: str | None


class PartyAnswerLike(Protocol):
    found: bool
    quote: str | None
    clause: str | None


@dataclass(frozen=True)
class ClauseRange:
    """A record of the parse (feature 04): key, kind and own text range."""

    key: str
    kind: str
    start: int
    end: int


@dataclass(frozen=True)
class TextIndex:
    """The clean text of a document with its clauses and `text_span` lines."""

    text: str
    shown_end: int
    clauses: Sequence[ClauseRange]  # in text order
    spans: Sequence[tuple[int, int, int, int]]  # (start, end, page, line), in text order
    text_sha256: str

    @property
    def shown_last_page(self) -> int | None:
        """The page of the last line that starts inside the shown part."""
        pages = [page for start, _, page, _ in self.spans if start < self.shown_end]
        return pages[-1] if pages else None


@dataclass(frozen=True)
class FieldResult:
    """One row of `field_value` without the document, the run and the text fingerprint."""

    field: str
    result: Result
    value_text: str | None = None
    value_normalized: str | None = None
    quote: str | None = None
    quote_start: int | None = None
    quote_end: int | None = None
    clause_key: str | None = None
    page: int | None = None
    pages: tuple[int, ...] | None = None
    reason: str | None = None
    proposed_value: str | None = None
    proposed_quote: str | None = None
    proposed_clause: str | None = None


@dataclass(frozen=True)
class PartyResult:
    """The model reported a party other than Заказчик and Подрядчик (research R-8)."""

    found: bool
    quote_found: bool = False
    clause_key: str | None = None
    page: int | None = None


@dataclass(frozen=True)
class _Place:
    start: int
    end: int
    clause_key: str
    pages: tuple[int, ...]


def clause_hint_key(clause: str | None) -> str | None:
    """`2.1`, `2.1.`, `п. 2.1`, `пункт 2.1` → `2.1`; `Преамбула` → `преамбула`."""
    if not clause or not clause.strip():
        return None
    key = _CLAUSE_HINT.sub("", clause.strip()).strip().rstrip(".").strip()
    return key.lower() if key and not key[0].isdigit() else key or None


def _clause_at(index: TextIndex, offset: int) -> ClauseRange | None:
    starts = [c.start for c in index.clauses]
    i = bisect_right(starts, offset) - 1
    if i >= 0 and index.clauses[i].start <= offset < index.clauses[i].end:
        return index.clauses[i]
    return None


def quote_pages(
    spans: Sequence[tuple[int, int, int, int]], start: int, end: int
) -> tuple[int, ...]:
    """The pages of the `text_span` lines that overlap `[start, end)`, in text order
    (shared with the answer check of feature 09)."""
    pages: list[int] = []
    for span_start, span_end, page, _ in spans:
        if span_start < end and span_end > start and page not in pages:
            pages.append(page)
    return tuple(pages)


def _place(index: TextIndex, quote: str, clause_hint: str | None) -> _Place | None:
    """Where `quote` stands in the shown part; the occurrence in the named clause first."""
    places = []
    for start, end in locate(index.text, quote):
        if end > index.shown_end:
            continue
        clause = _clause_at(index, start)
        pages = quote_pages(index.spans, start, end)
        if clause is None or not pages:
            continue
        places.append(_Place(start, end, clause.key, pages))
    if not places:
        return None
    hint = clause_hint_key(clause_hint)
    return next((p for p in places if p.clause_key == hint), places[0])


def _blank(text: str | None) -> bool:
    return text is None or not text.strip()


def check_field(spec: FieldSpec, answer: FieldAnswerLike, index: TextIndex) -> FieldResult:
    """The result of one field (research R-8, checks top to bottom; the first that fails
    gives the reason)."""
    if not answer.found or _blank(answer.value):
        return FieldResult(spec.name, Result.NOT_FOUND)
    value = answer.value or ""

    def rejected(reason: str) -> FieldResult:
        return FieldResult(
            spec.name,
            Result.REJECTED,
            reason=reason,
            proposed_value=value,
            proposed_quote=answer.quote,
            proposed_clause=answer.clause,
        )

    if _blank(answer.quote):
        return rejected(NO_QUOTE)
    try:
        normalized = normalize(spec.kind, value)
    except ValueNotNormalized as exc:
        return rejected(str(exc))
    place = _place(index, answer.quote or "", answer.clause)
    if place is None:
        return rejected(QUOTE_NOT_FOUND)
    quote = index.text[place.start : place.end]
    span = find_in_quote(spec.kind, normalized, quote)
    if span is None:
        return rejected(VALUE_NOT_CONFIRMED)
    return FieldResult(
        spec.name,
        Result.FOUND,
        value_text=quote[span[0] : span[1]],
        value_normalized=normalized,
        quote=quote,
        quote_start=place.start,
        quote_end=place.end,
        clause_key=place.clause_key,
        page=place.pages[0],
        pages=place.pages,
        proposed_value=value,
        proposed_clause=answer.clause,
    )


def failed_results(reason: str) -> list[FieldResult]:
    """Six `failed` rows: the answer did not come in form, the text was too long, …"""
    return [FieldResult(f.name, Result.FAILED, reason=reason) for f in PROTOTYPE_FIELDS]


def check_party(answer: PartyAnswerLike, index: TextIndex) -> PartyResult:
    """The mark for a party beyond Заказчик and Подрядчик, with the place of its quote."""
    if not answer.found:
        return PartyResult(found=False)
    place = None if _blank(answer.quote) else _place(index, answer.quote or "", answer.clause)
    if place is None:
        return PartyResult(found=True, quote_found=False)
    return PartyResult(
        found=True, quote_found=True, clause_key=place.clause_key, page=place.pages[0]
    )


def _pages_text(pages: Sequence[int]) -> str:
    return ", ".join(str(p) for p in pages)


def document_state(
    results: Sequence[FieldResult],
    party: PartyResult,
    *,
    low_quality_pages: Sequence[int],
    unread_pages: Sequence[int],
    shown_last_page: int | None,
    document_id: str,
) -> tuple[State, str | None]:
    """The state of the extraction stage and its reason, built in one place (R-8).

    Order of the reason parts: rejected fields, low recognition quality of a quote page,
    unread pages of the shown part, the party mark. Only field labels, kinds of reason,
    page numbers and clause ids — never a value or a quote.
    """
    failed = [r for r in results if r.result is Result.FAILED]
    if failed:
        return State.FAILED, failed[0].reason
    parts: list[str] = []
    rejected = [r for r in results if r.result is Result.REJECTED]
    if rejected:
        parts.append(
            "отклонено: " + ", ".join(f"{_LABELS[r.field]} — {r.reason}" for r in rejected)
        )
    low = set(low_quality_pages)
    low_fields = []
    for r in results:
        if r.result is Result.FOUND and r.pages:
            hit = [p for p in r.pages if p in low]
            if hit:
                low_fields.append(f"{_LABELS[r.field]} (стр. {_pages_text(hit)})")
    if low_fields:
        parts.append("низкое качество распознавания: " + ", ".join(low_fields))
    last = shown_last_page if shown_last_page is not None else 0
    unread = sorted(p for p in set(unread_pages) if p <= last)
    if len(unread) == 1:
        parts.append(f"не прочитана страница {unread[0]}")
    elif unread:
        parts.append(f"не прочитаны страницы {_pages_text(unread)}")
    if party.found:
        if party.quote_found and party.clause_key is not None:
            where = f"{format_clause_id(document_id, party.clause_key)}, стр. {party.page}"
            parts.append(f"{PARTIES}: {where}")
        else:
            parts.append(f"{PARTIES}: {QUOTE_NOT_FOUND}")
    if parts:
        return State.NEEDS_REVIEW, "; ".join(parts)
    return State.DONE, None
