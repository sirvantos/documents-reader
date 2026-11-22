"""Integration tests for `docreader extract` (feature 05; tasks T016, T019).

Everything goes through `add`, `read`, `parse` and `extract` on the synthetic contracts of
`make_extraction_contract`; the model is a `ScriptedModel` (answers written here from the
truth of the variant). Written by the main session; the implementer must not edit,
weaken, skip or delete these tests (CLAUDE.md «Model routing»).

Page flags of recognised scans (low quality, unread) are set directly in `page_flag`
after reading: the rule under test is extraction's, not recognition's.
"""

from __future__ import annotations

import json

import httpx2
import pytest

from docreader import verify
from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import (
    BASE_ANSWERS,
    NOT_FOUND,
    add_variants,
    answer,
    field,
    field_rows,
    missing_answer,
    text_sha,
)
from tests.integration.test_read import add_files, set_stage, stage
from tests.synthetic import make_pdfs as mk

NOTHING = "Нечего извлекать: поля всех договоров заполнены (заново: docreader extract --all)"
FORBIDDEN = "На этой машине языковая модель не запускается (DOCREADER_FORBID_MODELS)"
DOWN = "Модель недоступна по адресу http://127.0.0.1:8080/v1 — запустите сервер модели"


def extract_json(cli, *args, code: int = 0) -> dict:
    result = cli("extract", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout)


def truth(variant: str) -> dict:
    return mk.extraction_truth(variant)["fields"]  # type: ignore[return-value]


def assert_matches_truth(db, doc_id: str, variant: str) -> None:
    rows = field_rows(db, doc_id)
    text = db.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]
    for name, expected in truth(variant).items():
        row = rows[name]
        got = {k: row[k] for k in ("result", "value_normalized", "clause_key", "page")}
        assert got == expected, name
        if row["result"] == "found":
            assert row["quote"] == text[row["quote_start"]:row["quote_end"]]


def flag(db, doc_id: str, page: int, code: str) -> None:
    db.execute(
        "INSERT INTO page_flag (document_id, page_number, code, reason) VALUES (%s, %s, %s, %s)",
        (doc_id, page, code, "флаг теста"),
    )


@pytest.fixture
def base(cli, tmp_path) -> str:
    (doc,) = add_variants(cli, tmp_path / "in", "base")
    return doc


# --- US1: six results, one run (T016) -----------------------------------------------------


def test_extract_base_gives_the_truth(cli, db, base, use_model) -> None:
    model = use_model(ScriptedModel(answer()))
    report = extract_json(cli)
    assert_matches_truth(db, base, "base")
    rows = field_rows(db, base)
    assert {r["source_text_sha256"] for r in rows.values()} == {text_sha(db, base)}
    assert rows["contract_number"]["value_text"] == "ДП-17/2026"
    assert rows["amount_with_vat"]["value_text"].startswith("1 440 000")
    assert stage(db, base, "extraction")[:2] == ("done", None)
    run = db.execute(
        "SELECT stage, model, prompt_version, settings FROM run WHERE id = %s",
        (report["run_id"],),
    ).fetchone()
    assert run[:3] == ("extraction", "qwen3.6-27b-4bit", "05.1")
    assert run[3]["served_model"] == "fake-model"
    assert len(run[3]["prompt_sha256"]) == 64
    assert run[3]["extraction"]["max_retries"] == 2
    assert {r["run_id"] for r in rows.values()} == {report["run_id"]}
    assert report["model"] == "qwen3.6-27b-4bit"
    assert report["prompt_version"] == "05.1"
    (doc,) = report["documents"]
    assert doc["document_id"] == base
    assert (doc["state"], doc["reason"]) == ("done", None)
    assert (doc["found"], doc["not_found"], doc["rejected"]) == (6, 0, 0)
    assert doc["not_found_fields"] == [] and doc["rejected_fields"] == []
    assert isinstance(doc["seconds"], (int, float))
    assert report["totals"] == {
        "extracted": 1, "needs_review": 0, "failed": 0, "skipped": 0,
        "fields_found": 6, "fields_not_found": 0, "fields_rejected": 0,
    }
    assert report["stopped"] is None and report["interrupted"] is False
    assert len(model.requests) == 1


def test_request_carries_the_shown_text_only(cli, db, base, use_model) -> None:
    model = use_model(ScriptedModel(answer()))
    extract_json(cli)
    (request,) = model.requests
    user = next(m for m in request["messages"] if m["role"] == "user")["content"]
    assert "Договор действует по 25 марта 2027 г." in user
    assert "Адреса и реквизиты сторон" in user  # the requisites are shown
    assert "Ведомость цены" not in user  # the appendix is not
    assert "999 999" not in user


def test_output_has_no_values_and_no_quotes(cli, base, use_model) -> None:
    use_model(ScriptedModel(answer(), answer()))
    text = cli("extract")
    assert text.exit_code == 0, text.stderr
    report = cli("extract", "--all", "--json")
    for out in (text.stdout + text.stderr, report.stdout + report.stderr):
        for value, quote, _ in BASE_ANSWERS.values():
            assert value not in out
            assert quote not in out
        assert "ДП-17/2026" not in out and "1440000.00" not in out


# --- selection ----------------------------------------------------------------------------


def test_selection_pending_all_and_ids(cli, db, tmp_path, use_model) -> None:
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(answer(), answer(), answer(), answer()))
    first = extract_json(cli)
    assert [d["document_id"] for d in first["documents"]] == [a, b]
    assert cli("extract").stdout.strip() == NOTHING
    again = extract_json(cli, "--all")
    assert [d["document_id"] for d in again["documents"]] == [a, b]
    one = extract_json(cli, b)
    assert [d["document_id"] for d in one["documents"]] == [b]


def test_failed_documents_are_taken_again(cli, db, tmp_path, use_model) -> None:
    _, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(answer(), answer(), answer()))
    extract_json(cli)
    set_stage(db, b, "extraction", "failed", "ошибка извлечения: X")
    report = extract_json(cli)
    assert [d["document_id"] for d in report["documents"]] == [b]


def test_all_with_ids_is_a_user_error(cli, base, use_model) -> None:
    use_model(ScriptedModel())
    result = cli("extract", base, "--all")
    assert result.exit_code == 1


def test_document_not_parsed_is_skipped(cli, db, tmp_path, use_model) -> None:
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    set_stage(db, b, "structure", "pending")
    use_model(ScriptedModel(answer()))
    report = extract_json(cli, a, b)
    assert [d["document_id"] for d in report["documents"]] == [a]
    assert report["skipped"] == [
        {"document_id": b, "reason": f"не разобран — выполните docreader parse {b}"}
    ]
    assert field_rows(db, b) == {}


def test_parse_of_an_older_text_is_skipped(cli, db, base, use_model) -> None:
    db.execute(
        "UPDATE clause SET source_text_sha256 = %s WHERE document_id = %s", ("b" * 64, base)
    )
    use_model(ScriptedModel(answer()))
    report = extract_json(cli, base)
    assert report["documents"] == []
    assert report["skipped"] == [
        {"document_id": base, "reason": f"разбор устарел — выполните docreader parse {base}"}
    ]
    assert cli("extract").stdout.strip() == NOTHING


def test_rerun_replaces_the_six_rows(cli, db, base, use_model) -> None:
    use_model(ScriptedModel(answer(), answer(amount_with_vat=NOT_FOUND)))
    first = extract_json(cli)
    second = extract_json(cli, base)
    rows = field_rows(db, base)
    assert len(rows) == 6
    assert rows["amount_with_vat"]["result"] == "not_found"
    assert {r["run_id"] for r in rows.values()} == {second["run_id"]}
    assert second["run_id"] != first["run_id"]


# --- states and reasons -------------------------------------------------------------------


def test_rejected_field_needs_review(cli, db, base, use_model) -> None:
    wrong = field("1 500 000 рублей", BASE_ANSWERS["amount_without_vat"][1], "2.1")
    use_model(ScriptedModel(answer(amount_without_vat=wrong)))
    report = extract_json(cli)
    reason = "отклонено: цена без НДС — значение не подтверждено цитатой"
    assert stage(db, base, "extraction")[:2] == ("needs_review", reason)
    (doc,) = report["documents"]
    assert (doc["found"], doc["rejected"], doc["rejected_fields"]) == (5, 1, ["amount_without_vat"])
    row = field_rows(db, base)["amount_without_vat"]
    assert (row["result"], row["proposed_value"]) == ("rejected", "1 500 000 рублей")


def test_answer_not_in_form_fails_one_document(cli, db, tmp_path, use_model) -> None:
    marker = "МАРКЕР-ОТВЕТА-5521"
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(marker, marker, marker, missing_answer()))
    result = cli("extract", "--json")
    assert result.exit_code == 0, result.stderr
    reason = "ответ модели не по форме после 2 повторов"
    assert stage(db, a, "extraction")[:2] == ("failed", reason)
    assert {(r["result"], r["reason"]) for r in field_rows(db, a).values()} == {("failed", reason)}
    assert stage(db, b, "extraction")[0] == "done"
    assert marker not in result.stdout + result.stderr


def test_exception_in_the_check_fails_one_document(
    cli, db, tmp_path, use_model, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = "МАРКЕР-ИСКЛЮЧЕНИЯ-7310"
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    real = verify.check_field
    calls = {"n": 0}

    def boom(spec, answer_, index):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError(marker)
        return real(spec, answer_, index)

    monkeypatch.setattr(verify, "check_field", boom)
    use_model(ScriptedModel(answer(), missing_answer()))
    result = cli("extract", "--json")
    assert result.exit_code == 0, result.stderr
    reason = "ошибка извлечения: RuntimeError"
    assert stage(db, a, "extraction")[:2] == ("failed", reason)
    assert {(r["result"], r["reason"]) for r in field_rows(db, a).values()} == {("failed", reason)}
    assert stage(db, b, "extraction")[0] == "done"
    assert marker not in result.stdout + result.stderr
    assert marker not in str(stage(db, a, "extraction"))


def test_server_refusal_fails_one_document(cli, db, tmp_path, use_model) -> None:
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(httpx2.Response(400, json={"error": "too long"}), missing_answer()))
    result = cli("extract", "--json")
    assert result.exit_code == 0, result.stderr
    assert stage(db, a, "extraction")[:2] == ("failed", "сервер модели отклонил запрос: HTTP 400")
    assert stage(db, b, "extraction")[0] == "done"


def test_text_too_long_is_not_sent(cli, db, tmp_path, data_dir, use_model) -> None:
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_structured_contract])
    assert cli("read").exit_code == 0 and cli("parse").exit_code == 0
    (data_dir / "settings.toml").write_text("[extraction]\nmax_shown_chars = 1000\n", "utf-8")
    model = use_model(ScriptedModel(answer()))
    result = cli("extract", "--json")
    assert result.exit_code == 0, result.stderr
    assert model.requests == []
    (state, reason, _) = stage(db, doc, "extraction")
    assert state == "failed"
    assert reason.startswith("текст слишком длинный: ") and reason.endswith(
        " знаков при пределе 1000"
    )
    shown = int(reason.split(": ")[1].split()[0])
    assert shown > 1000
    assert {r["result"] for r in field_rows(db, doc).values()} == {"failed"}


# --- the model server ---------------------------------------------------------------------


def test_forbidden_on_this_machine(cli, db, base) -> None:
    result = cli("extract")
    assert result.exit_code == 2
    assert FORBIDDEN in result.stderr
    assert stage(db, base, "extraction")[0] == "pending"
    assert db.execute("SELECT count(*) FROM run WHERE stage = 'extraction'").fetchone()[0] == 0


def test_model_down_before_the_run(cli, db, base, use_model) -> None:
    use_model(ScriptedModel(models_error=httpx2.ConnectError("refused")))
    result = cli("extract")
    assert result.exit_code == 2
    assert DOWN in result.stderr
    assert stage(db, base, "extraction")[0] == "pending"
    assert field_rows(db, base) == {}


def test_connection_lost_on_the_second_document(cli, db, tmp_path, use_model) -> None:
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(answer(), httpx2.ConnectError("reset")))
    result = cli("extract", "--json")
    assert result.exit_code == 2
    report = json.loads(result.stdout)
    assert [d["document_id"] for d in report["documents"]] == [a]
    assert report["stopped"] == {"document_id": b, "reason": DOWN}
    assert stage(db, a, "extraction")[0] == "done"
    assert stage(db, b, "extraction")[0] == "pending"
    assert field_rows(db, b) == {}


def test_timeout_stops_the_run(cli, db, base, use_model) -> None:
    use_model(ScriptedModel(httpx2.ReadTimeout("slow")))
    result = cli("extract")
    assert result.exit_code == 2
    assert "модель не ответила (тайм-аут 1800 с)" in result.stdout + result.stderr
    assert stage(db, base, "extraction")[0] == "pending"


# --- scans: page flags --------------------------------------------------------------------


def test_quote_on_a_low_quality_page(cli, db, base, use_model) -> None:
    flag(db, base, 2, "low_recognition_quality")
    use_model(ScriptedModel(answer()))
    extract_json(cli)
    assert stage(db, base, "extraction")[:2] == (
        "needs_review", "низкое качество распознавания: дата окончания (стр. 2)"
    )


def test_unread_page_in_the_shown_part(cli, db, base, use_model) -> None:
    flag(db, base, 2, "scan_unread")
    use_model(ScriptedModel(answer()))
    extract_json(cli)
    assert stage(db, base, "extraction")[:2] == ("needs_review", "не прочитана страница 2")


def test_unread_appendix_page_does_not_matter(cli, db, base, use_model) -> None:
    flag(db, base, 3, "scan_unread")
    flag(db, base, 3, "low_recognition_quality")
    use_model(ScriptedModel(answer()))
    extract_json(cli)
    assert stage(db, base, "extraction")[:2] == ("done", None)


# --- the other party ----------------------------------------------------------------------


def test_third_party_needs_review(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "three_parties")
    party = {"found": True, "quote": "ООО «Гамма», именуемое в дальнейшем Поручитель",
             "clause": "преамбула"}
    use_model(ScriptedModel(answer(other_party=party)))
    extract_json(cli)
    assert_matches_truth(db, doc, "three_parties")
    assert stage(db, doc, "extraction")[:2] == (
        "needs_review", f"состав сторон не соответствует допущению: {doc}/преамбула, стр. 1"
    )


def test_third_party_with_a_quote_not_in_the_text(cli, db, base, use_model) -> None:
    party = {"found": True, "quote": "ООО «Омега», именуемое Гарантом", "clause": None}
    use_model(ScriptedModel(answer(other_party=party)))
    extract_json(cli)
    assert stage(db, base, "extraction")[:2] == (
        "needs_review", "состав сторон не соответствует допущению: цитата не найдена"
    )


# --- variants -----------------------------------------------------------------------------


@pytest.mark.parametrize("variant", ["injection", "no_tail"])
def test_variants_with_base_answers(cli, db, tmp_path, use_model, variant: str) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", variant)
    use_model(ScriptedModel(answer()))
    extract_json(cli)
    assert_matches_truth(db, doc, variant)


def test_forms_variant(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "forms")
    use_model(ScriptedModel(answer(
        contractor_name_short=field(
            "ООО «Бёта–Строй»", "и ООО «Бёта–Строй», именуемое в дальнейшем Подрядчик"
        ),
        amount_without_vat=field("1 200 000,50 руб.", "Цена договора без НДС — 1 200 000,50 руб."),
        amount_with_vat=field("1 440 000,60 руб.", "с НДС — 1 440 000,60 руб."),
        contract_end_date=field("25.03.2027", "Договор действует до 25.03.2027", "4.1"),
    )))
    extract_json(cli)
    assert_matches_truth(db, doc, "forms")


# --- US3: «не найдено» (T019) -------------------------------------------------------------


def test_missing_variant_two_not_found(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "missing")
    use_model(ScriptedModel(missing_answer(), missing_answer()))
    report = extract_json(cli)
    assert_matches_truth(db, doc, "missing")
    assert stage(db, doc, "extraction")[:2] == ("done", None)
    (d,) = report["documents"]
    assert (d["found"], d["not_found"], d["rejected"]) == (4, 2, 0)
    assert d["not_found_fields"] == ["amount_with_vat", "contract_end_date"]
    text = cli("extract", "--all")
    assert text.exit_code == 0
    assert "найдено 4, не найдено 2 (цена с НДС, дата окончания), отклонено 0" in text.stdout


def test_computed_price_with_vat_is_rejected(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "missing")
    computed = field("1 440 000 рублей", "Цена договора составляет 1 200 000 рублей без НДС",
                     "2.1")
    use_model(ScriptedModel(answer(amount_with_vat=computed, contract_end_date=NOT_FOUND)))
    extract_json(cli)
    row = field_rows(db, doc)["amount_with_vat"]
    assert (row["result"], row["reason"]) == ("rejected", "значение не подтверждено цитатой")

