"""The extraction stage: `docreader extract` (feature 05; research R-8, R-9, R-10).

Reads the saved text, parse and page flags of each document, asks the language model
once (`llm.py`), checks every field with `verify.py` and replaces the document's six
`field_value` rows and its stage state in one transaction (`store_document`).
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import psycopg

from docreader import extraction_prompt, extraction_text, llm, runs, stages, verify
from docreader.config import Settings
from docreader.errors import UserError
from docreader.fields import FIELD_NAMES, PROTOTYPE_FIELDS, Result
from docreader.ids import format_document_id
from docreader.parsing import UNREAD_FLAGS
from docreader.stages import RunStage, Stage, State
from docreader.verify import FieldResult


@dataclass(frozen=True)
class ExtractedDocument:
    """One line of the `extract` output (contracts/cli.md); no values, no quotes."""

    document_id: str
    state: str
    reason: str | None
    found: int
    not_found: int
    rejected: int
    not_found_fields: list[str]  # field names in catalog order
    rejected_fields: list[str]
    seconds: float | None  # time of the model request; None when none was sent


@dataclass(frozen=True)
class SkippedDocument:
    document_id: str
    reason: str


@dataclass(frozen=True)
class Stopped:
    """The model server stopped answering on this document: the run ended there."""

    document_id: str
    reason: str


@dataclass
class ExtractRun:
    """Result of one `extract` command (contracts/cli.md «docreader extract»)."""

    run_id: int | None = None
    model: str | None = None
    prompt_version: str | None = None
    documents: list[ExtractedDocument] = field(default_factory=list)
    skipped: list[SkippedDocument] = field(default_factory=list)
    interrupted: bool = False
    stopped: Stopped | None = None

    @property
    def totals(self) -> dict[str, int]:
        states = [d.state for d in self.documents]
        return {
            "extracted": sum(1 for s in states if s in (State.DONE, State.NEEDS_REVIEW)),
            "needs_review": states.count(State.NEEDS_REVIEW),
            "failed": states.count(State.FAILED),
            "skipped": len(self.skipped),
            "fields_found": sum(d.found for d in self.documents),
            "fields_not_found": sum(d.not_found for d in self.documents),
            "fields_rejected": sum(d.rejected for d in self.documents),
        }

    def to_json(self) -> dict:
        return {
            "run_id": self.run_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "documents": [asdict(d) for d in self.documents],
            "skipped": [asdict(s) for s in self.skipped],
            "totals": self.totals,
            "interrupted": self.interrupted,
            "stopped": asdict(self.stopped) if self.stopped else None,
        }


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


def _select(
    conn: psycopg.Connection, seqs: Sequence[int] | None, all_documents: bool
) -> tuple[list[str], list[SkippedDocument]]:
    """Documents to extract, in order, and the named ones that are not available (R-9)."""
    params = {"pending": State.PENDING, "structure": Stage.STRUCTURE}
    rows = conn.execute(_STATUS + " ORDER BY d.seq", params).fetchall()
    parsed_states = (State.DONE, State.NEEDS_REVIEW)

    def available(row: tuple) -> bool:
        _, _, state, has_clauses, stale, no_text = row
        return state in parsed_states and has_clauses and not stale and not no_text

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
            elif row[2] not in parsed_states:
                skipped.append(
                    SkippedDocument(doc_id, f"не разобран — выполните docreader parse {doc_id}")
                )
            else:
                skipped.append(
                    SkippedDocument(doc_id, f"разбор устарел — выполните docreader parse {doc_id}")
                )
        return chosen, skipped
    ready = [row for row in rows if available(row)]
    if all_documents:
        return [row[0] for row in ready], []
    todo = {
        doc_id
        for (doc_id,) in conn.execute(
            "SELECT document_id FROM stage_status WHERE stage = %s AND state = ANY(%s)",
            (Stage.EXTRACTION, [State.PENDING, State.FAILED]),
        )
    }
    # every document has a stage_status row per stage from intake (stages.create_pending)
    return [row[0] for row in ready if row[0] in todo], []


def _error_reason(exc: Exception) -> str:
    # Only the kind of error: an exception message may quote document text, and the
    # output of `extract` may be sent to the agent (Constitution I).
    return f"ошибка извлечения: {type(exc).__name__}"


def _summary(
    doc_id: str,
    results: Sequence[FieldResult],
    state: State,
    reason: str | None,
    seconds: float | None,
) -> ExtractedDocument:
    return ExtractedDocument(
        document_id=doc_id,
        state=state,
        reason=reason,
        found=sum(1 for r in results if r.result == Result.FOUND),
        not_found=sum(1 for r in results if r.result == Result.NOT_FOUND),
        rejected=sum(1 for r in results if r.result == Result.REJECTED),
        not_found_fields=[r.field for r in results if r.result == Result.NOT_FOUND],
        rejected_fields=[r.field for r in results if r.result == Result.REJECTED],
        seconds=seconds,
    )


def _catalog_order(results: Sequence[FieldResult]) -> list[FieldResult]:
    by_name = {r.field: r for r in results}
    return [by_name[name] for name in FIELD_NAMES if name in by_name]


def _build_index(conn: psycopg.Connection, doc_id: str) -> verify.TextIndex:
    text, sha = conn.execute(
        "SELECT text, text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone() or ("", "")
    clause_rows = conn.execute(
        "SELECT key, kind, start, end_ FROM clause WHERE document_id = %s ORDER BY start",
        (doc_id,),
    ).fetchall()
    clauses = [verify.ClauseRange(key, kind, start, end) for key, kind, start, end in clause_rows]
    spans = [
        (start, end, page, line)
        for start, end, page, line in conn.execute(
            "SELECT start, end_, page_number, line_index FROM text_span"
            " WHERE document_id = %s ORDER BY start",
            (doc_id,),
        )
    ]
    tail_start = next((c.start for c in clauses if c.kind == "tail"), None)
    shown = extraction_text.shown_end(text, tail_start)
    return verify.TextIndex(text, shown, clauses, spans, sha)


def _pages(conn: psycopg.Connection, doc_id: str, codes: Sequence[str]) -> list[int]:
    return [
        page
        for (page,) in conn.execute(
            "SELECT DISTINCT page_number FROM page_flag WHERE document_id = %s"
            " AND code = ANY(%s) ORDER BY page_number",
            (doc_id, list(codes)),
        )
    ]


def _extract_document(
    conn: psycopg.Connection,
    settings: Settings,
    client: llm.ModelClient,
    run_id: int,
    doc_id: str,
    result: ExtractRun,
) -> None:
    """Extract one document; appends to `result` unless the model server stopped."""
    cfg = settings.extraction
    seconds: float | None = None
    try:
        index = _build_index(conn, doc_id)
        low_quality = _pages(conn, doc_id, ["low_recognition_quality"])
        unread = _pages(conn, doc_id, UNREAD_FLAGS)
        party = verify.PartyResult(found=False)
        if index.shown_end > cfg.max_shown_chars:
            results = verify.failed_results(
                f"текст слишком длинный: {index.shown_end} знаков при пределе "
                f"{cfg.max_shown_chars}"
            )
        else:
            messages = extraction_prompt.build_messages(index.text[: index.shown_end])
            started = time.monotonic()
            try:
                answer = client.extract(messages, extraction_prompt.ExtractionAnswer)
            except llm.AnswerFormError:
                seconds = time.monotonic() - started
                results = verify.failed_results(
                    f"ответ модели не по форме после {cfg.max_retries} повторов"
                )
            except llm.ModelRequestError as exc:
                seconds = time.monotonic() - started
                results = verify.failed_results(str(exc))
            except llm.ModelUnavailable as exc:
                result.stopped = Stopped(doc_id, str(exc))
                return
            else:
                seconds = time.monotonic() - started
                results = [
                    verify.check_field(spec, getattr(answer, spec.name), index)
                    for spec in PROTOTYPE_FIELDS
                ]
                party = verify.check_party(answer.other_party, index)
        state, reason = verify.document_state(
            results,
            party,
            low_quality_pages=low_quality,
            unread_pages=unread,
            shown_last_page=index.shown_last_page,
            document_id=doc_id,
        )
        store_document(conn, doc_id, results, state, reason, run_id, index.text_sha256)
    except Exception as exc:  # one document's failure must not stop the others
        reason = _error_reason(exc)
        results = verify.failed_results(reason)
        state = State.FAILED
        try:
            sha = conn.execute(
                "SELECT text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
            ).fetchone()
            store_document(conn, doc_id, results, state, reason, run_id, sha[0] if sha else "")
        except Exception:  # last resort: record only the stage state
            with conn.transaction():
                stages.set_state(conn, doc_id, Stage.EXTRACTION, State.FAILED, reason, run_id)
    result.documents.append(_summary(doc_id, _catalog_order(results), state, reason, seconds))


def extract_documents(
    conn: psycopg.Connection,
    settings: Settings,
    seqs: Sequence[int] | None,
    *,
    all_documents: bool = False,
    label: str | None = None,
) -> ExtractRun:
    """Extract the chosen documents (contracts/cli.md «docreader extract»); T017.

    `seqs` → those documents if available (others skipped with a reason);
    `all_documents` → every available document; neither → available documents whose
    `extraction` stage is `pending` or `failed`. Nothing to extract → `run_id` None.
    A stopped model server ends the run with `stopped` set; the caller exits with code 2.
    """
    if seqs and all_documents:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    chosen, skipped = _select(conn, seqs, all_documents)
    result = ExtractRun(skipped=skipped)
    if not chosen:
        return result
    client = llm.load_client(settings.extraction)
    served = client.check()
    run_settings = {
        "extraction": settings.settings_for_run()["extraction"],
        "prompt_sha256": extraction_prompt.prompt_sha256(),
        "served_model": served,
    }
    run_id = runs.start_run(conn, RunStage.EXTRACTION, run_settings, label)
    conn.execute(
        "UPDATE run SET model = %s, prompt_version = %s WHERE id = %s",
        (settings.extraction.model, extraction_prompt.PROMPT_VERSION, run_id),
    )
    result.run_id = run_id
    result.model = settings.extraction.model
    result.prompt_version = extraction_prompt.PROMPT_VERSION
    try:
        for doc_id in chosen:
            _extract_document(conn, settings, client, run_id, doc_id, result)
            if result.stopped:
                break
    except KeyboardInterrupt:
        # the current document is not written: its transaction() block rolled back
        result.interrupted = True
    runs.finish_run(conn, run_id)
    return result


_INSERT = (
    "INSERT INTO field_value (document_id, field, result, value_text, value_normalized,"
    " quote, quote_start, quote_end, clause_key, page, pages, reason, proposed_value,"
    " proposed_quote, proposed_clause, source_text_sha256, run_id)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


def store_document(
    conn: psycopg.Connection,
    doc_id: str,
    results: Sequence[FieldResult],
    state: State,
    reason: str | None,
    run_id: int,
    text_sha256: str,
) -> None:
    """Replace the six rows of `doc_id` and set its extraction state, all or nothing.

    Exactly one result per prototype field, otherwise ValueError before anything is
    written. A row the schema refuses (a CHECK of 0005_extraction.sql) rolls the whole
    document back: its previous rows and state stay (data-model.md «Состояние этапа»).
    """
    counts = Counter(r.field for r in results)
    if len(results) != len(FIELD_NAMES) or set(counts) != set(FIELD_NAMES):
        raise ValueError("нужно ровно шесть полей прототипа, по одному результату на поле")
    rows = [
        (
            doc_id, r.field, str(r.result), r.value_text, r.value_normalized, r.quote,
            r.quote_start, r.quote_end, r.clause_key, r.page,
            list(r.pages) if r.pages is not None else None, r.reason, r.proposed_value,
            r.proposed_quote, r.proposed_clause, text_sha256, run_id,
        )
        for r in results
    ]
    with conn.transaction():
        stages.lock(conn, doc_id, Stage.EXTRACTION)
        conn.execute("DELETE FROM field_value WHERE document_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(_INSERT, rows)
        stages.set_state(conn, doc_id, Stage.EXTRACTION, state, reason, run_id)
