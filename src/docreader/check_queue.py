"""The queue page of field checks and the parse of its answers (feature 06, research R-9).

Cards are the fields with status `needs_review` or `rejected` of documents whose checks are up
to date. The page is the one of feature 02 (`review_page.render_html`, check mode).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from docreader import catalog, values
from docreader.checks import (
    CHECKS_VERSION,
    FIELDS,
    SYSTEM_CHANGED,
    DecisionKind,
    FieldStatus,
    documents_with_extraction,
    recheck,
    split_fresh,
)
from docreader.config import Settings
from docreader.errors import UserError
from docreader.ids import format_document_id, parse_document_id
from docreader.review import PageImages, Shown, new_build
from docreader.review_page import render_html

ANSWERS_FORMAT = "docreader-check-review/1"
CARDS_FORMAT = "docreader-check-cards/1"

_CATALOG_ORDER = {f.name: i for i, f in enumerate(catalog.CATALOG)}


def sort_cards(cards: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Five required fields first, then the end date; inside a group `system_changed` cards
    first, then by document and catalog order of the field (research R-9)."""

    def key(card: dict[str, Any]) -> tuple[int, int, str, int]:
        return (
            card["field"] == "contract_end_date",
            SYSTEM_CHANGED not in card["flags"],
            card["document_id"],
            _CATALOG_ORDER.get(card["field"], len(_CATALOG_ORDER)),
        )

    return sorted(cards, key=key)


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind
    value_text: str | None
    value_normalized: str | None
    clause_key: str | None


@dataclass(frozen=True)
class ParsedAnswers:
    decisions: dict[tuple[str, str], Decision]
    errors: list[tuple[str, str]]  # (card key, reason code)
    skipped: int


def parse_answers(data: bytes, cards: Sequence[dict[str, Any]]) -> ParsedAnswers:
    """The answers file of the queue page against the cards of its build (contracts/files.md)."""
    try:
        doc = json.loads(data)
    except ValueError:
        raise UserError("Файл ответов не разобрать: это не JSON") from None
    if not isinstance(doc, dict) or doc.get("format") != ANSWERS_FORMAT:
        raise UserError(f"Файл ответов не того формата: ожидается {ANSWERS_FORMAT}")
    items = doc.get("cards")
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise UserError("В файле ответов нет списка карточек")
    by_key = {c["key"]: c for c in cards}
    decisions: dict[tuple[str, str], Decision] = {}
    errors: list[tuple[str, str]] = []
    skipped = 0
    for item in items:
        key = str(item.get("key"))
        card = by_key.get(key)
        if card is None:
            errors.append((key, "unknown_card"))
            continue
        pair = (card["document_id"], card["field"])
        answer = item.get("answer")
        if answer == "skip":
            skipped += 1
        elif answer == "absent":
            decisions[pair] = Decision(DecisionKind.ABSENT, None, None, None)
        elif answer == "agree":
            if card["system"]["result"] == "found":
                decisions[pair] = Decision(DecisionKind.CONFIRM, None, None, None)
            else:
                errors.append((key, "agree_without_value"))
        elif answer == "typed":
            text = item.get("value")
            text = text.strip() if isinstance(text, str) else ""
            try:
                if not text:
                    raise ValueError("empty value")
                normalized = values.normalize_field(catalog.field(card["field"]), text)
            except ValueError:
                errors.append((key, "kind_invalid"))
                continue
            clause = item.get("clause")
            clause_key = clause.split("/", 1)[-1] if isinstance(clause, str) and clause else None
            decisions[pair] = Decision(DecisionKind.CORRECT, text, normalized, clause_key)
        else:
            errors.append((key, "unknown_answer"))
    return ParsedAnswers(decisions, errors, skipped)


@dataclass(frozen=True)
class QueueBuilt:
    path: str  # index.html, relative to the data folder
    build: str
    cards: int
    by_status: dict[str, int]
    by_field: dict[str, int]
    system_changed: int
    stale: int

    def to_json(self) -> dict[str, object]:
        return {
            "path": self.path, "build": self.build, "cards": self.cards,
            "by_status": self.by_status, "by_field": self.by_field,
            "system_changed": self.system_changed, "stale": self.stale,
        }


def _documents(conn: psycopg.Connection, ids: Sequence[str] | None) -> list[str]:
    have = documents_with_extraction(conn)
    if not ids:
        return have
    wanted = sorted({format_document_id(parse_document_id(i)) for i in ids})
    for doc in wanted:
        if doc not in have:
            raise UserError(
                f"У документа {doc} нет результатов извлечения — выполните docreader extract {doc}"
            )
    return wanted


def _system(row: tuple, images: PageImages | None, doc: str) -> tuple[dict[str, Any], dict | None]:
    """The `system` part of a card and the source block for the page (None without a value)."""
    (result, value, normalized, quote, q_start, q_end, clause, pages,
     p_value, p_quote, p_clause) = row
    system: dict[str, Any] = {
        "result": result, "value": value, "normalized": normalized, "quote": quote,
        "clause": clause, "pages": list(pages or ()), "image": None,
    }
    shown_images: list[str] = []
    if result == "found":
        assert images is not None
        shown = Shown(value, normalized, clause, quote, q_start, q_end, tuple(pages or ()))
        shown_images = [f"img/{n}" for n in images.of_quote(shown)]
        system["image"] = shown_images[0]
    elif result == "rejected":
        # the model's proposal, not accepted: its quote was not confirmed (analyze U1)
        system.update(value=p_value, quote=p_quote, clause=p_clause, unconfirmed=True)
    if system["value"] is None:
        return system, None
    return system, {**system, "images": shown_images}


def build_queue(
    conn: psycopg.Connection, settings: Settings, ids: Sequence[str] | None, out: Path | None
) -> QueueBuilt:
    """Write `checks/queue-<build>/` (cards.json, index.html, img/) and count the cards."""
    docs = _documents(conn, ids)
    fresh, stale = split_fresh(conn, settings, docs)
    build, folder = new_build(settings, out, parent="checks", prefix="queue")
    earlier = {
        (d, f): {"kind": k, "value": v, "system_normalized": n}
        for d, f, k, v, n in conn.execute(
            "SELECT document_id, field, kind, value_text, system_normalized FROM field_decision"
            " WHERE document_id = ANY(%s)",
            (fresh,),
        ).fetchall()
    }
    rows = conn.execute(
        "SELECT s.document_id, s.field, s.status, s.reasons, s.flags, v.result, v.value_text,"
        " v.value_normalized, v.quote, v.quote_start, v.quote_end, v.clause_key, v.pages,"
        " v.proposed_value, v.proposed_quote, v.proposed_clause"
        " FROM field_status s JOIN field_value v USING (document_id, field)"
        " WHERE s.document_id = ANY(%s) AND s.status = ANY(%s)",
        (fresh, [FieldStatus.NEEDS_REVIEW.value, FieldStatus.REJECTED.value]),
    ).fetchall()
    folder.mkdir(parents=True)
    (folder / "img").mkdir()
    images = PageImages(conn, settings, folder / "img")
    cards: list[dict[str, Any]] = []
    page_cards: list[dict[str, Any]] = []
    try:
        for doc in sorted({r[0] for r in rows}):
            images.open(doc)
            for row in (r for r in rows if r[0] == doc):
                _, field, status, reasons, flags = row[:5]
                system, source = _system(row[5:], images, doc)
                card = {
                    "key": f"{doc}/{field}", "document_id": doc, "field": field,
                    "status": status, "reasons": list(reasons), "flags": list(flags),
                    "system": system, "decision": earlier.get((doc, field)),
                }
                cards.append(card)
                spec = catalog.field(field)
                page_cards.append({
                    **card, "label": spec.label, "kind": spec.kind.value, "mark": status,
                    "model": source, "rules": [], "places": [],
                })
    finally:
        images.close()
    order = {c["key"]: i for i, c in enumerate(sort_cards(cards))}
    cards.sort(key=lambda c: order[c["key"]])
    page_cards.sort(key=lambda c: order[c["key"]])
    document = {
        "format": CARDS_FORMAT, "build": build, "checks_version": CHECKS_VERSION, "cards": cards,
    }
    (folder / "cards.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (folder / "index.html").write_text(
        render_html(build, page_cards, answers_format=ANSWERS_FORMAT, check=True),
        encoding="utf-8",
    )
    fields = Counter(c["field"] for c in cards)
    by_field = dict(sorted(fields.items(), key=lambda kv: (-kv[1], FIELDS.index(kv[0]))))
    statuses = Counter(c["status"] for c in cards)
    return QueueBuilt(
        path=(folder / "index.html").relative_to(settings.data_dir.resolve()).as_posix(),
        build=build,
        cards=len(cards),
        by_status={s.value: statuses.get(s.value, 0) for s in FieldStatus},
        by_field=by_field,
        system_changed=sum(SYSTEM_CHANGED in c["flags"] for c in cards),
        stale=len(stale),
    )


# --- loading the answers (research R-9, T018) ----------------------------------------------


@dataclass
class CheckLoadReport:
    cards: int
    accepted: dict[str, int]
    skipped: int
    errors: list[tuple[str, str]]
    not_applied: int
    recomputed: int

    def to_json(self) -> dict[str, object]:
        return {
            "cards": self.cards, "accepted": self.accepted, "skipped": self.skipped,
            "errors": [{"key": k, "reason": r} for k, r in self.errors],
            "not_applied": self.not_applied, "recomputed": self.recomputed,
        }


def _build_cards(settings: Settings, build: object) -> list[dict[str, Any]]:
    """The cards of the build the answers name, from `checks/queue-…/cards.json`."""
    root = settings.data_dir / "checks"
    for path in sorted(root.glob("queue-*/cards.json")) if root.is_dir() else []:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if doc.get("format") == CARDS_FORMAT and doc.get("build") == build:
            return list(doc["cards"])
    raise UserError(
        f"Сборка очереди «{build}» не найдена в папке данных (checks/queue-…): "
        "соберите очередь заново — docreader check queue"
    )


def load_answers(conn: psycopg.Connection, settings: Settings, path: Path) -> CheckLoadReport:
    """Store the decisions of a queue page answers file and recompute those documents.

    The system value of a decision is the one shown on the card (cards.json of the build);
    if the extraction changed since, the next status marks it «system_changed» (R-6 row 2).
    A decision for a document or field no longer extracted is not applied (counted).
    """
    try:
        data = path.read_bytes()
    except OSError:
        raise UserError(f"Файл ответов не прочитать: {path}") from None
    parse_answers(data, [])  # a file that is not an answers file stops here, with its reason
    cards = _build_cards(settings, json.loads(data).get("build"))
    parsed = parse_answers(data, cards)
    by_key = {c["key"]: c for c in cards}
    sha = hashlib.sha256(data).hexdigest()
    accepted = {k.value: 0 for k in DecisionKind}
    not_applied = 0
    touched: set[str] = set()
    with conn.transaction():
        for (doc, field), decision in parsed.decisions.items():
            exists = conn.execute(
                "SELECT 1 FROM field_value WHERE document_id = %s AND field = %s", (doc, field)
            ).fetchone()
            if exists is None:
                not_applied += 1
                continue
            system = by_key[f"{doc}/{field}"]["system"]
            conn.execute(
                "INSERT INTO field_decision (document_id, field, kind, value_text,"
                " value_normalized, clause_key, system_result, system_normalized,"
                " answers_sha256) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (document_id, field) DO UPDATE SET kind = EXCLUDED.kind,"
                " value_text = EXCLUDED.value_text, value_normalized = EXCLUDED.value_normalized,"
                " clause_key = EXCLUDED.clause_key, system_result = EXCLUDED.system_result,"
                " system_normalized = EXCLUDED.system_normalized,"
                " answers_sha256 = EXCLUDED.answers_sha256, decided_at = now()",
                (doc, field, decision.kind, decision.value_text, decision.value_normalized,
                 decision.clause_key, system["result"], system["normalized"], sha),
            )
            accepted[decision.kind.value] += 1
            touched.add(doc)
    recomputed = recheck(conn, settings, sorted(touched))
    return CheckLoadReport(
        cards=len(parsed.decisions) + parsed.skipped + len(parsed.errors),
        accepted=accepted, skipped=parsed.skipped, errors=parsed.errors,
        not_applied=not_applied, recomputed=recomputed,
    )
