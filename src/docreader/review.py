"""The review page of the gold set (feature 02, research R-9).

The pure part: cards with their marks, order and carried answers. A card is a pair
«document, field» of the six prototype fields with the value of feature 05 and the
values of the rules (`rules.py`). The page itself is built from these cards.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from docreader import catalog
from docreader.gold import REVIEW_PATHS, GoldPath, GoldState
from docreader.values import same_value

Pair = tuple[str, str]


class Mark(StrEnum):
    """Agreement of the two sources; the order of the members is the order of the cards."""

    CHANGED = "changed"  # the system value differs from the one shown when answered
    DISAGREE = "disagree"
    RULES_ONLY = "rules_only"
    NONE = "none"
    MODEL_ONLY = "model_only"
    AGREE = "agree"


_ORDER = {mark: i for i, mark in enumerate(Mark)}


@dataclass(frozen=True)
class Shown:
    """A value shown on a card with its quote (feature 05 or the rules)."""

    value: str
    normalized: str
    clause: str | None
    quote: str
    quote_start: int
    quote_end: int
    pages: tuple[int, ...]


@dataclass(frozen=True)
class SystemField:
    """The feature 05 result of a pair; `shown` only for `found`."""

    result: str
    shown: Shown | None
    reason: str | None
    proposed_value: str | None


@dataclass(frozen=True)
class GoldRow:
    state: GoldState
    values_text: tuple[str, ...]
    values_normalized: tuple[str, ...]
    path: GoldPath
    system_normalized: str | None
    clause_key: str | None


@dataclass(frozen=True)
class Card:
    key: str
    document_id: str
    field: str
    mark: Mark
    model: Shown | None
    rules: tuple[Shown, ...]
    system: SystemField | None
    carried: dict[str, Any] | None  # the answer preselected from the gold set


def _same(field: catalog.CatalogField, a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return a is b
    return same_value(field, a, b)


def _distinct(field: catalog.CatalogField, items: Sequence[Shown]) -> list[Shown]:
    out: list[Shown] = []
    for item in items:
        if not any(_same(field, item.normalized, o.normalized) for o in out):
            out.append(item)
    return out


def _mark(
    field: catalog.CatalogField,
    model: Shown | None,
    rules: Sequence[Shown],
    gold: GoldRow | None,
) -> Mark:
    current = model.normalized if model else None
    if gold is not None and gold.path in REVIEW_PATHS:
        if not _same(field, current, gold.system_normalized):
            return Mark.CHANGED
    distinct = _distinct(field, rules)
    if len(distinct) > 1:
        return Mark.DISAGREE
    if model and distinct:
        return Mark.AGREE if _same(field, model.normalized, distinct[0].normalized) else (
            Mark.DISAGREE
        )
    if model:
        return Mark.MODEL_ONLY
    return Mark.RULES_ONLY if distinct else Mark.NONE


def _carried(
    field: catalog.CatalogField,
    doc: str,
    mark: Mark,
    model: Shown | None,
    rules: Sequence[Shown],
    gold: GoldRow | None,
) -> dict[str, Any] | None:
    if gold is None or mark is Mark.CHANGED:
        return None
    if gold.state is GoldState.ABSENT:
        return {"answer": "absent"}
    one_value = mark in (Mark.AGREE, Mark.MODEL_ONLY, Mark.RULES_ONLY)

    def matches(shown: Shown) -> bool:
        return any(_same(field, v, shown.normalized) for v in gold.values_normalized)

    if model and matches(model):
        return {"answer": "agree"} if one_value else {"answer": "chosen", "choice": "model"}
    for i, shown in enumerate(rules, start=1):
        if matches(shown):
            if one_value:
                return {"answer": "agree"}
            return {"answer": "chosen", "choice": f"rules:{i}"}
    typed: dict[str, Any] = {"answer": "typed", "value": gold.values_text[0]}
    if gold.clause_key:
        typed["clause"] = f"{doc}/{gold.clause_key}"
    return typed


def build_cards(
    documents: Sequence[str],
    fields: Sequence[str],
    system: Mapping[Pair, SystemField],
    rules: Mapping[Pair, Sequence[Shown]],
    gold: Mapping[Pair, GoldRow],
    blind_waiting: set[str],
) -> list[Card]:
    """Cards of `documents` × `fields` (documents waiting for blind marking excluded),
    ordered by mark (`Mark` order), then document, then catalog order."""
    order = {f.name: i for i, f in enumerate(catalog.CATALOG)}
    out: list[Card] = []
    for doc in documents:
        if doc in blind_waiting:
            continue
        for name in fields:
            pair = (doc, name)
            field = catalog.field(name)
            sys = system.get(pair)
            model = sys.shown if sys is not None and sys.result == "found" else None
            found_rules = tuple(rules.get(pair, ()))
            g = gold.get(pair)
            mark = _mark(field, model, found_rules, g)
            out.append(
                Card(
                    f"{doc}/{name}", doc, name, mark, model, found_rules, sys,
                    _carried(field, doc, mark, model, found_rules, g),
                )
            )
    out.sort(key=lambda c: (_ORDER[c.mark], c.document_id, order.get(c.field, len(order))))
    return out
