"""The blind control of the gold set (feature 02, research R-10).

A few documents are marked from an empty template before their review cards are shown.
The report compares those blind values with the values set by the review afterwards:
how often the review confirmed a system value that the blind marking disagrees with.
Pure functions first; the pick and the load, which use the database, come below them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from docreader import catalog, evaluation, gold
from docreader.errors import UserError
from docreader.gold import SYSTEM_CONFIRMED_PATHS, GoldPath, GoldState
from docreader.outcomes import BlindOutcome, GoldValue
from docreader.values import same_value


@dataclass(frozen=True)
class BlindPair:
    """A pair of a blind document: its blind value, its reviewed value and whether the
    reviewed value was loaded after the blind marking."""

    document_id: str
    field: str
    blind: GoldValue | None
    reviewed: GoldValue | None
    path: GoldPath | None
    after_blind: bool


def _same(field: catalog.CatalogField, a: GoldValue, b: GoldValue) -> bool:
    if a.state is not b.state:
        return False
    if a.state is GoldState.ABSENT:
        return True
    return any(same_value(field, x, y) for x in a.normalized for y in b.normalized)


def blind_outcome(field: catalog.CatalogField, pair: BlindPair) -> BlindOutcome | None:
    """The outcome of a pair, or None when its review came before the blind marking (such
    a review could not be blind to nothing, but it is not the test of the review)."""
    if pair.blind is None:
        return BlindOutcome.REVIEWED_ONLY if pair.reviewed is not None else None
    if pair.reviewed is None:
        return BlindOutcome.BLIND_ONLY
    if not pair.after_blind:
        return None
    return BlindOutcome.SAME if _same(field, pair.blind, pair.reviewed) else BlindOutcome.DIFFERS


@dataclass(frozen=True)
class BlindTotals:
    pairs: int  # counted pairs
    not_reviewed: int  # reviewed before the blind marking, not counted
    same: int
    differs: int
    blind_only: int
    reviewed_only: int
    confirmed_pairs: int  # compared pairs whose review confirmed a system value
    confirmed_differs: int  # … of them differing from the blind value

    def as_dict(self) -> dict[str, int]:
        return {
            "pairs": self.pairs, "not_reviewed": self.not_reviewed, "same": self.same,
            "differs": self.differs, "blind_only": self.blind_only,
            "reviewed_only": self.reviewed_only, "confirmed_pairs": self.confirmed_pairs,
            "confirmed_differs": self.confirmed_differs,
        }


def blind_totals(pairs: Sequence[BlindPair]) -> BlindTotals:
    counts = dict.fromkeys(BlindOutcome, 0)
    not_reviewed = confirmed = confirmed_differs = 0
    for pair in pairs:
        outcome = blind_outcome(catalog.field(pair.field), pair)
        if outcome is None:
            not_reviewed += 1
            continue
        counts[outcome] += 1
        if outcome in (BlindOutcome.SAME, BlindOutcome.DIFFERS) and (
            pair.path in SYSTEM_CONFIRMED_PATHS
        ):
            confirmed += 1
            confirmed_differs += outcome is BlindOutcome.DIFFERS
    return BlindTotals(
        sum(counts.values()), not_reviewed, counts[BlindOutcome.SAME],
        counts[BlindOutcome.DIFFERS], counts[BlindOutcome.BLIND_ONLY],
        counts[BlindOutcome.REVIEWED_ONLY], confirmed, confirmed_differs,
    )


# --- the pick of documents (research R-10) ----------------------------------------------------

PICK_COUNT = 5


def _even(items: Sequence[str], n: int) -> list[str]:
    """`n` items of a sorted list at an even step, starting with the first one."""
    if n <= 0:
        return []
    return [items[i * len(items) // n] for i in range(n)]


def pick(docs: list[dict[str, Any]], count: int = PICK_COUNT) -> list[str]:
    """One text-layer document first (if any), then scans at an even step; too few scans
    are filled with other text-layer documents. The first text-layer id comes first, the
    rest sorted; fewer documents than `count` give all of them, sorted."""
    ids = sorted(str(d["document_id"]) for d in docs)
    if len(ids) <= count:
        return ids
    layer = sorted(str(d["document_id"]) for d in docs if d["text_layer"])
    scans = sorted(str(d["document_id"]) for d in docs if not d["text_layer"])
    head = layer[:1]
    need = count - len(head)
    if len(scans) >= need:
        rest = _even(scans, need)
    else:
        rest = scans + _even(layer[1:], need - len(scans))
    return head + sorted(rest)


@dataclass(frozen=True)
class PickReport:
    documents: list[str]
    text_layer: list[str]
    template: str  # relative to the data folder


def candidates(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Documents with results of feature 05; `text_layer`: has a page of kind `text`."""
    rows = conn.execute(
        "SELECT d.id, EXISTS (SELECT 1 FROM page p WHERE p.document_id = d.id"
        " AND p.kind = 'text') FROM document d"
        " WHERE EXISTS (SELECT 1 FROM field_value f WHERE f.document_id = d.id) ORDER BY d.id"
    ).fetchall()
    return [{"document_id": doc, "text_layer": layer, "state": ""} for doc, layer in rows]


def picked(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT document_id FROM blind_pick ORDER BY 1")]


def run_pick(
    conn: psycopg.Connection, data_dir: Path, *, again: bool, now: datetime | None = None
) -> PickReport:
    """Pick (or keep) the blind documents and write the blind template for them."""
    documents = picked(conn)
    if again or not documents:
        documents = pick(candidates(conn))
        if not documents:
            raise UserError(
                "Нет документов с результатами извлечения: сначала docreader extract"
            )
        with conn.transaction():
            conn.execute("DELETE FROM blind_pick")
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO blind_pick (document_id) VALUES (%s)", [(d,) for d in documents]
                )
    layer = {c["document_id"] for c in candidates(conn) if c["text_layer"]}
    path = evaluation.new_file_path(data_dir, None, "blind", now)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gold.write_template(catalog.PROTOTYPE, documents))
    return PickReport(
        documents, [d for d in documents if d in layer], evaluation.relative_label(path, data_dir)
    )


def parse_blind_file(
    conn: psycopg.Connection, data: bytes
) -> gold.ParsedGold:
    """A filled blind template: rows of documents that were not picked are skipped."""
    documents = picked(conn)
    if not documents:
        raise UserError("Слепой контроль не начат: сначала docreader eval blind pick")
    return gold.parse_template(data, set(documents), kind=gold.LoadKind.BLIND)
