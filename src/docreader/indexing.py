"""The indexing stage: passages, both indexes, the state of a document (feature 07).

Research R-6 – R-8 (specs/006-passages-and-indexes/research.md). For one document: load
the text, the parse records and the line spans → `passages.cut` and `passages.label` →
`wordforms.lemmatize` → `embedding_input` → the search model (outside any transaction)
→ one transaction that replaces the document's passages and vectors and sets its
`indexing` state (`store_document`).

Critical parts here (plan.md «Критические части»): the model input limit and the state
with its reason (`embedding_input`, `index_state`), the write (`store_document`), the
choice of documents and staleness (`select_documents`, `passages_current`). The rest of
the stage layer follows `extraction.py`.

No reason, no output line and no exception message carries a label or contract text.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import psycopg

from docreader import stages
from docreader.errors import UserError
from docreader.ids import format_document_id
from docreader.stages import Stage, State

TRUNCATED = "отрывок длиннее предела модели"
NO_PASSAGES = "нет отрывков"
_MAX_IDS_IN_REASON = 5


# --- rules (pure) ----------------------------------------------------------------------


def embedding_input(label: str, text: str, max_chars: int) -> tuple[str, bool]:
    """What goes to the search model for a passage: `label + "\\n" + text`, cut to
    `max_chars` characters; the flag tells whether it was cut (research R-6)."""
    full = f"{label}\n{text}"
    if len(full) <= max_chars:
        return full, False
    return full[:max_chars], True


def index_state(
    passage_keys: Sequence[str], truncated_keys: set[str] | frozenset[str], document_id: str
) -> tuple[State, str | None]:
    """The state of the `indexing` stage and its reason (research R-8).

    `passage_keys` in passage order; the reason names clause ids only, never text.
    """
    if not passage_keys:
        return State.NEEDS_REVIEW, NO_PASSAGES
    cut = [k for k in passage_keys if k in truncated_keys]
    if not cut:
        return State.DONE, None
    ids = [f"{document_id}/{k}" for k in cut[:_MAX_IDS_IN_REASON]]
    more = f" и ещё {len(cut) - _MAX_IDS_IN_REASON}" if len(cut) > _MAX_IDS_IN_REASON else ""
    return State.NEEDS_REVIEW, f"{TRUNCATED}: {', '.join(ids)}{more}"


# --- rows and their write ---------------------------------------------------------------


@dataclass(frozen=True)
class PassageRow:
    """One row of `passage` without the document and the run (data-model.md)."""

    clause_key: str
    ordinal: int
    part: str
    start: int
    end: int
    first_page: int
    last_page: int
    label: str
    lemmas: str
    source_text_sha256: str
    structure_run_id: int


@dataclass(frozen=True)
class VectorRow:
    """One row of `passage_vector` without the document and the run."""

    clause_key: str
    model: str
    embedding: list[float]
    input_chars: int
    truncated: bool


@dataclass(frozen=True)
class SkippedDocument:
    document_id: str
    reason: str


_INSERT_PASSAGE = (
    "INSERT INTO passage (document_id, clause_key, ordinal, part, start, end_, first_page,"
    " last_page, label, lemmas, source_text_sha256, structure_run_id, run_id)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_INSERT_VECTOR = (
    "INSERT INTO passage_vector (document_id, clause_key, model, embedding, dims,"
    " input_chars, truncated, run_id) VALUES (%s, %s, %s, %s::vector, %s, %s, %s, %s)"
)


def _vector_text(vector: Sequence[float]) -> str:
    """pgvector's text form `[x,y,…]`: no Python package needed (research R-6)."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def store_document(
    conn: psycopg.Connection,
    doc_id: str,
    passages: Sequence[PassageRow],
    vectors: Sequence[VectorRow],
    state: State,
    reason: str | None,
    run_id: int,
) -> None:
    """Replace the passages and vectors of `doc_id` and set its indexing state, all or
    nothing. A row the schema refuses (a CHECK or a key of 0006_passages.sql) rolls the
    whole document back: its previous rows and state stay (data-model.md)."""
    passage_rows = [
        (doc_id, p.clause_key, p.ordinal, p.part, p.start, p.end, p.first_page, p.last_page,
         p.label, p.lemmas, p.source_text_sha256, p.structure_run_id, run_id)
        for p in passages
    ]
    # dims is the length the code sends; the CHECK `dims = vector_dims(embedding)` and the
    # key to `passage` keep a broken row out
    vector_rows = [
        (doc_id, v.clause_key, v.model, _vector_text(v.embedding), len(v.embedding),
         v.input_chars, v.truncated, run_id)
        for v in vectors
    ]
    dims = {len(v.embedding) for v in vectors}
    if len(dims) > 1:
        raise psycopg.errors.DataException(
            "векторы документа разной длины: " + ", ".join(map(str, sorted(dims)))
        )
    with conn.transaction():
        stages.lock(conn, doc_id, Stage.INDEXING)
        conn.execute("DELETE FROM passage WHERE document_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(_INSERT_PASSAGE, passage_rows)
            cur.executemany(_INSERT_VECTOR, vector_rows)
        stages.set_state(conn, doc_id, Stage.INDEXING, state, reason, run_id)


# --- choice of documents, staleness ----------------------------------------------------------

_STATUS = (
    "SELECT d.id, d.seq, COALESCE(s.state, %(pending)s),"
    " EXISTS (SELECT 1 FROM clause c WHERE c.document_id = d.id),"
    " EXISTS (SELECT 1 FROM clause c WHERE c.document_id = d.id"
    "  AND c.source_text_sha256 IS DISTINCT FROM t.text_sha256),"
    " t.text_sha256 IS NULL"
    " FROM document d"
    " LEFT JOIN stage_status s ON s.document_id = d.id AND s.stage = %(structure)s"
    " LEFT JOIN document_text t ON t.document_id = d.id"
)

# passages built from another parse run than the current clause records (research R-7)
_OLDER_PARSE = (
    "SELECT DISTINCT p.document_id FROM passage p"
    " WHERE EXISTS (SELECT 1 FROM clause c WHERE c.document_id = p.document_id"
    "  AND c.run_id <> p.structure_run_id)"
)


def select_documents(
    conn: psycopg.Connection, seqs: Sequence[int] | None, all_documents: bool
) -> tuple[list[str], list[SkippedDocument]]:
    """Documents to index, in order, and the named ones that are not available (R-7).

    Available: `structure` done or needs_review, clause records exist, all of them made
    from the current text. Without `seqs` and `all_documents`: the available ones whose
    `indexing` is pending or failed, or whose passages come from another parse run.
    """
    params = {"pending": State.PENDING, "structure": Stage.STRUCTURE}
    rows = conn.execute(_STATUS + " ORDER BY d.seq", params).fetchall()
    parsed = (State.DONE, State.NEEDS_REVIEW)

    def available(row: tuple) -> bool:
        _, _, state, has_clauses, stale, no_text = row
        return state in parsed and has_clauses and not stale and not no_text

    if seqs:
        by_seq = {row[1]: row for row in rows}
        missing = [seq for seq in seqs if seq not in by_seq]
        if missing:
            raise UserError(
                f"Документ {format_document_id(missing[0])} не найден — "
                "список документов: docreader list"
            )
        chosen, skipped = [], []
        for seq in dict.fromkeys(seqs):
            row = by_seq[seq]
            doc_id = row[0]
            if available(row):
                chosen.append(doc_id)
            elif row[2] not in parsed or not row[3] or row[5]:
                skipped.append(
                    SkippedDocument(doc_id, f"не разобран — выполните docreader parse {doc_id}")
                )
            else:
                skipped.append(
                    SkippedDocument(doc_id, f"разбор устарел — выполните docreader parse {doc_id}")
                )
        return chosen, skipped
    ready = [row[0] for row in rows if available(row)]
    if all_documents:
        return ready, []
    due = {
        doc_id
        for (doc_id,) in conn.execute(
            "SELECT document_id FROM stage_status WHERE stage = %s AND state = ANY(%s)",
            (Stage.INDEXING, [State.PENDING, State.FAILED]),
        )
    }
    due |= {doc_id for (doc_id,) in conn.execute(_OLDER_PARSE)}
    return [doc_id for doc_id in ready if doc_id in due], []


def passages_current(conn: psycopg.Connection, doc_id: str) -> bool:
    """True when the document has passages and all of them come from its current text
    and its current parse run (FR-007; `passage` and feature 08 rely on it)."""
    row = conn.execute(
        "SELECT count(*),"
        " count(*) FILTER (WHERE p.source_text_sha256 IS DISTINCT FROM t.text_sha256"
        "  OR p.structure_run_id NOT IN (SELECT c.run_id FROM clause c"
        "   WHERE c.document_id = p.document_id))"
        " FROM passage p LEFT JOIN document_text t ON t.document_id = p.document_id"
        " WHERE p.document_id = %s",
        (doc_id,),
    ).fetchone()
    total, stale = row if row is not None else (0, 0)
    return total > 0 and stale == 0
