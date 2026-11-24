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

import time
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import psycopg

from docreader import embedding, extraction_text, passages, runs, stages, wordforms
from docreader.config import Settings
from docreader.errors import ModelUnavailable, UserError
from docreader.ids import format_document_id
from docreader.stages import RunStage, Stage, State

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


# --- the stage: `docreader index` ------------------------------------------------------------


@dataclass(frozen=True)
class IndexedDocument:
    """One line of the `index` output (contracts/cli.md); no labels, no text."""

    document_id: str
    state: str
    reason: str | None
    passages: int
    word_entries: int
    vectors: int
    truncated: int
    seconds: float


@dataclass(frozen=True)
class Stopped:
    """The search model server stopped answering on this document: the run ended there."""

    document_id: str
    reason: str


@dataclass
class IndexRun:
    """Result of one `index` command (contracts/cli.md «docreader index»)."""

    run_id: int | None = None
    model: str | None = None
    served_model: str | None = None
    dims: int | None = None
    documents: list[IndexedDocument] = field(default_factory=list)
    skipped: list[SkippedDocument] = field(default_factory=list)
    interrupted: bool = False
    stopped: Stopped | None = None

    @property
    def totals(self) -> dict[str, int]:
        states = [d.state for d in self.documents]
        return {
            "indexed": states.count(State.DONE),
            "needs_review": states.count(State.NEEDS_REVIEW),
            "failed": states.count(State.FAILED),
            "skipped": len(self.skipped),
            "passages": sum(d.passages for d in self.documents),
        }

    def to_json(self) -> dict:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "served_model": self.served_model,
            "dims": self.dims,
            "documents": [asdict(d) for d in self.documents],
            "skipped": [asdict(s) for s in self.skipped],
            "totals": self.totals,
            "interrupted": self.interrupted,
            "stopped": asdict(self.stopped) if self.stopped else None,
        }


def _error_reason(exc: Exception) -> str:
    # Only the kind of error: a message may quote contract text (Constitution I).
    if isinstance(exc, embedding.EmbeddingRequestError):
        return f"ошибка построения векторов: {type(exc).__name__}"
    return f"ошибка индексации: {type(exc).__name__}"


def _failed(doc_id: str, reason: str, seconds: float) -> IndexedDocument:
    return IndexedDocument(doc_id, State.FAILED, reason, 0, 0, 0, 0, seconds)


def _index_document(
    conn: psycopg.Connection,
    settings: Settings,
    embedder: embedding.Embedder,
    run_id: int,
    doc_id: str,
) -> IndexedDocument:
    """Index one document. Raises ModelUnavailable (the run stops) and nothing else
    from the model; any other failure becomes a `failed` line."""
    started = time.monotonic()
    cfg = settings.embedding
    try:
        text, sha = conn.execute(
            "SELECT text, text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
        ).fetchone() or ("", "")
        rows = conn.execute(
            "SELECT key, kind, depth, start, end_, section_number, section_title, run_id"
            " FROM clause WHERE document_id = %s ORDER BY ordinal",
            (doc_id,),
        ).fetchall()
        records = [passages.ClauseRecord(*row[:7]) for row in rows]
        structure_run = rows[0][7] if rows else 0
        by_key = {r.key: r for r in records}
        spans = conn.execute(
            "SELECT start, page_number FROM text_span WHERE document_id = %s ORDER BY start",
            (doc_id,),
        ).fetchall()
        starts = [s for s, _ in spans]

        def page_of(offset: int) -> int:
            return spans[max(bisect_right(starts, offset) - 1, 0)][1]

        tail = next((r for r in records if r.kind == "tail"), None)
        tail_end = extraction_text.shown_end(text, tail.start) if tail else len(text)
        cuts = passages.cut(text, records, tail_end)
        passage_rows: list[PassageRow] = []
        inputs: list[str] = []
        truncated_flags: list[bool] = []
        for ordinal, span in enumerate(cuts):
            record = by_key[span.key]
            label = passages.label(doc_id, record)
            body = text[span.start : span.end]
            text_in, was_cut = embedding_input(label, body, cfg.max_chars)
            inputs.append(text_in)
            truncated_flags.append(was_cut)
            passage_rows.append(
                PassageRow(
                    clause_key=span.key,
                    ordinal=ordinal,
                    part=span.part,
                    start=span.start,
                    end=span.end,
                    first_page=page_of(span.start),
                    last_page=page_of(span.end - 1),
                    label=label,
                    lemmas=wordforms.lemmatize(label + "\n" + body),
                    source_text_sha256=sha,
                    structure_run_id=structure_run,
                )
            )
        embedded = embedder.embed(inputs)  # outside any transaction
        vector_rows = [
            VectorRow(p.clause_key, cfg.model, vec, len(text_in), was_cut)
            for p, vec, text_in, was_cut in zip(
                passage_rows, embedded, inputs, truncated_flags, strict=True
            )
        ]
        keys = [p.clause_key for p in passage_rows]
        cut_keys = {p.clause_key for p, f in zip(passage_rows, truncated_flags, strict=True) if f}
        state, reason = index_state(keys, cut_keys, doc_id)
        store_document(conn, doc_id, passage_rows, vector_rows, state, reason, run_id)
    except ModelUnavailable:
        raise
    except Exception as exc:  # one document's failure must not stop the others
        reason = _error_reason(exc)
        with conn.transaction():
            stages.set_state(conn, doc_id, Stage.INDEXING, State.FAILED, reason, run_id)
        return _failed(doc_id, reason, time.monotonic() - started)
    return IndexedDocument(
        doc_id, state, reason, len(passage_rows), len(passage_rows), len(vector_rows),
        len(cut_keys), time.monotonic() - started,
    )


def index_documents(
    conn: psycopg.Connection,
    settings: Settings,
    seqs: Sequence[int] | None,
    all_documents: bool = False,
    label: str | None = None,
) -> IndexRun:
    """Index the chosen documents (contracts/cli.md «docreader index»); T017.

    Nothing to index → `run_id` None. A stopped model server ends the run with `stopped`
    set; the caller exits with code 2.
    """
    if seqs and all_documents:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    chosen, skipped = select_documents(conn, seqs, all_documents)
    result = IndexRun(skipped=skipped)
    if not chosen:
        return result
    embedder = embedding.load_embedder(settings.embedding)
    info = embedder.check()
    run_settings = {
        **settings.settings_for_run(),
        "served_model": info.served_model,
        "dims": info.dims,
    }
    run_id = runs.start_run(conn, RunStage.INDEXING, run_settings, label)
    conn.execute("UPDATE run SET model = %s WHERE id = %s", (settings.embedding.model, run_id))
    result.run_id = run_id
    result.model = settings.embedding.model
    result.served_model = info.served_model
    result.dims = info.dims
    try:
        for doc_id in chosen:
            try:
                result.documents.append(_index_document(conn, settings, embedder, run_id, doc_id))
            except ModelUnavailable as exc:
                # it follows «Остановлено на D-0004: » in the output, so lower-case it
                message = str(exc)
                result.stopped = Stopped(doc_id, message[:1].lower() + message[1:])
                break
    except KeyboardInterrupt:
        result.interrupted = True
    runs.finish_run(conn, run_id)
    return result
