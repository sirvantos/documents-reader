"""The program check of a field: quote, place, value; the state of a document.

Feature 05, research R-5 and R-8; task T011. Critical rules (CLAUDE.md «Model routing»).
The tests build a `TextIndex` by hand: a text, the end of its shown part, the clause
ranges of feature 04 and the `text_span` lines (start, end, page, line).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from docreader.fields import Result, spec
from docreader.stages import State
from docreader.verify import (
    ClauseRange,
    FieldResult,
    PartyResult,
    TextIndex,
    check_field,
    check_party,
    document_state,
    failed_results,
)

# A small contract: preamble on page 1, clause 2.1 across pages 1–2, clause 4.1 on page 2,
# the tail (requisites) on page 2, an appendix on page 3 after the shown part.
LINES = [
    ("ДОГОВОР ПОДРЯДА", 1),
    ("№ ДП-17/2026", 1),
    ("ООО «Альфа», именуемое Заказчик, и ООО «Бета», именуемое Подрядчик:", 1),
    ("2. Цена договора", 1),
    ("2.1. Цена договора составляет 1 200 000 рублей без НДС,", 1),
    ("всего с НДС 1 440 000 рублей. Аванс 1 200 000 рублей.", 2),
    ("4.1. Договор действует по 25 марта 2027 г.", 2),
    ("5. Адреса и реквизиты сторон", 2),
    ("Подрядчик: ООО «Бета», ИНН 0000000001", 2),
    ("Приложение № 1", 3),
    ("Итого 999 999 рублей. Договор действует по 1 апреля 2030 г.", 3),
]


def _build() -> TextIndex:
    text = ""
    spans = []
    starts = []
    for i, (line, page) in enumerate(LINES):
        starts.append(len(text))
        spans.append((len(text), len(text) + len(line), page, i))
        text += line + "\n"

    def at(n: int) -> int:
        return starts[n]

    clauses = [
        ClauseRange("преамбула", "preamble", 0, at(3)),
        ClauseRange("2", "section", at(3), at(4)),
        ClauseRange("2.1", "clause", at(4), at(6)),
        ClauseRange("4.1", "clause", at(6), at(7)),
        ClauseRange("реквизиты", "tail", at(7), len(text)),
    ]
    return TextIndex(
        text=text, shown_end=at(9), clauses=clauses, spans=spans, text_sha256="a" * 64
    )


INDEX = _build()


@dataclass
class Answer:
    found: bool = True
    value: str | None = None
    quote: str | None = None
    clause: str | None = None


def check(field: str, **answer) -> FieldResult:
    return check_field(spec(field), Answer(**answer), INDEX)


# --- found -------------------------------------------------------------------------------


def test_verbatim_quote_is_found_with_place() -> None:
    r = check("amount_with_vat", value="1 440 000 рублей", quote="всего с НДС 1 440 000 рублей",
              clause="2.1")
    assert r.result is Result.FOUND
    assert INDEX.text[r.quote_start:r.quote_end] == "всего с НДС 1 440 000 рублей"
    assert r.quote == "всего с НДС 1 440 000 рублей"
    assert (r.clause_key, r.page, r.pages) == ("2.1", 2, (2,))
    assert r.value_text == "1 440 000 рублей"
    assert r.value_normalized == "1440000.00"
    assert (r.proposed_value, r.proposed_clause) == ("1 440 000 рублей", "2.1")
    assert r.proposed_quote is None
    assert r.reason is None


def test_value_text_comes_from_the_contract_not_the_model() -> None:
    r = check("amount_with_vat", value="1440000.00", quote="всего с НДС 1 440 000 рублей")
    assert r.result is Result.FOUND
    assert r.value_text == "1 440 000 рублей"
    assert r.proposed_value == "1440000.00"


def test_quote_across_the_title_line_break() -> None:
    r = check("contract_number", value="№ ДП-17/2026", quote="ДОГОВОР ПОДРЯДА № ДП-17/2026",
              clause="преамбула")
    assert r.result is Result.FOUND
    assert INDEX.text[r.quote_start:r.quote_end] == "ДОГОВОР ПОДРЯДА\n№ ДП-17/2026"
    assert r.value_text == "ДП-17/2026"
    assert r.value_normalized == "ДП-17/2026"
    assert (r.clause_key, r.page) == ("преамбула", 1)


@pytest.mark.parametrize(
    "quote",
    [
        "ООО «Бета»,  именуемое   Подрядчик",  # spaces
        "ООО „Бета“, именуемое Подрядчик",  # other quote marks
        'ООО "Бета", именуемое Подрядчик',
    ],
)
def test_quote_differing_only_in_spaces_or_quote_marks_is_found(quote: str) -> None:
    r = check("contractor_name_short", value="ООО «Бета»", quote=quote)
    assert r.result is Result.FOUND
    assert r.value_text == "ООО «Бета»"
    assert r.value_normalized == 'ООО "Бета"'


def test_quote_with_yo_and_hyphen_variants_is_found() -> None:
    r = check("contract_number", value="ДП‐17/2026", quote="№ ДП‑17/2026")
    assert r.result is Result.FOUND
    assert r.value_normalized == "ДП-17/2026"


def test_quote_over_a_page_break() -> None:
    r = check("amount_without_vat", value="1 200 000 рублей",
              quote="составляет 1 200 000 рублей без НДС, всего с НДС", clause="2.1")
    assert r.result is Result.FOUND
    assert (r.page, r.pages) == (1, (1, 2))


def test_quote_crossing_two_clauses_belongs_to_where_it_starts() -> None:
    r = check("contract_end_date", value="25 марта 2027 г.",
              quote="по 25 марта 2027 г. 5. Адреса и реквизиты сторон")
    assert r.result is Result.FOUND
    assert r.clause_key == "4.1"


def test_quote_in_the_tail_belongs_to_the_requisites() -> None:
    r = check("contractor_name_short", value="ООО «Бета»", quote="Подрядчик: ООО «Бета», ИНН")
    assert r.result is Result.FOUND
    assert (r.clause_key, r.page) == ("реквизиты", 2)


@pytest.mark.parametrize("hint", ["2.1", "2.1.", "п. 2.1", "пункт 2.1", " 2.1 "])
def test_occurrence_in_the_named_clause_is_chosen(hint: str) -> None:
    # «1 200 000 рублей» appears twice, both inside 2.1 here; use a quote that also
    # appears in the preamble-free part twice: «рублей» lines 4 and 5
    r = check("amount_without_vat", value="1 200 000 рублей", quote="1 200 000 рублей",
              clause=hint)
    assert r.result is Result.FOUND
    assert r.clause_key == "2.1"


def test_named_clause_without_the_quote_falls_back_to_the_first() -> None:
    r = check("amount_without_vat", value="1 200 000 рублей", quote="1 200 000 рублей",
              clause="4.1")
    assert r.result is Result.FOUND
    first = INDEX.text.find("1 200 000 рублей")
    assert r.quote_start == first


def test_named_clause_picks_the_later_occurrence() -> None:
    # «Договор действует по» appears in 4.1 and in the appendix (not shown); and «ООО «Бета»»
    # appears in the preamble and in the tail
    r = check("contractor_name_short", value="ООО «Бета»", quote="ООО «Бета»", clause="реквизиты")
    assert r.result is Result.FOUND
    assert r.clause_key == "реквизиты"
    r = check("contractor_name_short", value="ООО «Бета»", quote="ООО «Бета»")
    assert r.clause_key == "преамбула"


# --- rejected ----------------------------------------------------------------------------


def test_quote_only_after_the_shown_part_is_not_found() -> None:
    r = check("contract_end_date", value="1 апреля 2030 г.",
              quote="Договор действует по 1 апреля 2030 г.", clause="4.1")
    assert r.result is Result.REJECTED
    assert r.reason == "цитата не найдена"
    assert (r.proposed_value, r.proposed_quote, r.proposed_clause) == (
        "1 апреля 2030 г.", "Договор действует по 1 апреля 2030 г.", "4.1"
    )
    assert (r.value_text, r.value_normalized, r.quote, r.quote_start, r.clause_key, r.page,
            r.pages) == (None, None, None, None, None, None, None)


def test_quote_not_in_the_text() -> None:
    r = check("amount_with_vat", value="1 440 000 рублей", quote="цена с НДС 1 440 000 рублей")
    assert (r.result, r.reason) == (Result.REJECTED, "цитата не найдена")


@pytest.mark.parametrize(
    ("field", "value", "quote"),
    [
        ("amount_with_vat", "1 500 000 рублей", "всего с НДС 1 440 000 рублей"),
        ("contract_end_date", "26 марта 2027 г.", "по 25 марта 2027 г."),
        ("contract_number", "ДП-18/2026", "№ ДП-17/2026"),
        ("customer_name_short", "ООО «Гамма»", "ООО «Альфа», именуемое Заказчик"),
    ],
)
def test_value_not_in_the_quote(field: str, value: str, quote: str) -> None:
    r = check(field, value=value, quote=quote)
    assert (r.result, r.reason) == (Result.REJECTED, "значение не подтверждено цитатой")
    assert r.proposed_value == value


@pytest.mark.parametrize("quote", [None, "", "   "])
def test_value_without_a_quote(quote) -> None:
    r = check("amount_with_vat", value="1 440 000 рублей", quote=quote)
    assert (r.result, r.reason) == (Result.REJECTED, "нет цитаты")


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("amount_with_vat", "один миллион", "значение не приводится к сумме"),
        ("contract_end_date", "до исполнения обязательств", "значение не приводится к дате"),
        ("contract_number", "№", "значение не приводится к номеру"),
    ],
)
def test_value_that_does_not_normalize(field: str, value: str, reason: str) -> None:
    r = check(field, value=value, quote="всего с НДС 1 440 000 рублей")
    assert (r.result, r.reason) == (Result.REJECTED, reason)


# --- not found ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        {"found": False},
        {"found": False, "value": "1 рубль", "quote": "Аванс 1 200 000 рублей", "clause": "2.1"},
        {"found": True, "value": None},
        {"found": True, "value": "  "},
    ],
)
def test_not_found(answer: dict) -> None:
    r = check("amount_with_vat", **answer)
    assert r.result is Result.NOT_FOUND
    assert all(
        getattr(r, name) is None
        for name in ("value_text", "value_normalized", "quote", "quote_start", "quote_end",
                     "clause_key", "page", "pages", "reason", "proposed_value",
                     "proposed_quote", "proposed_clause")
    )


# --- failed ------------------------------------------------------------------------------


def test_failed_results_are_six_with_the_reason() -> None:
    results = failed_results("ответ модели не по форме после 2 повторов")
    assert [r.field for r in results] == [
        "contract_number", "customer_name_short", "contractor_name_short",
        "amount_without_vat", "amount_with_vat", "contract_end_date",
    ]
    assert all(r.result is Result.FAILED for r in results)
    assert {r.reason for r in results} == {"ответ модели не по форме после 2 повторов"}
    assert all(r.proposed_value is None and r.quote is None for r in results)


# --- the other party ----------------------------------------------------------------------


def test_no_other_party() -> None:
    assert check_party(Answer(found=False), INDEX) == PartyResult(found=False)


def test_other_party_with_a_found_quote() -> None:
    party = check_party(Answer(found=True, quote="ООО «Бета», именуемое Подрядчик"), INDEX)
    assert party == PartyResult(found=True, quote_found=True, clause_key="преамбула", page=1)


@pytest.mark.parametrize("quote", [None, "", "ООО «Гамма», именуемое Поручителем"])
def test_other_party_with_a_missing_quote(quote) -> None:
    party = check_party(Answer(found=True, quote=quote), INDEX)
    assert party == PartyResult(found=True, quote_found=False)


# --- document state and reason ------------------------------------------------------------

NO_PARTY = PartyResult(found=False)


def _all_found() -> list[FieldResult]:
    return [
        check("contract_number", value="ДП-17/2026", quote="№ ДП-17/2026"),
        check("customer_name_short", value="ООО «Альфа»", quote="ООО «Альфа»"),
        check("contractor_name_short", value="ООО «Бета»", quote="ООО «Бета», именуемое"),
        check("amount_without_vat", value="1 200 000 рублей", quote="1 200 000 рублей без НДС"),
        check("amount_with_vat", value="1 440 000 рублей", quote="всего с НДС 1 440 000 рублей"),
        check("contract_end_date", value="25 марта 2027 г.", quote="по 25 марта 2027 г."),
    ]


def state(results, party=NO_PARTY, low=(), unread=(), last=2):
    return document_state(
        results, party, low_quality_pages=low, unread_pages=unread, shown_last_page=last,
        document_id="D-0001",
    )


def test_all_found_is_done() -> None:
    results = _all_found()
    assert all(r.result is Result.FOUND for r in results)
    assert state(results) == (State.DONE, None)


def test_not_found_does_not_change_the_state() -> None:
    results = _all_found()
    results[4] = check("amount_with_vat", found=False)
    assert state(results) == (State.DONE, None)


def test_rejected_needs_review() -> None:
    results = _all_found()
    results[3] = check("amount_without_vat", value="1 500 000 рублей", quote="1 200 000 рублей")
    assert state(results) == (
        State.NEEDS_REVIEW, "отклонено: цена без НДС — значение не подтверждено цитатой"
    )


def test_two_rejected_fields_in_catalog_order() -> None:
    results = _all_found()
    results[4] = check("amount_with_vat", value="1 440 000 рублей", quote="нет такой цитаты")
    results[0] = check("contract_number", value="ДП-1", quote="№ ДП-17/2026")
    assert state(results)[1] == (
        "отклонено: номер договора — значение не подтверждено цитатой, "
        "цена с НДС — цитата не найдена"
    )


def test_low_recognition_quality_on_a_quote_page() -> None:
    assert state(_all_found(), low=(2,)) == (
        State.NEEDS_REVIEW,
        "низкое качество распознавания: цена с НДС (стр. 2), дата окончания (стр. 2)",
    )


def test_low_quality_on_a_page_without_quotes_does_not_matter() -> None:
    assert state(_all_found(), low=(3,)) == (State.DONE, None)


def test_unread_page_in_the_shown_part() -> None:
    assert state(_all_found(), unread=(2,)) == (State.NEEDS_REVIEW, "не прочитана страница 2")
    assert state(_all_found(), unread=(1, 2)) == (
        State.NEEDS_REVIEW, "не прочитаны страницы 1, 2"
    )


def test_unread_page_after_the_shown_part_does_not_matter() -> None:
    assert state(_all_found(), unread=(3, 4), last=2) == (State.DONE, None)


def test_other_party_with_its_place() -> None:
    party = PartyResult(found=True, quote_found=True, clause_key="преамбула", page=1)
    assert state(_all_found(), party=party) == (
        State.NEEDS_REVIEW,
        "состав сторон не соответствует допущению: D-0001/преамбула, стр. 1",
    )


def test_other_party_without_a_quote() -> None:
    party = PartyResult(found=True, quote_found=False)
    assert state(_all_found(), party=party) == (
        State.NEEDS_REVIEW, "состав сторон не соответствует допущению: цитата не найдена"
    )


def test_reason_parts_in_order() -> None:
    results = _all_found()
    results[3] = check("amount_without_vat", value="1 500 000 рублей", quote="1 200 000 рублей")
    party = PartyResult(found=True, quote_found=True, clause_key="преамбула", page=1)
    _, reason = state(results, party=party, low=(5,), unread=(1,), last=2)
    assert reason == (
        "отклонено: цена без НДС — значение не подтверждено цитатой; "
        "не прочитана страница 1; "
        "состав сторон не соответствует допущению: D-0001/преамбула, стр. 1"
    )
    results[4] = check("amount_with_vat", value="1 440 000 рублей", quote="1 440 000 рублей")
    _, reason = state(results, party=party, low=(2,), unread=(1,), last=2)
    assert reason == (
        "отклонено: цена без НДС — значение не подтверждено цитатой; "
        "низкое качество распознавания: цена с НДС (стр. 2), дата окончания (стр. 2); "
        "не прочитана страница 1; "
        "состав сторон не соответствует допущению: D-0001/преамбула, стр. 1"
    )


def test_failed_results_make_the_document_failed() -> None:
    results = failed_results("текст слишком длинный: 200000 знаков при пределе 150000")
    assert state(results, unread=(1,)) == (
        State.FAILED, "текст слишком длинный: 200000 знаков при пределе 150000"
    )


def test_reason_carries_no_proposed_value_or_quote() -> None:
    marker = "МАРКЕР-9931"
    results = _all_found()
    results[3] = check("amount_without_vat", value=f"{marker} 1 рубль", quote=f"{marker} цитата")
    results[4] = check("amount_with_vat", value="1 500 000 рублей", quote=f"{marker}")
    _, reason = state(results)
    assert reason is not None
    assert marker not in reason
