"""Text output of `docreader extract` and its help (contracts/cli.md «docreader extract»)."""

from datetime import datetime

import pytest

from docreader.cli import main
from docreader.extraction import ExtractedDocument, ExtractRun, SkippedDocument, Stopped
from docreader.fieldview import FieldsView, FieldView
from docreader.render import NOTHING_TO_EXTRACT, render_extract_text, render_fields_text


def _doc(
    document_id: str = "D-0001",
    state: str = "done",
    reason: str | None = None,
    *,
    found: int = 6,
    not_found: int = 0,
    rejected: int = 0,
    not_found_fields: list[str] | None = None,
    rejected_fields: list[str] | None = None,
) -> ExtractedDocument:
    return ExtractedDocument(
        document_id=document_id,
        state=state,
        reason=reason,
        found=found,
        not_found=not_found,
        rejected=rejected,
        not_found_fields=not_found_fields or [],
        rejected_fields=rejected_fields or [],
        seconds=212.4,
    )


def _run(
    documents: list[ExtractedDocument] | None = None,
    skipped: list[SkippedDocument] | None = None,
    stopped: Stopped | None = None,
    run_id: int | None = 61,
) -> ExtractRun:
    return ExtractRun(
        run_id=run_id,
        model="qwen3.6-27b-4bit",
        prompt_version="05.1",
        documents=documents or [],
        skipped=skipped or [],
        stopped=stopped,
    )


def test_nothing_to_extract_is_one_line() -> None:
    assert render_extract_text(_run(run_id=None)) == NOTHING_TO_EXTRACT


def test_done_document_line() -> None:
    text = render_extract_text(_run([_doc()]))
    assert text.splitlines()[0] == "D-0001  готово             найдено 6, не найдено 0, отклонено 0"


def test_not_found_fields_are_named_by_label() -> None:
    doc = _doc(
        found=4,
        not_found=2,
        not_found_fields=["amount_with_vat", "contract_end_date"],
    )
    line = render_extract_text(_run([doc])).splitlines()[0]
    assert "найдено 4, не найдено 2 (цена с НДС, дата окончания), отклонено 0" in line


def test_rejected_fields_are_named_by_label() -> None:
    doc = _doc(
        state="needs_review",
        found=4,
        not_found=1,
        rejected=1,
        rejected_fields=["amount_without_vat"],
        reason="отклонено: цена без НДС — значение не подтверждено цитатой",
    )
    line = render_extract_text(_run([doc])).splitlines()[0]
    assert line == (
        "D-0001  требует просмотра  найдено 4, не найдено 1, отклонено 1 (цена без НДС)"
        " — отклонено: цена без НДС — значение не подтверждено цитатой"
    )


def test_failed_document_shows_reason_instead_of_counts() -> None:
    doc = _doc(state="failed", reason="ответ модели не по форме после 2 повторов", found=0)
    line = render_extract_text(_run([doc])).splitlines()[0]
    assert line == "D-0001  ошибка             ответ модели не по форме после 2 повторов"


def test_skipped_document_line() -> None:
    skipped = SkippedDocument("D-0003", "не разобран — выполните docreader parse D-0003")
    text = render_extract_text(_run([_doc()], skipped=[skipped]))
    assert text.splitlines()[1] == (
        "D-0003  пропущен           не разобран — выполните docreader parse D-0003"
    )


def test_stopped_line() -> None:
    stopped = Stopped("D-0004", "модель не ответила (тайм-аут 1800 с)")
    text = render_extract_text(_run([_doc()], stopped=stopped))
    assert "Остановлено на D-0004: модель не ответила (тайм-аут 1800 с)" in text.splitlines()


def test_totals_line() -> None:
    documents = [
        _doc("D-0001", found=6),
        _doc(
            "D-0002",
            state="needs_review",
            found=3,
            not_found=2,
            rejected=1,
            not_found_fields=["amount_with_vat", "contract_end_date"],
            rejected_fields=["amount_without_vat"],
            reason="отклонено: цена без НДС — значение не подтверждено цитатой",
        ),
        _doc(
            "D-0003",
            state="failed",
            reason="текст слишком длинный: 90000 знаков при пределе 60000",
            found=0,
        ),
    ]
    skipped = [SkippedDocument("D-0004", "не разобран — выполните docreader parse D-0004")]
    text = render_extract_text(_run(documents, skipped=skipped))
    assert text.splitlines()[-1] == (
        "Итого: извлечено 2, требует просмотра 1, ошибок 1, пропущено 1; "
        "полей найдено 9, не найдено 2, отклонено 1 "
        "(запуск 61, модель qwen3.6-27b-4bit, подсказка 05.1)"
    )


def test_totals_line_without_run_id_has_no_details() -> None:
    skipped = [SkippedDocument("D-0004", "не разобран — выполните docreader parse D-0004")]
    text = render_extract_text(_run(skipped=skipped, run_id=None))
    assert text.splitlines()[-1] == (
        "Итого: извлечено 0, требует просмотра 0, ошибок 0, пропущено 1; "
        "полей найдено 0, не найдено 0, отклонено 0"
    )


def test_extract_help_lists_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["extract", "--help"]) == 0
    out = capsys.readouterr().out
    for option in ("--all", "--label", "--json"):
        assert option in out


def test_extract_is_listed_in_top_level_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "извлечь поля договоров" in capsys.readouterr().out


def _field(
    field: str = "contract_number",
    label: str = "номер договора",
    result: str = "found",
    **overrides: object,
) -> FieldView:
    base: dict[str, object] = {
        "value_text": None,
        "value_normalized": None,
        "quote": None,
        "quote_start": None,
        "quote_end": None,
        "clause_id": None,
        "clause_missing": False,
        "page": None,
        "pages": None,
        "low_quality": False,
        "reason": None,
        "proposed_value": None,
        "proposed_quote": None,
        "proposed_clause": None,
    }
    base.update(overrides)
    return FieldView(field=field, label=label, result=result, **base)  # type: ignore[arg-type]


def _fields_view(
    fields: list[FieldView] | None = None,
    state: str = "done",
    reason: str | None = None,
) -> FieldsView:
    return FieldsView(
        document_id="D-0001",
        state=state,
        reason=reason,
        run_id=61,
        run_started_at=datetime(2026, 11, 26, 9, 30),
        model="qwen3.6-27b-4bit",
        prompt_version="05.1",
        fields=fields or [],
    )


def test_fields_header_line() -> None:
    text = render_fields_text(_fields_view())
    assert text.splitlines()[0] == (
        "D-0001 — извлечение от 2026-11-26 (запуск 61, модель qwen3.6-27b-4bit, "
        "подсказка 05.1), готово"
    )


@pytest.mark.parametrize(
    ("state", "word"),
    [
        ("needs_review", "требует просмотра"),
        ("failed", "ошибка"),
        ("pending", "ожидает"),
    ],
)
def test_fields_header_state_words(state: str, word: str) -> None:
    first = render_fields_text(_fields_view(state=state)).splitlines()[0]
    assert first.endswith(f"подсказка 05.1), {word}")


def test_fields_reason_line_follows_header() -> None:
    reason = "отклонено: цена без НДС — значение не подтверждено цитатой"
    lines = render_fields_text(
        _fields_view(state="needs_review", reason=reason, fields=[_field()])
    ).splitlines()
    assert lines[1] == f"  {reason}"
    assert lines[2] == ""


def test_fields_without_reason_has_no_reason_line() -> None:
    lines = render_fields_text(_fields_view(fields=[_field()])).splitlines()
    assert lines[1] == ""


def test_found_block_with_clause_and_quote() -> None:
    field = _field(
        value_text="№ ДП-17/2026",
        value_normalized="ДП-17/2026",
        quote="ДОГОВОР ПОДРЯДА № ДП-17/2026",
        clause_id="D-0001/преамбула",
        page=1,
    )
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[2:] == [
        "номер договора      найдено     ДП-17/2026  (как в тексте: «№ ДП-17/2026»)",
        "                                D-0001/преамбула, стр. 1",
        "                                «ДОГОВОР ПОДРЯДА № ДП-17/2026»",
    ]


def test_found_block_quote_is_one_line() -> None:
    field = _field(
        value_text="ООО «Альфа»",
        value_normalized='ООО "Альфа"',
        quote="… (далее — ООО «Альфа»),\nв лице директора\nИванова",
        clause_id="D-0001/преамбула",
        page=1,
    )
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[4] == (
        "                                «… (далее — ООО «Альфа»), в лице директора Иванова»"
    )


def test_found_block_marks_low_quality_page() -> None:
    field = _field(
        value_text="ДП-17/2026",
        value_normalized="ДП-17/2026",
        quote="ДП-17/2026",
        clause_id="D-0001/преамбула",
        page=1,
        low_quality=True,
    )
    first = render_fields_text(_fields_view(fields=[field])).splitlines()[2]
    assert first.endswith("  (как в тексте: «ДП-17/2026») [низкое качество распознавания]")


def test_found_block_without_clause_says_clause_not_in_parse() -> None:
    field = _field(
        value_text="ДП-17/2026",
        value_normalized="ДП-17/2026",
        quote="ДП-17/2026",
        clause_id=None,
        page=1,
        clause_missing=True,
    )
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[3] == (
        "                                пункт не найден в разборе — "
        "выполните docreader extract D-0001"
    )


def test_not_found_block_is_one_line() -> None:
    field = _field(field="amount_with_vat", label="цена с НДС", result="not_found")
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[2] == "цена с НДС          не найдено"


def test_rejected_block_with_model_proposal() -> None:
    field = _field(
        field="amount_without_vat",
        label="цена без НДС",
        result="rejected",
        reason="значение не подтверждено цитатой",
        proposed_value="1 000 000 рублей",
        proposed_quote="стоимость 1 000 000 рублей",
        proposed_clause="2.1",
    )
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[2:] == [
        "цена без НДС        отклонено   значение не подтверждено цитатой",
        "                                модель: «1 000 000 рублей», пункт 2.1",
        "                                цитата модели: «стоимость 1 000 000 рублей»",
    ]


def test_rejected_block_without_clause_or_quote() -> None:
    field = _field(
        field="amount_without_vat",
        label="цена без НДС",
        result="rejected",
        reason="значение не подтверждено цитатой",
        proposed_value="1 000 000 рублей",
    )
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[3] == "                                модель: «1 000 000 рублей»"
    assert len(lines) == 4


def test_rejected_proposed_quote_line_breaks_become_spaces() -> None:
    field = _field(
        field="amount_without_vat",
        label="цена без НДС",
        result="rejected",
        reason="значение не подтверждено цитатой",
        proposed_value="1 000 000 рублей",
        proposed_quote="1 000\n000 рублей",
    )
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[4] == "                                цитата модели: «1 000 000 рублей»"


def test_failed_block_shows_reason() -> None:
    field = _field(
        field="contract_end_date",
        label="дата окончания",
        result="failed",
        reason="ответ модели не по форме после 2 повторов",
    )
    lines = render_fields_text(_fields_view(fields=[field])).splitlines()
    assert lines[2] == (
        "дата окончания      ошибка      ответ модели не по форме после 2 повторов"
    )


def test_fields_keep_the_given_order() -> None:
    fields = [
        _field(field="contract_number", label="номер договора", result="not_found"),
        _field(field="customer", label="заказчик", result="not_found"),
    ]
    lines = render_fields_text(_fields_view(fields=fields)).splitlines()
    assert lines[2:] == ["номер договора      не найдено", "заказчик            не найдено"]


def test_fields_help_lists_json_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["fields", "--help"]) == 0
    assert "--json" in capsys.readouterr().out


def test_fields_is_listed_in_top_level_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "показать поля договора" in capsys.readouterr().out
