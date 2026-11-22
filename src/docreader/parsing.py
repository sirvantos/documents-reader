"""The structure stage: `docreader parse` (feature 04; research R-1, R-6, R-7, R-9).

Reads the saved reading result of each document, runs the pure rule of
`docreader.structure` and replaces the document's `clause` rows in one transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

import psycopg

from docreader import runs, stages, structure
from docreader.config import Settings
from docreader.errors import UserError
from docreader.ids import format_document_id
from docreader.stages import RunStage, Stage, State

# Page flags of pages without text (research R-7): inside the main text they need a review.
UNREAD_FLAGS = ("scan_unread", "scan_no_text", "unreadable")
_MAX_ERROR_LEN = 300


@dataclass(frozen=True)
class ParsedDocument:
    document_id: str
    state: str
    reason: str | None
    sections: int
    clauses: int
    first_page: int | None
    last_page: int | None
    has_tail: bool


@dataclass(frozen=True)
class SkippedDocument:
    document_id: str
    reason: str


@dataclass
class ParseRun:
    """Result of one `parse` command (contracts/cli.md)."""

    run_id: int | None = None
    documents: list[ParsedDocument] = field(default_factory=list)
    skipped: list[SkippedDocument] = field(default_factory=list)
    interrupted: bool = False

    @property
    def totals(self) -> dict[str, int]:
        states = [d.state for d in self.documents]
        return {
            "parsed": sum(1 for s in states if s in (State.DONE, State.NEEDS_REVIEW)),
            "needs_review": states.count(State.NEEDS_REVIEW),
            "failed": states.count(State.FAILED),
            "skipped": len(self.skipped),
        }

    def to_json(self) -> dict:
        return {
            "run_id": self.run_id,
            "documents": [asdict(d) for d in self.documents],
            "skipped": [asdict(s) for s in self.skipped],
            "totals": self.totals,
            "interrupted": self.interrupted,
        }


_AVAILABLE = (
    "SELECT d.id, d.seq FROM document d"
    " JOIN stage_status r ON r.document_id = d.id AND r.stage = %(reading)s"
    " JOIN document_text t ON t.document_id = d.id"
    " WHERE r.state = ANY(%(read_states)s) AND t.read_pages > 0"
)


def _select(
    conn: psycopg.Connection, seqs: Sequence[int] | None, all_documents: bool
) -> tuple[list[str], list[SkippedDocument]]:
    """Documents to parse, in order, and the named ones that are not available (R-9)."""
    params = {
        "reading": Stage.READING,
        "read_states": [State.DONE, State.NEEDS_REVIEW],
        "structure": Stage.STRUCTURE,
        "parse_states": [State.PENDING, State.FAILED],
    }
    if seqs:
        known = {
            seq: doc_id
            for doc_id, seq in conn.execute(
                "SELECT id, seq FROM document WHERE seq = ANY(%s)", (list(seqs),)
            )
        }
        missing = [seq for seq in seqs if seq not in known]
        if missing:
            raise UserError(
                f"Документ {format_document_id(missing[0])} не найден — "
                "список документов: docreader list"
            )
        available = {
            doc_id
            for doc_id, _ in conn.execute(_AVAILABLE + " AND d.seq = ANY(%(seqs)s)",
                                          {**params, "seqs": list(seqs)})
        }
        chosen, skipped = [], []
        for seq in dict.fromkeys(seqs):
            doc_id = known[seq]
            if doc_id in available:
                chosen.append(doc_id)
            else:
                reason = f"не прочитан — выполните docreader read {doc_id}"
                skipped.append(SkippedDocument(doc_id, reason))
        return chosen, skipped
    if all_documents:
        return [doc_id for doc_id, _ in conn.execute(_AVAILABLE + " ORDER BY d.seq", params)], []
    query = (
        _AVAILABLE + " AND EXISTS (SELECT 1 FROM stage_status s WHERE s.document_id = d.id"
        " AND s.stage = %(structure)s AND s.state = ANY(%(parse_states)s)) ORDER BY d.seq"
    )
    return [doc_id for doc_id, _ in conn.execute(query, params)], []


@dataclass(frozen=True)
class _Input:
    text: str
    text_sha256: str
    lines: list[structure.Line]
    unread_pages: list[int]


def _load(conn: psycopg.Connection, doc_id: str) -> _Input:
    """Lines of the cleaned text with table marks and the unread pages (R-1)."""
    text, sha = conn.execute(
        "SELECT text, text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone() or ("", "")
    table_lines = {
        (page, i)
        for page, lines in conn.execute(
            "SELECT page_number, lines FROM page_text WHERE document_id = %s", (doc_id,)
        )
        for i, line in enumerate(lines)
        if line.get("table") is not None
    }
    lines = [
        structure.Line(
            start=start,
            end=end,
            page=page,
            text=text[start:end],
            table=(page, index) in table_lines,
            line_start=start == 0 or text[start - 1] == "\n",
        )
        for start, end, page, index in conn.execute(
            "SELECT start, end_, page_number, line_index FROM text_span"
            " WHERE document_id = %s ORDER BY start",
            (doc_id,),
        )
    ]
    unread = [
        page
        for (page,) in conn.execute(
            "SELECT DISTINCT page_number FROM page_flag WHERE document_id = %s"
            " AND code = ANY(%s) ORDER BY page_number",
            (doc_id, list(UNREAD_FLAGS)),
        )
    ]
    return _Input(text, sha, lines, unread)


def _write(
    conn: psycopg.Connection,
    run_id: int,
    doc_id: str,
    data: _Input,
    result: structure.ParseResult,
) -> State:
    """Replace the document's records and set its stage state in one transaction."""
    state = State.NEEDS_REVIEW if result.reason else State.DONE
    with conn.transaction():
        stages.lock(conn, doc_id, Stage.STRUCTURE)
        conn.execute("DELETE FROM clause WHERE document_id = %s", (doc_id,))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO clause (document_id, key, ordinal, kind, number_printed, number,"
                " depth, parent_key, title, section_number, section_title, start, end_,"
                " first_page, last_page, source_text_sha256, run_id)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        doc_id, r.key, r.ordinal, r.kind, r.number_printed,
                        list(r.number) if r.number is not None else None, r.depth,
                        r.parent_key, r.title, r.section_number, r.section_title,
                        r.start, r.end, r.first_page, r.last_page, data.text_sha256, run_id,
                    )
                    for r in result.records  # in ordinal order: parents before children
                ],
            )
        stages.set_state(conn, doc_id, Stage.STRUCTURE, state, result.reason, run_id)
    return state


def _error_reason(exc: Exception) -> str:
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    text = f"ошибка разбора: {type(exc).__name__}" + (f": {detail}" if detail else "")
    return text[:_MAX_ERROR_LEN]


def _parse_document(
    conn: psycopg.Connection, settings: Settings, run_id: int, doc_id: str
) -> ParsedDocument:
    try:
        data = _load(conn, doc_id)
        result = structure.parse_lines(
            data.lines, len(data.text), settings.structure, data.unread_pages
        )
        state = _write(conn, run_id, doc_id, data, result)
    except Exception as exc:  # one document's failure must not stop the others
        reason = _error_reason(exc)
        with conn.transaction():
            stages.set_state(conn, doc_id, Stage.STRUCTURE, State.FAILED, reason, run_id)
        return ParsedDocument(doc_id, State.FAILED, reason, 0, 0, None, None, False)
    records = result.records
    return ParsedDocument(
        document_id=doc_id,
        state=state,
        reason=result.reason,
        sections=sum(1 for r in records if r.kind == "section"),
        clauses=sum(1 for r in records if r.kind == "clause"),
        first_page=min((r.first_page for r in records), default=None),
        last_page=max((r.last_page for r in records), default=None),
        has_tail=any(r.kind == "tail" for r in records),
    )


def parse_documents(
    conn: psycopg.Connection,
    settings: Settings,
    seqs: Sequence[int] | None,
    *,
    all_documents: bool = False,
    label: str | None = None,
) -> ParseRun:
    """Parse the chosen documents (contracts/cli.md «docreader parse»).

    `seqs` → those documents if available after reading (others are skipped with a
    reason); `all_documents` → every available document; neither → available documents
    whose `structure` stage is `pending` or `failed`. Nothing to parse → `run_id` None.
    """
    if seqs and all_documents:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    chosen, skipped = _select(conn, seqs, all_documents)
    result = ParseRun(skipped=skipped)
    if not chosen:
        return result
    run_settings = {"structure": settings.settings_for_run()["structure"]}
    run_id = runs.start_run(conn, RunStage.STRUCTURE, run_settings, label)
    result.run_id = run_id
    try:
        for doc_id in chosen:
            result.documents.append(_parse_document(conn, settings, run_id, doc_id))
    except KeyboardInterrupt:
        # the current document is not written: its transaction() block rolled back
        result.interrupted = True
    runs.finish_run(conn, run_id)
    return result
