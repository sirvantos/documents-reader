"""Hybrid search over the passages of feature 07 (feature 08; research R-1 – R-11).

Scope (critical, CLAUDE.md «Model routing»; research R-3, R-5, R-6): only current
passages are searched — their text fingerprint and parse run are the document's
current ones (the rule of `indexing.passages_current`, written as one condition for the
whole set); documents without current passages are counted for a warning; the vectors
of another model are never compared; a search limited to one document never widens.

Nothing here writes to the database. No error message carries the query or contract text.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import psycopg

from docreader import embedding
from docreader.config import Settings
from docreader.errors import EnvironmentProblem, UserError
from docreader.ids import format_clause_id, format_document_id, parse_document_id
from docreader.ranking import PassageKey, bm25, rrf
from docreader.registry import _not_found, find_document
from docreader.wordforms import query_terms

# A current passage `p` (alias `t` — its document_text row): data-model.md, research R-6.
CURRENT_PASSAGE = (
    "p.source_text_sha256 = t.text_sha256"
    " AND p.structure_run_id IN (SELECT c.run_id FROM clause c"
    " WHERE c.document_id = p.document_id)"
)
_CURRENT_FROM = (
    " FROM passage p JOIN document_text t ON t.document_id = p.document_id"
    f" WHERE {CURRENT_PASSAGE}"
)


def stale_documents(conn: psycopg.Connection) -> int:
    """Registry documents without current passages: not indexed, or indexed from an older
    text or parse run (research R-6). Their passages are not searched."""
    row = conn.execute(
        "SELECT count(*) FROM document d WHERE NOT EXISTS (SELECT 1"
        + _CURRENT_FROM
        + " AND p.document_id = d.id)"
    ).fetchone()
    return int(row[0]) if row else 0


def _document(conn: psycopg.Connection, document_id: str) -> str:
    seq = parse_document_id(document_id)
    if find_document(conn, seq) is None:
        raise _not_found(seq)
    doc = format_document_id(seq)
    total = conn.execute(
        "SELECT count(*) FROM passage WHERE document_id = %s", (doc,)
    ).fetchone()
    if not total or total[0] == 0:
        raise UserError(f"Отрывков нет: выполните docreader index {doc}")
    current = conn.execute(
        "SELECT count(*)" + _CURRENT_FROM + " AND p.document_id = %s", (doc,)
    ).fetchone()
    if not current or current[0] != total[0]:
        raise UserError(
            f"Отрывки устарели: текст или разбор изменились — выполните docreader index {doc}"
        )
    return doc


def ensure_searchable(
    conn: psycopg.Connection, model: str, document_id: str | None
) -> str | None:
    """Check the scope before any model is called (research R-5, R-6, R-10).

    Returns the document id in its standard form (`D-0002`), or None for the whole set.
    UserError: unknown document, a document without passages or with stale ones, no
    current passage at all. EnvironmentProblem: no vector of `model` among the current
    passages (the meaning index was built by another model).
    """
    doc = _document(conn, document_id) if document_id is not None else None
    scope = " AND p.document_id = %s" if doc else ""
    params: tuple = (doc,) if doc else ()
    if not doc:
        row = conn.execute("SELECT count(*)" + _CURRENT_FROM, params).fetchone()
        if not row or row[0] == 0:
            raise UserError("Индексы пусты — выполните docreader index")
    vectors = conn.execute(
        "SELECT EXISTS (SELECT 1"
        + _CURRENT_FROM
        + scope
        + " AND EXISTS (SELECT 1 FROM passage_vector v WHERE v.document_id = p.document_id"
        " AND v.clause_key = p.clause_key AND v.model = %s))",
        (*params, model),
    ).fetchone()
    if not vectors or not vectors[0]:
        raise EnvironmentProblem(
            f"Индекс по смыслу построен другой моделью (нет векторов {model}) — выполните "
            "docreader index --all или укажите [embedding] model"
        )
    return doc


def word_corpus(
    conn: psycopg.Connection, document_id: str | None
) -> list[tuple[PassageKey, list[str]]]:
    """The current passages of the scope with their stored word forms, lower-cased and
    split on spaces (research R-1), in key order."""
    scope = " AND p.document_id = %s" if document_id else ""
    params: tuple = (document_id,) if document_id else ()
    rows = conn.execute(
        "SELECT p.document_id, p.ordinal, p.lemmas"
        + _CURRENT_FROM
        + scope
        + " ORDER BY p.document_id, p.ordinal",
        params,
    ).fetchall()
    return [((doc, ordinal), lemmas.lower().split()) for doc, ordinal, lemmas in rows]


def _vector_text(vector: Sequence[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def vector_candidates(
    conn: psycopg.Connection,
    model: str,
    vector: Sequence[float],
    n: int,
    document_id: str | None,
) -> list[PassageKey]:
    """The `n` current passages of the scope nearest to `vector` among the vectors of
    `model` (research R-3): exact search by cosine distance, equal distances by key."""
    scope = " AND p.document_id = %s" if document_id else ""
    params: tuple = (document_id,) if document_id else ()
    rows = conn.execute(
        "SELECT p.document_id, p.ordinal"
        " FROM passage p JOIN document_text t ON t.document_id = p.document_id"
        " JOIN passage_vector v ON v.document_id = p.document_id"
        " AND v.clause_key = p.clause_key"
        f" WHERE {CURRENT_PASSAGE}"
        + scope
        + " AND v.model = %s"
        " ORDER BY v.embedding <=> %s::vector, p.document_id, p.ordinal LIMIT %s",
        (*params, model, _vector_text(vector), n),
    ).fetchall()
    return [(doc, ordinal) for doc, ordinal in rows]


@dataclass(frozen=True)
class Hit:
    """One passage of the answer (data-model.md)."""

    place: int  # final place from 1
    document_id: str
    clause_key: str
    clause_id: str  # `D-0015/2.2.1`
    label: str
    text: str
    first_page: int | None
    last_page: int | None
    word_place: int | None
    vector_place: int | None
    fused_place: int
    rerank_score: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "place": self.place,
            "clause_id": self.clause_id,
            "label": self.label,
            "text": self.text,
            "first_page": self.first_page,
            "last_page": self.last_page,
            "word_place": self.word_place,
            "vector_place": self.vector_place,
            "fused_place": self.fused_place,
            "rerank_score": self.rerank_score,
        }


@dataclass(frozen=True)
class SearchResult:
    """The answer of `search` (data-model.md)."""

    query: str
    document_id: str | None
    reranked: bool
    hits: list[Hit]
    word_candidates: int
    vector_candidates: int
    warnings: list[str] = field(default_factory=list)
    embedding_model: str = ""
    reranker_model: str | None = None
    seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "document_id": self.document_id,
            "reranked": self.reranked,
            "embedding_model": self.embedding_model,
            "reranker_model": self.reranker_model,
            "word_candidates": self.word_candidates,
            "vector_candidates": self.vector_candidates,
            "seconds": self.seconds,
            "warnings": list(self.warnings),
            "hits": [h.to_json() for h in self.hits],
        }


def _load_passages(
    conn: psycopg.Connection, keys: Sequence[PassageKey]
) -> dict[PassageKey, tuple[str, str, int | None, int | None, str]]:
    """clause_key, label, pages and text of the passages `keys`, in one query."""
    if not keys:
        return {}
    rows = conn.execute(
        "SELECT p.document_id, p.ordinal, p.clause_key, p.label, p.first_page, p.last_page,"
        " substr(t.text, p.start + 1, p.end_ - p.start)"
        " FROM passage p JOIN document_text t ON t.document_id = p.document_id"
        " JOIN unnest(%s::text[], %s::int[]) AS k(d, o)"
        " ON k.d = p.document_id AND k.o = p.ordinal",
        ([k[0] for k in keys], [k[1] for k in keys]),
    ).fetchall()
    return {(d, o): (ck, label, fp, lp, text) for d, o, ck, label, fp, lp, text in rows}


def search(
    conn: psycopg.Connection,
    settings: Settings,
    query: str,
    *,
    document_id: str | None = None,
    rerank: bool | None = None,
    results: int | None = None,
    embedder: embedding.Embedder | None = None,
    reranker: Any = None,
) -> SearchResult:
    """Hybrid search: BM25 over word forms + vector search, fused by RRF (research R-1..R-4).

    Writes nothing. Errors and warnings never carry the query or contract text.
    """
    if not query.strip():
        raise UserError("Пустой запрос — введите слова для поиска")
    cfg = settings.search
    n = results if results is not None else cfg.results
    if not 1 <= n <= cfg.rerank_candidates:
        raise UserError(f"--results: целое от 1 до {cfg.rerank_candidates}")
    use_rerank = rerank if rerank is not None else settings.reranker.enabled
    if use_rerank:
        # TODO(T015): the rerank path (reranker client, pairs, rerank_score) is task T015.
        raise NotImplementedError("rerank path is task T015")
    doc = ensure_searchable(conn, settings.embedding.model, document_id)
    if embedder is None:
        embedder = embedding.load_embedder(settings.embedding)
    served_model = embedder.check().served_model

    started = time.perf_counter()
    warnings: list[str] = []
    if doc is None:
        stale = stale_documents(conn)
        if stale > 0:
            warnings.append(
                f"договоров без актуальных отрывков: {stale} — выполните docreader index"
            )
    limit = settings.embedding.max_chars
    if len(query) > limit:
        warnings.append(
            f"запрос длиннее предела модели поиска ({limit} знаков) — вектор построен по его началу"
        )

    terms = query_terms(query)
    word_ranked = bm25(terms, word_corpus(conn, doc))[: cfg.candidates]
    if not terms:
        warnings.append("в запросе нет слов для поиска по словам — только поиск по смыслу")
    elif not word_ranked:
        warnings.append("поиск по словам ничего не нашёл")

    (vector,) = embedder.embed([query[:limit]])
    vector_keys = vector_candidates(
        conn, settings.embedding.model, vector, cfg.candidates, doc
    )
    fused = rrf([[key for key, _ in word_ranked], vector_keys], cfg.rrf_k)[:n]
    loaded = _load_passages(conn, [key for key, _, _ in fused])
    hits: list[Hit] = []
    for place, (key, _, (word_place, vector_place)) in enumerate(fused, start=1):
        clause_key, label, first_page, last_page, text = loaded[key]
        hits.append(
            Hit(
                place=place,
                document_id=key[0],
                clause_key=clause_key,
                clause_id=format_clause_id(key[0], clause_key),
                label=label,
                text=text,
                first_page=first_page,
                last_page=last_page,
                word_place=word_place,
                vector_place=vector_place,
                fused_place=place,
            )
        )
    elapsed = time.perf_counter() - started
    return SearchResult(
        query=query,
        document_id=doc,
        reranked=False,
        hits=hits,
        word_candidates=len(word_ranked),
        vector_candidates=len(vector_keys),
        warnings=warnings,
        embedding_model=served_model,
        reranker_model=None,
        seconds=round(elapsed, 3),
    )
