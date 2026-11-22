"""Integration tests for `docreader fields ID` (feature 05, US4; task T021).

After `extract` with a `ScriptedModel`. Written by the main session; the implementer must
not edit, weaken, skip or delete these tests (CLAUDE.md «Model routing»). The output of
`fields` contains contract text — here it is synthetic.
"""

from __future__ import annotations

import json

import pytest

from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import (
    BASE_ANSWERS,
    NOT_FOUND,
    add_variants,
    answer,
    field,
)
from tests.integration.test_extract import flag

WRONG = field("1 500 000 рублей", BASE_ANSWERS["amount_without_vat"][1], "2.1")
JSON_KEYS = {
    "field", "label", "result", "value_text", "value_normalized", "quote", "quote_start",
    "quote_end", "clause_id", "page", "pages", "low_quality", "reason", "proposed_value",
    "proposed_quote", "proposed_clause",
}


@pytest.fixture
def extracted(cli, tmp_path, use_model) -> tuple[str, str]:
    """`base` extracted with one rejected and one not-found field; `missing` not extracted."""
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(answer(amount_without_vat=WRONG, amount_with_vat=NOT_FOUND)))
    result = cli("extract", a)
    assert result.exit_code == 0, result.stderr
    return a, b


def fields_json(cli, doc: str) -> dict:
    result = cli("fields", doc, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_json_shape(cli, db, extracted) -> None:
    doc, _ = extracted
    report = fields_json(cli, doc)
    run_id = db.execute("SELECT max(id) FROM run WHERE stage = 'extraction'").fetchone()[0]
    assert report["document_id"] == doc
    assert (report["state"], report["run_id"]) == ("needs_review", run_id)
    assert report["reason"] == "отклонено: цена без НДС — значение не подтверждено цитатой"
    assert (report["model"], report["prompt_version"]) == ("qwen3.6-27b-4bit", "05.1")
    names = [f["field"] for f in report["fields"]]
    assert names == [
        "contract_number", "customer_name_short", "contractor_name_short",
        "amount_without_vat", "amount_with_vat", "contract_end_date",
    ]
    assert all(set(f) == JSON_KEYS for f in report["fields"])
    by = {f["field"]: f for f in report["fields"]}
    number = by["contract_number"]
    assert (number["label"], number["result"]) == ("номер договора", "found")
    assert (number["value_normalized"], number["value_text"]) == ("ДП-17/2026", "ДП-17/2026")
    assert number["clause_id"] == f"{doc}/преамбула"
    assert (number["page"], number["pages"], number["low_quality"]) == (1, [1], False)
    assert number["quote"] == "ДОГОВОР ПОДРЯДА\n№ ДП-17/2026"
    rejected = by["amount_without_vat"]
    assert (rejected["result"], rejected["reason"]) == (
        "rejected", "значение не подтверждено цитатой"
    )
    assert rejected["proposed_value"] == "1 500 000 рублей"
    assert rejected["proposed_clause"] == "2.1"
    assert rejected["clause_id"] is None and rejected["quote"] is None
    assert by["amount_with_vat"]["result"] == "not_found"
    assert by["contract_end_date"]["clause_id"] == f"{doc}/4.1"


def test_text_view(cli, db, extracted) -> None:
    doc, _ = extracted
    result = cli("fields", doc)
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    run_id = db.execute("SELECT max(id) FROM run WHERE stage = 'extraction'").fetchone()[0]
    first = out.splitlines()[0]
    assert first.startswith(f"{doc} — извлечение от ")
    assert f"(запуск {run_id}, модель qwen3.6-27b-4bit, подсказка 05.1)" in first
    assert first.endswith("требует просмотра")
    assert "отклонено: цена без НДС — значение не подтверждено цитатой" in out
    assert "номер договора" in out and "найдено" in out
    assert "ДП-17/2026" in out
    assert "«ДОГОВОР ПОДРЯДА № ДП-17/2026»" in out  # the quote on one line
    assert f"{doc}/преамбула, стр. 1" in out
    assert f"{doc}/4.1, стр. 2" in out
    assert "цена без НДС" in out and "отклонено" in out
    assert "модель: «1 500 000 рублей», пункт 2.1" in out
    assert "цена с НДС" in out and "не найдено" in out
    # catalog order of the six labels
    labels = ["номер договора", "заказчик", "подрядчик", "цена без НДС", "цена с НДС",
              "дата окончания"]
    positions = [out.index(f"\n{label}") for label in labels]
    assert positions == sorted(positions)


def test_low_quality_mark(cli, db, extracted) -> None:
    doc, _ = extracted
    flag(db, doc, 2, "low_recognition_quality")
    by = {f["field"]: f for f in fields_json(cli, doc)["fields"]}
    assert by["contract_end_date"]["low_quality"] is True
    assert by["contract_number"]["low_quality"] is False
    assert "[низкое качество распознавания]" in cli("fields", doc).stdout


def test_unknown_document(cli, extracted) -> None:
    result = cli("fields", "D-0099")
    assert result.exit_code == 1
    assert "D-0099" in result.stderr


def test_not_extracted(cli, extracted) -> None:
    _, other = extracted
    result = cli("fields", other)
    assert result.exit_code == 1
    assert f"Поля {other} не извлекались — выполните docreader extract {other}" in result.stderr


def test_stale_after_the_text_changed(cli, db, extracted) -> None:
    doc, _ = extracted
    db.execute(
        "UPDATE document_text SET text_sha256 = %s WHERE document_id = %s", ("c" * 64, doc)
    )
    result = cli("fields", doc)
    assert result.exit_code == 1
    assert f"Поля устарели: текст изменён — выполните docreader extract {doc}" in result.stderr


def test_reparse_of_the_same_text_keeps_the_view(cli, extracted) -> None:
    doc, _ = extracted
    before = cli("fields", doc, "--json").stdout
    assert cli("parse", doc).exit_code == 0
    after = cli("fields", doc, "--json").stdout
    assert json.loads(before)["fields"] == json.loads(after)["fields"]


def test_clause_gone_from_the_parse(cli, db, extracted) -> None:
    doc, _ = extracted
    db.execute(
        "UPDATE clause SET key = 'преамбула-старая' WHERE document_id = %s AND key = 'преамбула'",
        (doc,),
    )
    by = {f["field"]: f for f in fields_json(cli, doc)["fields"]}
    assert by["contract_number"]["clause_id"] is None
    out = cli("fields", doc).stdout
    assert f"пункт не найден в разборе — выполните docreader extract {doc}" in out


def test_clause_no_longer_holding_the_quote(cli, db, extracted) -> None:
    doc, _ = extracted
    db.execute(
        "UPDATE clause SET start = end_ - 1 WHERE document_id = %s AND key = '4.1'", (doc,)
    )
    by = {f["field"]: f for f in fields_json(cli, doc)["fields"]}
    assert by["contract_end_date"]["clause_id"] is None
    assert by["contract_number"]["clause_id"] == f"{doc}/преамбула"
    assert "пункт не найден в разборе" in cli("fields", doc).stdout
