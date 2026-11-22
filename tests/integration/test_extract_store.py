"""The write of `field_value` (feature 05, data-model.md «Состояние этапа»; task T037).

Critical part (plan.md «Критические части»): one transaction per document — lock the
stage, delete the old six rows, insert six new ones, set the state. No model here: the
results are built by hand.
"""

from __future__ import annotations

import psycopg
import pytest

from docreader import runs
from docreader.extraction import store_document
from docreader.fields import FIELD_NAMES, Result
from docreader.stages import RunStage, Stage, State
from docreader.verify import FieldResult
from tests.integration.extraction_fixtures import add_variants, field_rows, text_sha
from tests.integration.test_read import stage


def _found(name: str, value: str = "v") -> FieldResult:
    return FieldResult(
        name, Result.FOUND, value_text=value, value_normalized=value, quote=f"цитата {value}",
        quote_start=0, quote_end=5, clause_key="преамбула", page=1, pages=(1,),
        proposed_value=value, proposed_clause="преамбула",
    )


def _six(value: str = "v") -> list[FieldResult]:
    return [_found(name, value) for name in FIELD_NAMES]


@pytest.fixture
def docs(cli, tmp_path) -> list[str]:
    return add_variants(cli, tmp_path / "in", "base", "missing")


def _run(db) -> int:
    return runs.start_run(db, RunStage.EXTRACTION, {})


def test_six_rows_and_the_state(db, docs) -> None:
    doc = docs[0]
    run_id = _run(db)
    sha = text_sha(db, doc)
    store_document(db, doc, _six(), State.DONE, None, run_id, sha)
    rows = field_rows(db, doc)
    assert sorted(rows) == sorted(FIELD_NAMES)
    assert {r["run_id"] for r in rows.values()} == {run_id}
    assert {r["source_text_sha256"] for r in rows.values()} == {sha}
    assert rows["contract_number"]["pages"] == [1]
    assert stage(db, doc, "extraction") == ("done", None, run_id)


def test_needs_review_reason_is_stored(db, docs) -> None:
    doc = docs[0]
    results = _six()
    results[3] = FieldResult(
        "amount_without_vat", Result.REJECTED, reason="цитата не найдена",
        proposed_value="1 рубль", proposed_quote="нет", proposed_clause="2.1",
    )
    run_id = _run(db)
    store_document(db, doc, results, State.NEEDS_REVIEW, "отклонено", run_id, text_sha(db, doc))
    rows = field_rows(db, doc)
    assert rows["amount_without_vat"]["result"] == "rejected"
    assert rows["amount_without_vat"]["proposed_quote"] == "нет"
    assert stage(db, doc, "extraction") == ("needs_review", "отклонено", run_id)


def test_second_call_replaces_the_rows(db, docs) -> None:
    doc = docs[0]
    first, second = _run(db), _run(db)
    store_document(db, doc, _six("a"), State.DONE, None, first, text_sha(db, doc))
    store_document(db, doc, _six("b"), State.DONE, None, second, text_sha(db, doc))
    rows = field_rows(db, doc)
    assert len(rows) == 6
    assert {r["value_text"] for r in rows.values()} == {"b"}
    assert {r["run_id"] for r in rows.values()} == {second}


def test_failed_rows_are_stored(db, docs) -> None:
    doc = docs[0]
    run_id = _run(db)
    failed = [FieldResult(n, Result.FAILED, reason="не по форме") for n in FIELD_NAMES]
    store_document(db, doc, failed, State.FAILED, "не по форме", run_id, text_sha(db, doc))
    assert {r["result"] for r in field_rows(db, doc).values()} == {"failed"}
    assert stage(db, doc, "extraction")[:2] == ("failed", "не по форме")


@pytest.mark.parametrize(
    "results",
    [
        _six()[:5],  # a field is missing
        [*_six(), _found("contract_number")],  # a field twice
        [*_six()[:5], _found("contract_number")],  # six rows, one field twice
    ],
)
def test_not_one_result_per_field_is_refused(db, docs, results) -> None:
    doc = docs[0]
    run_id = _run(db)
    store_document(db, doc, _six("old"), State.DONE, None, run_id, text_sha(db, doc))
    with pytest.raises(ValueError, match="шесть полей"):
        store_document(db, doc, results, State.DONE, None, _run(db), text_sha(db, doc))
    assert {r["value_text"] for r in field_rows(db, doc).values()} == {"old"}


def test_check_violation_rolls_the_whole_document_back(db, docs) -> None:
    doc = docs[0]
    first = _run(db)
    store_document(db, doc, _six("old"), State.DONE, None, first, text_sha(db, doc))
    bad = _six("new")
    bad[2] = FieldResult("contractor_name_short", Result.FOUND, value_text="x")  # no quote
    with pytest.raises(psycopg.errors.CheckViolation):
        store_document(db, doc, bad, State.NEEDS_REVIEW, "x", _run(db), text_sha(db, doc))
    rows = field_rows(db, doc)
    assert {r["value_text"] for r in rows.values()} == {"old"}
    assert stage(db, doc, "extraction") == ("done", None, first)


def test_other_documents_are_untouched(db, docs) -> None:
    a, b = docs
    run_id = _run(db)
    store_document(db, b, _six("b"), State.DONE, None, run_id, text_sha(db, b))
    store_document(db, a, _six("a"), State.DONE, None, run_id, text_sha(db, a))
    store_document(db, a, _six("a2"), State.DONE, None, _run(db), text_sha(db, a))
    assert {r["value_text"] for r in field_rows(db, b).values()} == {"b"}
    assert stage(db, b, Stage.EXTRACTION)[0] == "done"
