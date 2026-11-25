"""The answer by text with checked quotes (feature 09; research R-1, R-5, R-8, R-11).

The passages come from the search of feature 08; with one contract, its preamble is
always shown to the model (FR-010, research R-5 — critical part). The quotes are checked
by `answer_check`; nothing is written to the database (FR-011).
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import psycopg

from docreader import llm, search
from docreader.answer_check import (
    AnswerOutcome,
    CheckedClaim,
    DocumentText,
    ShownPassage,
    check_claim,
    merge_retry,
    needs_retry,
    outcome,
)
from docreader.answer_prompt import (
    PROMPT_VERSION,
    AnswerReply,
    PromptPassage,
    RetryReply,
    build_messages,
    build_retry,
)
from docreader.config import Settings
from docreader.ids import PREAMBLE_KEY, format_clause_id
from docreader.runs import code_version
from docreader.search import CURRENT_PASSAGE, Hit


def _document_texts(
    conn: psycopg.Connection, documents: Sequence[str]
) -> dict[str, DocumentText]:
    texts: dict[str, DocumentText] = {}
    for doc in documents:
        row = conn.execute(
            "SELECT text FROM document_text WHERE document_id = %s", (doc,)
        ).fetchone()
        spans = [
            (start, end, page, line)
            for start, end, page, line in conn.execute(
                "SELECT start, end_, page_number, line_index FROM text_span"
                " WHERE document_id = %s ORDER BY start",
                (doc,),
            )
        ]
        texts[doc] = DocumentText(text=row[0] if row else "", spans=spans)
    return texts


def _bounds(
    conn: psycopg.Connection, hits: Sequence[Hit]
) -> dict[tuple[str, str], tuple[int, int]]:
    if not hits:
        return {}
    rows = conn.execute(
        "SELECT p.document_id, p.clause_key, p.start, p.end_ FROM passage p"
        " JOIN unnest(%s::text[], %s::text[]) AS k(d, c)"
        " ON k.d = p.document_id AND k.c = p.clause_key",
        ([h.document_id for h in hits], [h.clause_key for h in hits]),
    ).fetchall()
    return {(d, c): (s, e) for d, c, s, e in rows}


def _current_preamble(conn: psycopg.Connection, document_id: str) -> ShownPassage | None:
    """The current preamble passage of a document, marked as added by the rule."""
    row = conn.execute(
        "SELECT p.clause_key, p.label, p.start, p.end_, p.first_page, p.last_page"
        " FROM passage p JOIN document_text t ON t.document_id = p.document_id"
        f" WHERE {CURRENT_PASSAGE} AND p.document_id = %s AND p.part = 'preamble'",
        (document_id,),
    ).fetchone()
    if row is None:
        return None
    key, label, start, end, first_page, last_page = row
    return ShownPassage(
        clause_id=format_clause_id(document_id, key),
        document_id=document_id,
        clause_key=key,
        label=label,
        start=start,
        end=end,
        first_page=first_page,
        last_page=last_page,
        added_by_rule=True,
    )


def shown_passages(
    conn: psycopg.Connection, hits: Sequence[Hit], document_id: str | None
) -> tuple[list[ShownPassage], dict[str, DocumentText]]:
    """The passages shown to the model, in order, and the texts of their documents.

    The hits of the search keep their order and places. With `document_id` and at least
    one hit, the document's current preamble passage is appended last when no hit is
    that preamble (FR-010, research R-5); a document without one gets nothing added.
    """
    bounds = _bounds(conn, hits)
    shown = [
        ShownPassage(
            clause_id=h.clause_id,
            document_id=h.document_id,
            clause_key=h.clause_key,
            label=h.label,
            start=bounds[(h.document_id, h.clause_key)][0],
            end=bounds[(h.document_id, h.clause_key)][1],
            first_page=h.first_page or 0,
            last_page=h.last_page or 0,
            search_place=h.place,
            word_place=h.word_place,
            vector_place=h.vector_place,
            fused_place=h.fused_place,
        )
        for h in hits
    ]
    if document_id is not None and shown:
        has_preamble = any(
            p.document_id == document_id and p.clause_key == PREAMBLE_KEY for p in shown
        )
        if not has_preamble:
            preamble = _current_preamble(conn, document_id)
            if preamble is not None:
                shown.append(preamble)
    documents = list(dict.fromkeys(p.document_id for p in shown))
    return shown, _document_texts(conn, documents)


@dataclass(frozen=True)
class Provenance:
    """What the answer was made with (FR-008)."""

    code_version: str
    llm_model: str
    prompt_version: str
    embedding_model: str
    reranker_model: str | None
    passages: int
    candidates: int
    rrf_k: int
    rerank_candidates: int


@dataclass(frozen=True)
class Answer:
    """The result of one question (data-model.md)."""

    question: str
    document_id: str | None
    outcome: AnswerOutcome
    claims: list[CheckedClaim]
    shown: list[ShownPassage]
    retried: bool
    not_found_first: int
    not_found_final: int
    failure: str | None
    warnings: list[str]
    provenance: Provenance
    seconds: float

    def to_json(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "document_id": self.document_id,
            "outcome": self.outcome.value,
            "claims": [
                {
                    "text": c.text,
                    "quote": c.quote,
                    "named_clause": c.named_clause,
                    "status": c.status.value,
                    "clause_id": c.clause_id,
                    "quote_text": c.quote_text,
                    "pages": list(c.pages),
                    "from_retry": c.from_retry,
                }
                for c in self.claims
            ],
            "shown": [
                {
                    "clause_id": p.clause_id,
                    "label": p.label,
                    "first_page": p.first_page,
                    "last_page": p.last_page,
                    "search_place": p.search_place,
                    "word_place": p.word_place,
                    "vector_place": p.vector_place,
                    "fused_place": p.fused_place,
                    "added_by_rule": p.added_by_rule,
                }
                for p in self.shown
            ],
            "retried": self.retried,
            "not_found_first": self.not_found_first,
            "not_found_final": self.not_found_final,
            "failure": self.failure,
            "warnings": list(self.warnings),
            "seconds": self.seconds,
            "provenance": dataclasses.asdict(self.provenance),
        }


def ask(
    conn: psycopg.Connection,
    settings: Settings,
    question: str,
    *,
    document_id: str | None = None,
    passages: int | None = None,
    client: llm.ModelClient | None = None,
    embedder: Any = None,
    reranker: Any = None,
) -> Answer:
    """Answer `question` from the passages of the search, with every quote checked (R-1)."""
    n = passages or settings.answer.passages
    doc = search.ensure_searchable(conn, settings.embedding.model, document_id)
    if client is None:
        client = llm.load_client(
            dataclasses.replace(
                settings.extraction,
                max_tokens=settings.answer.max_tokens,
                max_retries=settings.answer.max_retries,
            )
        )
    llm_model = client.check()

    started = time.perf_counter()
    result = search.search(
        conn, settings, question, document_id=doc, results=n,
        embedder=embedder, reranker=reranker,
    )
    shown, texts = shown_passages(conn, result.hits, doc)
    messages = build_messages(
        question,
        [
            PromptPassage(p.clause_id, p.label, texts[p.document_id].text[p.start : p.end])
            for p in shown
        ],
    )
    reply = client.extract(messages, AnswerReply)
    checked = [check_claim(c, shown, texts) for c in reply.claims]
    asked = needs_retry(checked)
    retry_map: dict[int, CheckedClaim] | None = None
    if asked:
        retry_messages = build_retry(
            messages, reply.model_dump_json(), [(num, c.text) for num, c in asked]
        )
        try:
            retry = client.extract(retry_messages, RetryReply)
            retry_map = {c.replaces: check_claim(c, shown, texts) for c in retry.claims}
        except (llm.AnswerFormError, llm.ModelRequestError):
            retry_map = None
    merged = merge_retry(checked, asked, retry_map)
    final = outcome(merged, model_kind=reply.kind)
    return Answer(
        question=question,
        document_id=doc,
        outcome=final,
        claims=merged.claims,
        shown=shown,
        retried=bool(asked),
        not_found_first=merged.not_found_first,
        not_found_final=merged.not_found_final,
        failure=None,
        warnings=list(result.warnings),
        provenance=Provenance(
            code_version=code_version(),
            llm_model=llm_model,
            prompt_version=PROMPT_VERSION,
            embedding_model=result.embedding_model,
            reranker_model=result.reranker_model,
            passages=n,
            candidates=settings.search.candidates,
            rrf_k=settings.search.rrf_k,
            rerank_candidates=settings.search.rerank_candidates,
        ),
        seconds=round(time.perf_counter() - started, 3),
    )
