"""The review page of the gold set (feature 02, research R-9).

The pure part: cards with their marks, order and carried answers. A card is a pair
«document, field» of the six prototype fields with the value of feature 05 and the
values of the rules (`rules.py`). The page itself is built from these cards.
"""

from __future__ import annotations

import json
import secrets
from bisect import bisect_right
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import psycopg

from docreader import catalog, extraction, extraction_text, gold, passages, rules, wordforms
from docreader.config import Settings
from docreader.errors import UserError
from docreader.fields import FIELD_NAMES
from docreader.gold import REVIEW_PATHS, GoldPath, GoldState
from docreader.ids import format_clause_id, format_document_id, parse_document_id
from docreader.pageimage import line_boxes, quote_lines, render_page
from docreader.pdfpages import open_pdf
from docreader.questions import TEMPLATES
from docreader.ranking import PassageKey, bm25
from docreader.review_page import render_html
from docreader.values import same_value
from docreader.verify import FieldResult
from docreader.wordforms import query_terms

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


# --- the build: values from the database, places, images, files ---------------------------

DPI = 110
PLACES = 3
MAX_IMAGES = 3  # pages of one quote shown on a card


@dataclass(frozen=True)
class ReviewBuilt:
    """What `eval review` reports; no values and no text."""

    path: str  # index.html, relative to the data folder
    build: str
    cards: int
    marks: dict[str, int]
    carried: int
    blind_waiting: list[str]
    without_places: int  # documents without parse records: their cards have no places


def _shown_of(result: FieldResult) -> Shown:
    if (
        result.value_text is None
        or result.value_normalized is None
        or result.quote is None
        or result.quote_start is None
        or result.quote_end is None
    ):
        raise ValueError(f"a found value without its quote: {result.field}")
    return Shown(
        result.value_text, result.value_normalized, result.clause_key, result.quote,
        result.quote_start, result.quote_end, tuple(result.pages or ()),
    )


def _documents(conn: psycopg.Connection, requested: Sequence[str] | None) -> list[str]:
    have = {
        doc for (doc,) in conn.execute("SELECT DISTINCT document_id FROM field_value")
    }
    if requested:
        ids = sorted({format_document_id(parse_document_id(d)) for d in requested})
        for doc in ids:
            if doc not in have:
                raise UserError(
                    f"У документа {doc} нет результатов извлечения — выполните "
                    f"docreader extract {doc}"
                )
        return ids
    if not have:
        raise UserError(
            "Нет документов с результатами извлечения — выполните docreader extract --all"
        )
    return sorted(have)


def _load_system(conn: psycopg.Connection, doc: str) -> dict[Pair, SystemField]:
    current = conn.execute(
        "SELECT text_sha256 FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()
    sha = current[0] if current else None
    out: dict[Pair, SystemField] = {}
    for (field, result, value_text, normalized, clause, quote, start, end, pages,
         reason, proposed, row_sha) in conn.execute(
        "SELECT field, result, value_text, value_normalized, clause_key, quote, quote_start,"
        " quote_end, pages, reason, proposed_value, source_text_sha256"
        " FROM field_value WHERE document_id = %s",
        (doc,),
    ):
        if field not in FIELD_NAMES:
            continue
        if row_sha != sha:
            out[(doc, field)] = SystemField(
                "not_found", None, "текст изменился после извлечения", None
            )
        elif result == "found":
            shown = Shown(
                value_text, normalized, clause, quote, start, end, tuple(pages or ())
            )
            out[(doc, field)] = SystemField("found", shown, None, None)
        else:
            out[(doc, field)] = SystemField(result, None, reason, proposed)
    return out


def _load_gold(conn: psycopg.Connection, doc: str) -> dict[Pair, GoldRow]:
    return {
        (doc, field): GoldRow(
            GoldState(state), tuple(texts), tuple(normalized), GoldPath(path), system, clause
        )
        for field, state, texts, normalized, path, system, clause in conn.execute(
            "SELECT field, state, values_text, values_normalized, path, system_normalized,"
            " clause_key FROM gold_field WHERE document_id = %s AND field = ANY(%s)",
            (doc, list(FIELD_NAMES)),
        )
    }


def _load_rules(conn: psycopg.Connection, doc: str) -> dict[Pair, list[Shown]]:
    sections = {
        key: title
        for key, title in conn.execute(
            "SELECT key, section_title FROM clause WHERE document_id = %s", (doc,)
        )
    }
    found = rules.extract_rules(extraction._build_index(conn, doc), sections)
    return {(doc, field): [_shown_of(r) for r in results] for field, results in found.items()}


class _Images:
    """PNG files of one build: one per (document, page, marked lines), rendered once."""

    def __init__(self, conn: psycopg.Connection, settings: Settings, folder: Path) -> None:
        self._conn = conn
        self._originals = settings.originals_dir
        self._folder = folder
        self._pdf: Any = None
        self._doc = ""
        self._names: dict[tuple[str, int, tuple[int, ...]], str] = {}

    def open(self, doc: str) -> None:
        self.close()
        row = self._conn.execute("SELECT sha256 FROM document WHERE id = %s", (doc,)).fetchone()
        path = self._originals / f"{row[0] if row else ''}.pdf"
        if not path.is_file():
            raise UserError(f"Оригинал документа {doc} не найден в папке данных")
        self._pdf = open_pdf(path)
        self._doc = doc

    def close(self) -> None:
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None

    def page(self, page: int, indexes: Sequence[int] = ()) -> str:
        key = (self._doc, page, tuple(sorted(set(indexes))))
        name = self._names.get(key)
        if name is None:
            name = f"{self._doc}-p{page}-{len(self._names)}.png"
            rotation, boxes = line_boxes(self._conn, self._doc, page, key[2])
            render_page(self._pdf, page, rotation, boxes, self._folder / name, dpi=DPI)
            self._names[key] = name
        return name

    def of_quote(self, shown: Shown) -> list[str]:
        lines = quote_lines(self._conn, self._doc, shown.quote_start, shown.quote_end)
        if not lines:
            lines = {p: [] for p in shown.pages[:1]} or {1: []}
        return [self.page(p, idx) for p, idx in sorted(lines.items())[:MAX_IMAGES]]


def _source_json(shown: Shown, images: _Images) -> dict[str, Any]:
    names = images.of_quote(shown)
    return {
        "value": shown.value,
        "normalized": shown.normalized,
        "clause": shown.clause,
        "quote": shown.quote,
        "pages": list(shown.pages),
        "image": names[0],
        "images": names,
    }


class _Passages:
    """The parse records of one document with their word forms, for the word-search places.

    Cut and lemmatized as feature 07 does (`passages.cut`, `wordforms.lemmatize`), so the
    places do not wait for `index`; no model is involved.
    """

    def __init__(self, conn: psycopg.Connection, doc: str) -> None:
        text, = conn.execute(
            "SELECT text FROM document_text WHERE document_id = %s", (doc,)
        ).fetchone() or ("",)
        rows = conn.execute(
            "SELECT key, kind, depth, start, end_, section_number, section_title"
            " FROM clause WHERE document_id = %s ORDER BY ordinal",
            (doc,),
        ).fetchall()
        records = [passages.ClauseRecord(*row) for row in rows]
        by_key = {r.key: r for r in records}
        tail = next((r for r in records if r.kind == "tail"), None)
        tail_end = extraction_text.shown_end(text, tail.start) if tail else len(text)
        spans = conn.execute(
            "SELECT start, page_number FROM text_span WHERE document_id = %s ORDER BY start",
            (doc,),
        ).fetchall()
        starts = [start for start, _ in spans]

        def page_of(offset: int) -> int:
            return spans[max(bisect_right(starts, offset) - 1, 0)][1] if spans else 1

        self.corpus: list[tuple[PassageKey, list[str]]] = []
        self._pages: dict[int, tuple[str, list[int]]] = {}
        for ordinal, span in enumerate(passages.cut(text, records, tail_end)):
            lemmas = wordforms.lemmatize(
                passages.label(doc, by_key[span.key]) + "\n" + text[span.start : span.end]
            )
            self.corpus.append(((doc, ordinal), lemmas.lower().split()))
            first, last = page_of(span.start), page_of(span.end - 1)
            self._pages[ordinal] = (span.key, list(range(first, last + 1)))

    def places(self, field: str) -> list[tuple[str, list[int]]]:
        """The best `PLACES` passages for the question of `field`: (clause key, pages)."""
        ranked = bm25(query_terms(TEMPLATES[field]), self.corpus)[:PLACES]
        return [self._pages[ordinal] for (_, ordinal), _score in ranked]


def _new_build(settings: Settings, out_dir: Path | None) -> tuple[str, Path]:
    data = settings.data_dir.resolve()
    if out_dir is not None:
        folder = out_dir.resolve()
        if folder == data or not folder.is_relative_to(data):
            raise UserError(
                "Папка --out должна лежать внутри папки данных (DOCREADER_DATA_DIR): "
                "значения договоров не выносятся из неё"
            )
        if folder.exists():
            raise UserError(f"Папка {folder.name} уже есть — укажите новую, поверх не пишу")
        return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}", folder
    while True:
        build = f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        default = settings.data_dir / "eval" / f"review-{build}"
        if not default.exists():
            return build, default


def build_review(
    conn: psycopg.Connection,
    settings: Settings,
    document_ids: list[str] | None,
    out_dir: Path | None,
) -> ReviewBuilt:
    """Build `eval/review-<build>/` (cards.json, index.html, page images)."""
    build, folder = _new_build(settings, out_dir)
    docs = _documents(conn, document_ids)
    waiting = sorted(
        doc
        for (doc,) in conn.execute(
            "SELECT document_id FROM blind_pick p WHERE NOT EXISTS"
            " (SELECT 1 FROM gold_blind b WHERE b.document_id = p.document_id)"
        )
        if doc in docs
    )
    system: dict[Pair, SystemField] = {}
    rule_values: dict[Pair, Sequence[Shown]] = {}
    gold_rows: dict[Pair, GoldRow] = {}
    shown_docs = [d for d in docs if d not in waiting]
    for doc in shown_docs:
        system.update(_load_system(conn, doc))
        rule_values.update(_load_rules(conn, doc))
        gold_rows.update(_load_gold(conn, doc))
    cards = build_cards(docs, list(FIELD_NAMES), system, rule_values, gold_rows, set(waiting))

    folder.mkdir(parents=True)
    images = _Images(conn, settings, folder)
    without_places = 0
    by_key: dict[str, dict[str, Any]] = {}
    try:
        for doc in shown_docs:
            passages = _Passages(conn, doc)
            without_places += 0 if passages.corpus else 1
            images.open(doc)
            for card in (c for c in cards if c.document_id == doc):
                field = catalog.field(card.field)
                places: list[dict[str, Any]] = []
                rejected = card.system is not None and card.system.result == "rejected"
                if card.mark is Mark.NONE or rejected:
                    for key, pages in passages.places(card.field):
                        places.append({
                            "clause_id": format_clause_id(doc, key),
                            "pages": pages,
                            "image": images.page(pages[0]),
                        })
                by_key[card.key] = {
                    "key": card.key,
                    "document_id": doc,
                    "field": card.field,
                    "label": field.label,
                    "kind": field.kind.value,
                    "mark": card.mark.value,
                    "model": _source_json(card.model, images) if card.model else None,
                    "rules": [_source_json(r, images) for r in card.rules],
                    "system": None if card.system is None else {
                        "result": card.system.result,
                        "reason": card.system.reason,
                        "proposed_value": card.system.proposed_value,
                    },
                    "places": places,
                    "carried": card.carried,
                }
    finally:
        images.close()
    cards_json = [by_key[c.key] for c in cards]
    document = {"format": gold.CARDS_FORMAT, "build": build, "cards": cards_json}
    (folder / "cards.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (folder / "index.html").write_text(render_html(build, cards_json), encoding="utf-8")
    counts = Counter(c.mark for c in cards)
    return ReviewBuilt(
        path=(folder / "index.html").relative_to(settings.data_dir.resolve()).as_posix(),
        build=build,
        cards=len(cards),
        marks={m.value: counts.get(m, 0) for m in Mark},
        carried=sum(1 for c in cards if c.carried is not None),
        blind_waiting=waiting,
        without_places=without_places,
    )
