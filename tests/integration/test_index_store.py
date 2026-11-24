"""The write of passages and vectors, the choice of documents and staleness (feature 07,
research R-7, R-8; task T015).

Documents are added, read and parsed through the CLI; the rows are built by hand (no
model). Critical part (plan.md «Критические части»), written by the main session; the
implementer must not edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

from functools import partial

import psycopg
import pytest

from docreader.errors import UserError
from docreader.indexing import (
    PassageRow,
    SkippedDocument,
    VectorRow,
    passages_current,
    select_documents,
    store_document,
)
from docreader.stages import Stage, State
from tests.integration.test_read import add_files, stage
from tests.synthetic import make_pdfs as mk


def _run(db) -> int:
    return db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('indexing', 'test', '{}') "
        "RETURNING id"
    ).fetchone()[0]


def _doc_info(db, doc: str) -> tuple[str, int]:
    sha = db.execute(
        "SELECT text_sha256 FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()[0]
    srun = db.execute(
        "SELECT DISTINCT run_id FROM clause WHERE document_id = %s", (doc,)
    ).fetchone()[0]
    return sha, srun


def _rows(db, doc: str, *, keys=("1.1", "2.1"), dims=2) -> tuple[list, list]:
    sha, srun = _doc_info(db, doc)
    passages = [
        PassageRow(key, i, "main", 10 * i, 10 * i + 5, 1, 1, f"{doc} · пункт {key}",
                   f"пункт {key}", sha, srun)
        for i, key in enumerate(keys)
    ]
    vectors = [VectorRow(key, "bge-m3", [1.0] + [0.0] * (dims - 1), 20, False)
               for key in keys]
    return passages, vectors


@pytest.fixture
def docs(cli, tmp_path) -> list[str]:
    makers = [mk.make_passage_contract, partial(mk.make_extraction_contract, variant="base")]
    ids = add_files(cli, tmp_path / "in", makers)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    return ids


def _count(db, table: str, doc: str) -> int:
    return db.execute(
        f"SELECT count(*) FROM {table} WHERE document_id = %s", (doc,)
    ).fetchone()[0]


# --- store_document ----------------------------------------------------------------------


def test_rows_state_and_reason_are_written(db, docs) -> None:
    doc = docs[0]
    run_id = _run(db)
    passages, vectors = _rows(db, doc)
    store_document(db, doc, passages, vectors, State.NEEDS_REVIEW, "нет отрывков", run_id)
    assert _count(db, "passage", doc) == 2
    assert _count(db, "passage_vector", doc) == 2
    assert stage(db, doc, "indexing")[:2] == ("needs_review", "нет отрывков")
    row = db.execute(
        "SELECT label, lemmas, p.run_id, vector_dims(v.embedding) FROM passage p"
        " JOIN passage_vector v USING (document_id, clause_key)"
        " WHERE p.document_id = %s AND clause_key = '2.1'",
        (doc,),
    ).fetchone()
    assert row == (f"{doc} · пункт 2.1", "пункт 2.1", run_id, 2)


def test_second_call_replaces(db, docs) -> None:
    doc = docs[0]
    passages, vectors = _rows(db, doc)
    store_document(db, doc, passages, vectors, State.DONE, None, _run(db))
    passages, vectors = _rows(db, doc, keys=("3.1",))
    store_document(db, doc, passages, vectors, State.DONE, None, _run(db))
    keys = [r[0] for r in db.execute(
        "SELECT clause_key FROM passage WHERE document_id = %s", (doc,))]
    assert keys == ["3.1"]
    assert _count(db, "passage_vector", doc) == 1
    assert stage(db, doc, "indexing")[:2] == ("done", None)


@pytest.mark.parametrize("bad", ["unknown_passage", "wrong_dims"])
def test_a_bad_row_rolls_the_whole_call_back(db, docs, bad: str) -> None:
    doc, other = docs
    passages, vectors = _rows(db, doc)
    store_document(db, doc, passages, vectors, State.DONE, None, _run(db))
    o_passages, o_vectors = _rows(db, other)
    store_document(db, other, o_passages, o_vectors, State.DONE, None, _run(db))

    new_passages, new_vectors = _rows(db, doc, keys=("3.1", "3.2"))
    if bad == "unknown_passage":
        new_vectors.append(VectorRow("9.9", "bge-m3", [1.0, 0.0], 20, False))
    else:
        new_vectors[0] = VectorRow("3.1", "bge-m3", [1.0, 0.0, 0.0], 20, False)
        new_vectors[1] = VectorRow("3.2", "bge-m3", [1.0, 0.0], 20, False)
    with pytest.raises((psycopg.errors.IntegrityError, psycopg.errors.DataException)):
        store_document(db, doc, new_passages, new_vectors, State.FAILED, "x", _run(db))
    keys = sorted(r[0] for r in db.execute(
        "SELECT clause_key FROM passage WHERE document_id = %s", (doc,)))
    assert keys == ["1.1", "2.1"]
    assert stage(db, doc, "indexing")[:2] == ("done", None)
    assert _count(db, "passage", other) == 2 and _count(db, "passage_vector", other) == 2


# --- select_documents ----------------------------------------------------------------------


def _seq(doc: str) -> int:
    return int(doc.split("-")[1])


def test_without_arguments_pending_and_failed_only(db, docs) -> None:
    first, second = docs
    assert select_documents(db, None, False) == ([first, second], [])
    passages, vectors = _rows(db, first)
    store_document(db, first, passages, vectors, State.DONE, None, _run(db))
    assert select_documents(db, None, False) == ([second], [])
    db.execute("UPDATE stage_status SET state = 'failed', reason = 'x' WHERE document_id = %s"
               " AND stage = 'indexing'", (first,))
    assert select_documents(db, None, False) == ([first, second], [])


def test_needs_review_is_not_taken_again_without_arguments(db, docs) -> None:
    first, second = docs
    passages, vectors = _rows(db, first)
    store_document(db, first, passages, vectors, State.NEEDS_REVIEW, "нет отрывков", _run(db))
    assert select_documents(db, None, False) == ([second], [])


def test_all_takes_every_available_document(db, docs) -> None:
    first, _ = docs
    passages, vectors = _rows(db, first)
    store_document(db, first, passages, vectors, State.DONE, None, _run(db))
    assert select_documents(db, None, True) == (docs, [])


def test_a_second_parse_makes_the_document_due_again(cli, db, docs) -> None:
    first, _ = docs
    for doc in docs:
        passages, vectors = _rows(db, doc)
        store_document(db, doc, passages, vectors, State.DONE, None, _run(db))
    assert select_documents(db, None, False) == ([], [])
    assert cli("parse", first).exit_code == 0
    assert select_documents(db, None, False) == ([first], [])


def test_named_documents_and_their_skip_reasons(cli, db, docs, tmp_path) -> None:
    first, second = docs
    (third,) = add_files(cli, tmp_path / "more", [mk.make_structured_contract])
    assert cli("read", third).exit_code == 0  # read, not parsed
    chosen, skipped = select_documents(db, [_seq(second), _seq(third), _seq(first)], False)
    assert chosen == [second, first]
    assert skipped == [SkippedDocument(third, f"не разобран — выполните docreader parse {third}")]

    db.execute("UPDATE document_text SET text_sha256 = %s WHERE document_id = %s",
               ("b" * 64, first))
    chosen, skipped = select_documents(db, [_seq(first)], False)
    assert chosen == []
    assert skipped == [
        SkippedDocument(first, f"разбор устарел — выполните docreader parse {first}")
    ]


def test_unknown_document_is_a_user_error(db, docs) -> None:
    with pytest.raises(UserError, match="D-0099"):
        select_documents(db, [99], False)


# --- passages_current -----------------------------------------------------------------------


def test_passages_current(cli, db, docs) -> None:
    first, second = docs
    assert passages_current(db, first) is False  # no passages yet
    passages, vectors = _rows(db, first)
    store_document(db, first, passages, vectors, State.DONE, None, _run(db))
    assert passages_current(db, first) is True

    assert cli("parse", first).exit_code == 0  # a second parse: another structure run
    assert passages_current(db, first) is False

    passages, vectors = _rows(db, second)
    store_document(db, second, passages, vectors, State.DONE, None, _run(db))
    db.execute("UPDATE document_text SET text_sha256 = %s WHERE document_id = %s",
               ("c" * 64, second))
    assert passages_current(db, second) is False


def test_stage_is_indexing() -> None:
    assert Stage.INDEXING.value == "indexing"
