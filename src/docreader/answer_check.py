"""The program check of the model's answer (feature 09; research R-4, R-6, R-8).

Pure functions on plain values: no database and no model (principle III — the program,
not the model, decides whether a quote is in the contract). Critical part (plan.md
«Критические части»).

- `check_claim` — a quote is confirmed only inside the passages shown to the model:
  first the passages the model named, then the others in the order shown. The one
  search for quotes is `textnorm.locate` (tech-context «Договорённости между этапами»).
- `needs_retry` / `merge_retry` — the quote retry by claim numbers (analyst's decision
  U1): confirmed claims of the first answer never change; every asked claim gives one
  claim in the result — its corrected version or, when the model says nothing about it,
  the claim of the first answer with its mark. Nothing is dropped silently (principle VII).
- `outcome` — the outcome of the question.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from docreader.textnorm import locate
from docreader.verify import clause_hint_key, quote_pages

ModelKind = Literal["answer", "not_found"]

_DOCUMENT_PREFIX = re.compile(r"^\s*([dD]-\d+)\s*/\s*(.*)$", re.DOTALL)


class ClaimStatus(StrEnum):
    CONFIRMED = "confirmed"
    CONFIRMED_ELSEWHERE = "confirmed_elsewhere"
    QUOTE_NOT_FOUND = "quote_not_found"
    NO_QUOTE = "no_quote"


class AnswerOutcome(StrEnum):
    ANSWERED = "answered"
    UNCONFIRMED = "unconfirmed"
    NOT_FOUND = "not_found"
    FAILED = "failed"


class ClaimLike(Protocol):
    """One claim of the model's answer (answer_prompt.ClaimReply)."""

    text: str
    clause: str
    quote: str


@dataclass(frozen=True)
class DocumentText:
    """The clean text of a document and its `text_span` lines (start, end, page, line)."""

    text: str
    spans: Sequence[tuple[int, int, int, int]]


@dataclass(frozen=True)
class ShownPassage:
    """A passage shown to the model (data-model.md)."""

    clause_id: str
    document_id: str
    clause_key: str
    label: str
    start: int
    end: int
    first_page: int
    last_page: int
    search_place: int | None = None
    word_place: int | None = None
    vector_place: int | None = None
    fused_place: int | None = None
    added_by_rule: bool = False


@dataclass(frozen=True)
class CheckedClaim:
    """A claim after the quote check (data-model.md)."""

    text: str
    quote: str
    named_clause: str
    status: ClaimStatus
    clause_id: str | None = None
    quote_text: str | None = None
    start: int | None = None
    end: int | None = None
    pages: tuple[int, ...] = ()
    from_retry: bool = False

    @property
    def confirmed(self) -> bool:
        return self.status in (ClaimStatus.CONFIRMED, ClaimStatus.CONFIRMED_ELSEWHERE)


@dataclass(frozen=True)
class MergedClaims:
    """The claims after the retry: confirmed first, then unconfirmed."""

    claims: list[CheckedClaim] = field(default_factory=list)
    not_found_first: int = 0
    not_found_final: int = 0


def _named_passages(
    named: str, shown: Sequence[ShownPassage]
) -> list[ShownPassage]:
    """The shown passages the model named: with a `D-NNNN/` prefix only that document's;
    without one every shown passage with the key (research R-4, analyze C1)."""
    document: str | None = None
    rest = named
    match = _DOCUMENT_PREFIX.match(named)
    if match:
        document, rest = match.group(1).upper(), match.group(2)
    key = clause_hint_key(rest)
    if key is None:
        return []
    return [
        p
        for p in shown
        if p.clause_key == key and (document is None or p.document_id == document)
    ]


def check_claim(
    claim: ClaimLike, shown: Sequence[ShownPassage], texts: Mapping[str, DocumentText]
) -> CheckedClaim:
    """The quote check of one claim (research R-4)."""
    base = CheckedClaim(
        text=claim.text,
        quote=claim.quote,
        named_clause=claim.clause,
        status=ClaimStatus.QUOTE_NOT_FOUND,
    )
    if not claim.quote or not claim.quote.strip():
        return dataclasses.replace(base, status=ClaimStatus.NO_QUOTE)
    named = _named_passages(claim.clause or "", shown)
    others = [p for p in shown if p not in named]
    for passages, status in (
        (named, ClaimStatus.CONFIRMED),
        (others, ClaimStatus.CONFIRMED_ELSEWHERE),
    ):
        for p in passages:
            doc = texts[p.document_id]
            found = locate(doc.text[p.start : p.end], claim.quote)
            if not found:
                continue
            start, end = found[0][0] + p.start, found[0][1] + p.start
            return dataclasses.replace(
                base,
                status=status,
                clause_id=p.clause_id,
                quote_text=doc.text[start:end],
                start=start,
                end=end,
                pages=quote_pages(doc.spans, start, end),
            )
    return base


def needs_retry(checked: Sequence[CheckedClaim]) -> list[tuple[int, CheckedClaim]]:
    """The retry list: the unconfirmed claims, numbered from 1 in their order."""
    unconfirmed = [c for c in checked if not c.confirmed]
    return list(enumerate(unconfirmed, start=1))


def _place(c: CheckedClaim) -> tuple[str | None, int | None, int | None]:
    return c.clause_id, c.start, c.end


def merge_retry(
    first: Sequence[CheckedClaim],
    asked: Sequence[tuple[int, CheckedClaim]],
    retry: Mapping[int, CheckedClaim] | None,
) -> MergedClaims:
    """The claims after the quote retry (research R-6, analyst's decision U1).

    `asked` — the retry list (`needs_retry(first)`); `retry` — the checked claims of the
    retry answer by their `replaces` number, or None when the retry gave no answer in
    form. A returned number that was not asked is ignored.
    """
    confirmed = [c for c in first if c.confirmed]
    places = {_place(c) for c in confirmed}
    unconfirmed: list[CheckedClaim] = []
    answers = retry or {}
    for number, original in asked:
        version = answers.get(number)
        if version is None:
            unconfirmed.append(original)
            continue
        version = dataclasses.replace(version, from_retry=True)
        if not version.confirmed:
            unconfirmed.append(version)
        elif _place(version) not in places:
            confirmed.append(version)
            places.add(_place(version))
        # else: the corrected quote is a place already confirmed — counted as fixed
    asked_ids = {id(c) for _, c in asked}
    # unconfirmed claims of `first` that were not asked (no retry at all) stay as they are
    unconfirmed.extend(c for c in first if not c.confirmed and id(c) not in asked_ids)
    return MergedClaims(
        claims=confirmed + unconfirmed,
        not_found_first=sum(1 for c in first if not c.confirmed),
        not_found_final=len(unconfirmed),
    )


def outcome(
    merged: MergedClaims | None, *, model_kind: ModelKind | None, failed: bool = False
) -> AnswerOutcome:
    """The outcome of the question (research R-8). `model_kind` None — the model was not
    asked (the search found no passage)."""
    if failed:
        return AnswerOutcome.FAILED
    if model_kind is None or model_kind == "not_found":
        return AnswerOutcome.NOT_FOUND
    if merged is not None and any(c.confirmed for c in merged.claims):
        return AnswerOutcome.ANSWERED
    return AnswerOutcome.UNCONFIRMED
