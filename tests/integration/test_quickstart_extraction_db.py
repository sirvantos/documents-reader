"""scripts/quickstart_extraction.py on a synthetic database (feature 05; T028).

`collect(conn)` reads the database after `extract`; `render(report)` prints only counts,
shares, document ids and reason kinds — no value, quote or name of the contracts. Written
by the main session; the implementer must not edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import (
    BASE_ANSWERS,
    add_variants,
    answer,
    field,
    missing_answer,
)

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_extraction_db", ROOT / "scripts" / "quickstart_extraction.py"
)
assert _spec is not None and _spec.loader is not None
qs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qs)


def test_collect_and_render(cli, db, tmp_path, use_model) -> None:
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    wrong = field("1 500 000 рублей", BASE_ANSWERS["amount_without_vat"][1], "2.1")
    use_model(ScriptedModel(answer(amount_without_vat=wrong), missing_answer()))
    assert cli("extract").exit_code == 0

    report = qs.collect(db)
    assert report.states == {"done": 1, "needs_review": 1}
    assert report.fields["amount_without_vat"] == {
        "found": 1, "not_found": 0, "rejected": 1, "failed": 0
    }
    assert report.fields["amount_with_vat"]["not_found"] == 1
    assert report.rejection_kinds == {"значение не подтверждено цитатой": 1}
    assert (report.found_total, report.found_rechecked) == (9, 9)
    assert report.clause_mismatch == 0
    assert report.party_marks == 0
    assert report.review == [a, b]  # two text-layer contracts, no scans

    lines = qs.render(report)
    out = "\n".join(lines)
    assert "SC-001" in out and "9 из 9" in out
    for value, quote, _ in BASE_ANSWERS.values():
        assert value not in out and quote not in out
    assert "ДП-17/2026" not in out and "Альфа" not in out and ".pdf" not in out


def test_a_contract_with_some_recognized_pages_keeps_its_text_layer(
    cli, db, tmp_path, use_model
) -> None:
    # A mixed contract (text-layer pages plus a few recognized scans) is one of the
    # text-layer contracts of Б5, not a scan (spec, clarification Q6).
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(answer(), missing_answer()))
    assert cli("extract").exit_code == 0
    db.execute(
        "UPDATE page SET kind = 'scan' WHERE document_id = %s AND page_number = 1", (a,)
    )
    db.execute(
        "UPDATE page_text SET source = 'recognized' WHERE document_id = %s AND page_number = 1",
        (a,),
    )
    report = qs.collect(db)
    assert report.review == [a, b]  # both text-layer contracts, no scans


def test_clause_mismatch_is_counted(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "base")
    use_model(ScriptedModel(answer()))
    assert cli("extract").exit_code == 0
    db.execute(
        "UPDATE clause SET start = end_ - 1 WHERE document_id = %s AND key = '4.1'", (doc,)
    )
    report = qs.collect(db)
    assert report.clause_mismatch == 1
    assert report.found_rechecked == 6  # the quote itself is still in the text
