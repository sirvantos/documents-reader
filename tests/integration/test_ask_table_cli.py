"""`docreader ask-table` on the nine checked synthetic contracts (feature 10, T012;
outcomes refused/clarify/unsupported/rejected/failed — T016). contracts/cli.md, R-1, R-10.

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).

The model is `ScriptedModel` with `TableReply` answers (`table_fixtures.reply`); the
expected contracts are computed here from `EXPECTED_CELLS`, not by the code under test.
`--json` is `TableAnswer.to_json()`: {"question", "outcome", "reason", "other", "retried",
"today", "seconds", "provenance": {"code_version", "llm_model", "prompt_version",
"prompt_sha256", "checks_version"}, "result": {"query": {"action", "field", "op", "value",
"value_to", "period", "side"}, "count", "considered", "total", "include_unreviewed",
"matched_names", "rows": [{"document_id", "unreviewed", "cells": {field: {"state",
"value", "clause_id", "flags"}}}], "excluded": {state: [ids]}}}; amounts as strings
(`str(Decimal)`), `result` null when no query ran.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest

from docreader import llm, table_answer
from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import add_check_contracts
from tests.integration.table_fixtures import (
    ALPHA,
    EXPECTED_CELLS,
    FIELDS,
    add_checked_contracts,
    reply,
)
from tests.table_guard import run_clean

REAL_LOAD_CLIENT = llm.load_client  # before any test installs a fake
TABLES = ("document", "field_value", "field_status", "field_decision", "run")


@pytest.fixture
def ids(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return add_checked_contracts(cli, use_model, tmp_path / "in")


def _counts(db) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


def _expected(ids: dict[str, str], field: str, meets: Callable[[str], bool]) -> tuple[
        list[str], int]:
    """Ids of contracts whose effective value of `field` meets the condition; considered."""
    hits, considered = [], 0
    for name, doc in ids.items():
        state, value, _ = EXPECTED_CELLS[name][field]
        if state != "effective" or value is None:
            continue
        considered += 1
        if meets(value):
            hits.append(doc)
    return sorted(hits), considered


CASES = [
    ("Какой договор с номером К-21/2026?", "contract_number", "eq", "№ К-21/2026",
     lambda v: v == "К-21/2026"),
    ("Сколько договоров у заказчика Альфа?", "customer_name_short", "eq", "Альфа",
     lambda v: v == ALPHA),
    ("Какие договоры с подрядчиком ООО «Бета»?", "contractor_name_short", "eq", "ООО «Бета»",
     lambda v: v == 'ООО "Бета"'),
    ("Какие договоры дороже 950 000 без НДС?", "amount_without_vat", "gt", "950000",
     lambda v: Decimal(v) > 950000),
    ("Какие договоры не дешевле 1 200 000 с НДС?", "amount_with_vat", "ge", "1200000",
     lambda v: Decimal(v) >= 1200000),
    ("Какие договоры заканчиваются до 2030 года?", "contract_end_date", "before", "2030-01-01",
     lambda v: v < "2030-01-01"),
]


def _ask_json(cli, db, question: str, *extra: str) -> dict:  # type: ignore[no-untyped-def]
    result = run_clean(cli, db, question, "--json", *extra)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("action", ["list", "count"])
@pytest.mark.parametrize(("question", "field", "op", "value", "meets"), CASES,
                         ids=[c[1] for c in CASES])
def test_each_field_both_actions(  # type: ignore[no-untyped-def]
    cli, db, use_model, ids, action, question, field, op, value, meets
) -> None:
    expected, considered = _expected(ids, field, meets)
    assert expected, "every case must find some contract"
    model = use_model(ScriptedModel(reply(action=action, field=field, op=op, value=value)))
    data = _ask_json(cli, db, question)
    assert data["outcome"] == "answered" and data["retried"] is False
    assert len(model.requests) == 1
    res = data["result"]
    assert res["query"]["action"] == action and res["query"]["field"] == field
    assert [r["document_id"] for r in res["rows"]] == expected
    assert res["count"] == len(expected)
    assert res["considered"] == considered and res["total"] == len(ids)

    use_model(ScriptedModel(reply(action=action, field=field, op=op, value=value)))
    text = run_clean(cli, db, question)
    assert text.exit_code == 0, text.stderr
    first = text.stdout.splitlines()[0]
    assert first.startswith("По таблице — ответ: ")
    assert f"; учтено {considered} из {len(ids)}, не учтено {len(ids) - considered}; " in first
    heading = "Договоры" if action == "list" else "Из каких договоров"
    assert f"{heading} ({len(expected)}):" in text.stdout
    for doc in expected:
        assert f"  {doc}   " in text.stdout


def test_first_line_of_an_amount_question(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(action="list", field="amount_with_vat", op="ge",
                                  value="1200000")))
    first = run_clean(cli, db, "Какие договоры не дешевле 1 200 000 с НДС?").stdout.splitlines()[0]
    assert first.startswith("По таблице — ответ: 4 договора; учтено 5 из 9, не учтено 4; "
                            "повторов 0; ")
    assert first.endswith(" с")


def test_matched_spellings_and_condition_shown(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(action="list", field="customer_name_short", op="eq",
                                  value="альфа")))
    out = run_clean(cli, db, "Какие договоры у заказчика Альфа?").stdout
    assert "Условие: заказчик — альфа" in out
    assert 'Совпали наименования: ООО "Альфа"' in out


def test_party_side_chosen_by_the_table(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    # «Альфа» is a counted customer everywhere; as contractor only in check-same, unreviewed
    use_model(ScriptedModel(reply(action="list", field="party", op="eq", value="Альфа")))
    data = _ask_json(cli, db, "Какие договоры с Альфой?")
    assert data["result"]["query"]["side"] == "customer"
    assert data["result"]["query"]["field"] == "customer_name_short"
    expected = sorted(doc for name, doc in ids.items() if name != "check-same")
    assert [r["document_id"] for r in data["result"]["rows"]] == expected
    use_model(ScriptedModel(reply(action="list", field="party", op="eq", value="Альфа")))
    out = run_clean(cli, db, "Какие договоры с Альфой?").stdout
    assert "Условие: заказчик — Альфа (сторона выбрана по таблице)" in out


def test_zero_contracts(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(action="list", field="contractor_name_short", op="eq",
                                  value="Гамма")))
    result = run_clean(cli, db, "Какие договоры с подрядчиком Гамма?")
    assert result.exit_code == 0
    assert result.stdout.startswith("По таблице — ответ: 0 договоров; ")
    assert "Условие: подрядчик — Гамма" in result.stdout
    assert "Таких договоров нет." in result.stdout


def test_same_question_twice_gives_the_same_list(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    answers = [reply(action="list", field="amount_with_vat", op="gt", value="0")] * 2
    use_model(ScriptedModel(*answers))
    first = _ask_json(cli, db, "Какие договоры дороже нуля?")
    second = _ask_json(cli, db, "Какие договоры дороже нуля?")
    assert first["result"] == second["result"]
    use_model(ScriptedModel(*answers))
    a = run_clean(cli, db, "Какие договоры дороже нуля?").stdout.splitlines()[1:]
    b = run_clean(cli, db, "Какие договоры дороже нуля?").stdout.splitlines()[1:]
    assert a == b


def test_json_holds_the_full_list_and_every_key(cli, db, use_model, ids, data_dir) -> None:  # type: ignore[no-untyped-def]
    (data_dir / "settings.toml").write_text("[table]\nlist_rows = 2\n", encoding="utf-8")
    use_model(ScriptedModel(reply(action="list", field="contract_end_date", op="before",
                                  value="2030-01-01")))
    data = _ask_json(cli, db, "Какие договоры заканчиваются до 2030 года?")
    assert set(data) == {"question", "outcome", "reason", "other", "retried", "today",
                         "seconds", "provenance", "result"}
    assert data["question"] == "Какие договоры заканчиваются до 2030 года?"
    assert set(data["provenance"]) == {"code_version", "llm_model", "prompt_version",
                                       "prompt_sha256", "checks_version"}
    assert data["provenance"]["prompt_version"] == "10.3"
    assert data["provenance"]["checks_version"] == "06.1"
    assert data["provenance"]["llm_model"] == "fake-model"
    res = data["result"]
    assert set(res) == {"query", "count", "considered", "total", "include_unreviewed",
                        "matched_names", "rows", "excluded"}
    assert set(res["query"]) == {"action", "field", "op", "value", "value_to", "period", "side"}
    assert res["count"] == 8 and len(res["rows"]) == 8  # the full list, not list_rows
    assert res["excluded"] == {"unreviewed": [ids["check-date"]]}
    first = res["rows"][0]
    assert set(first) == {"document_id", "unreviewed", "cells"}
    assert set(first["cells"]) == set(FIELDS)
    assert set(first["cells"]["contract_end_date"]) == {"state", "value", "clause_id", "flags"}
    assert first["cells"]["contract_end_date"]["clause_id"] == f"{first['document_id']}/5.1"

    use_model(ScriptedModel(reply(action="list", field="contract_end_date", op="before",
                                  value="2030-01-01")))
    text = run_clean(cli, db, "Какие договоры заканчиваются до 2030 года?").stdout
    assert "  … ещё 6 — полный список: --json" in text


def test_amount_value_in_json_is_a_string(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(action="count", field="amount_with_vat", op="gt",
                                  value="1 000 000")))
    data = _ask_json(cli, db, "Сколько договоров дороже миллиона?")
    assert data["result"]["query"]["value"] == "1000000.00"


def test_nothing_is_written(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    before = _counts(db)
    use_model(ScriptedModel(reply(action="list", field="amount_with_vat", op="gt", value="0"),
                            reply(action="count", field="amount_with_vat", op="gt", value="0")))
    run_clean(cli, db, "Какие договоры дороже нуля?")
    run_clean(cli, db, "Сколько договоров дороже нуля?", "--json")
    assert _counts(db) == before


@pytest.mark.parametrize("question", ["", "   "])
def test_empty_question(cli, db, use_model, ids, question: str) -> None:  # type: ignore[no-untyped-def]
    model = use_model(ScriptedModel(reply(action="count", field="amount_with_vat", op="gt",
                                          value="0")))
    result = run_clean(cli, db, question)
    assert result.exit_code == 1
    assert "Пустой вопрос — введите вопрос о договорах" in result.stderr
    assert model.requests == []


def test_no_extracted_fields(cli, db, use_model, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    add_check_contracts(cli, tmp_path / "in")
    model = use_model(ScriptedModel(reply(action="count", field="amount_with_vat", op="gt",
                                          value="0")))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 1
    assert ("По таблице ответить нельзя: нет извлечённых полей "
            "(docreader extract, docreader check)") in result.stderr
    assert model.requests == []


def test_models_forbidden_without_a_fake(cli, db, ids, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(llm, "load_client", REAL_LOAD_CLIENT)  # the fixture's fake removed
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 2
    assert "На этой машине языковая модель не запускается (DOCREADER_FORBID_MODELS)" in (
        result.stderr)


def test_models_forbidden_comes_before_the_registry_check(cli, db, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    add_check_contracts(cli, tmp_path / "in")
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 2
    assert "DOCREADER_FORBID_MODELS" in result.stderr


def test_model_server_down_before_the_call(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    model = use_model(ScriptedModel(models_error=httpx2.ConnectError("refused")))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 2
    assert "Модель недоступна по адресу" in result.stderr
    assert model.requests == []


@pytest.mark.parametrize(
    "error", [httpx2.ConnectError("refused"), httpx2.ReadTimeout("slow")], ids=["drop", "slow"]
)
def test_connection_lost_or_timeout_during_the_call(cli, db, use_model, ids, error) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(error))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 2


def test_output_guard_on_a_name_question(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(action="list", field="contractor_name_short", op="eq",
                                  value="ООО «Бета»")))
    result = run_clean(cli, db, "Какие договоры с подрядчиком ООО «Бета» на 1 200 000?")
    assert result.exit_code == 0


# --- outcomes that are not an answer (T016, US3; research R-8, R-9; contracts/cli.md) ---


SECRET_REASON = "нет сведений о подписанте ООО «Бета» по договору К-21/2026"


@pytest.fixture
def no_rows(monkeypatch):  # type: ignore[no-untyped-def]
    """The table must not be read: the outcome is decided before the query."""
    def refuse(*args, **kwargs):
        raise AssertionError("load_rows must not be called")

    monkeypatch.setattr(table_answer, "load_rows", refuse)


@pytest.mark.parametrize(
    ("kind", "head"),
    [("refuse", "отказ"), ("clarify", "нужно уточнение"), ("unsupported", "не поддерживается")],
)
def test_outcomes_without_a_query(cli, db, use_model, ids, no_rows, kind, head) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(kind=kind, reason=SECRET_REASON)))
    result = run_clean(cli, db, "Кто подписал договор?", extra=[SECRET_REASON])
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith(f"По таблице — {head}; повторов 0; ") and lines[0].endswith(" с")
    assert lines[1] == "" and lines[2] == f"Причина: {SECRET_REASON}"
    search_hint = "Поиск по тексту не подставляется (docreader ask)"
    assert (search_hint in lines) is (kind == "refuse")
    assert lines[-1].startswith("Получено: код ")
    assert not any(x.startswith(("Условие:", "Договоры (", "Не учтено")) for x in lines)

    use_model(ScriptedModel(reply(kind=kind, reason=SECRET_REASON)))
    data = json.loads(run_clean(cli, db, "Кто подписал договор?", "--json").stdout)
    expected = {"refuse": "refused", "clarify": "clarify", "unsupported": "unsupported"}[kind]
    assert data["outcome"] == expected and data["reason"] == SECRET_REASON
    assert data["result"] is None


def test_party_on_both_sides_asks_to_clarify(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    # with --include-unreviewed «Альфа» is a counted customer and, in check-same, contractor
    use_model(ScriptedModel(reply(action="list", field="party", op="eq", value="Альфа")))
    result = run_clean(cli, db, "Какие договоры с Альфой?", "--include-unreviewed")
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].startswith("По таблице — нужно уточнение; повторов 0; ")
    assert lines[2].startswith("Причина: ") and "заказчик или подрядчик" in lines[2]
    use_model(ScriptedModel(reply(action="list", field="party", op="eq", value="Альфа")))
    data = json.loads(run_clean(cli, db, "Какие договоры с Альфой?", "--include-unreviewed",
                                "--json").stdout)
    assert data["outcome"] == "clarify" and data["result"] is None


def test_second_request_is_named_but_not_run(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    other = "какие из договоров ООО «Бета» заканчиваются в 2027 году"
    use_model(ScriptedModel(reply(action="count", field="contractor_name_short", op="eq",
                                  value="ООО «Бета»", other=other)))
    result = run_clean(cli, db, "Сколько договоров с ООО «Бета» и какие заканчиваются?",
                       extra=[other])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].startswith("По таблице — ответ: 8 договоров; ")
    assert f"Выполнен первый запрос; не выполнено: {other}" in lines
    use_model(ScriptedModel(reply(action="count", field="contractor_name_short", op="eq",
                                  value="ООО «Бета»", other=other)))
    data = json.loads(run_clean(cli, db, "Сколько договоров?", "--json").stdout)
    assert data["other"] == other and data["outcome"] == "answered"


def test_retry_shown_in_the_first_line(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(action="count", field="price", op="gt", value="0"),
                            reply(action="count", field="amount_with_vat", op="gt", value="0")))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 0
    assert "; повторов 1; " in result.stdout.splitlines()[0]


def test_rejected_after_the_retry(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    secret = "цена договора К-21/2026"
    model = use_model(ScriptedModel(
        reply(action="count", field=secret, op="gt", value="0"),
        reply(action="count", field="amount_with_vat", op="contains", value="0")))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?", extra=[secret])
    assert result.exit_code == 1
    assert result.stderr.startswith("Запрос модели недопустим: сравнение не допустимо для поля "
                                    "amount_with_vat")
    assert len(model.requests) == 2

    use_model(ScriptedModel(
        reply(action="count", field=secret, op="gt", value="0"),
        reply(action="count", field="amount_with_vat", op="contains", value="0")))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?", "--json", extra=[secret])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["outcome"] == "rejected" and data["retried"] is True and data["result"] is None


def test_failed_reply_not_in_form(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel("не JSON", "не JSON", "не JSON"))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 1
    assert result.stderr.startswith("Ошибка ответа модели: ")


def test_failed_http_error(cli, db, use_model, ids) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(httpx2.Response(400, json={"error": "too long"})))
    result = run_clean(cli, db, "Сколько договоров дороже нуля?")
    assert result.exit_code == 1
    assert "Ошибка ответа модели: " in result.stderr
