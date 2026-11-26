"""The program corrects two kinds of model answers before the quote check (feature 05).

Findings of the first measurement on the gold set (feature 09, analyst, 2026-11-26), given
here in abstract form: the model took the contract number together with a letter code
after a space, and gave the full name of a party for its short name. Analyst's rules: a
letter code after a space is never part of the contract number; the short name is the
abbreviation in brackets right after the full name. A full name with no such
abbreviation in its quote is rejected, not stored. Critical rules (CLAUDE.md «Model
routing»): written by the main session; the implementer must not edit, weaken, skip or
delete these tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from docreader.fields import Result, spec
from docreader.verify import FULL_NAME, ClauseRange, FieldResult, TextIndex, check_field

LINES = [
    "ДОГОВОР ПОДРЯДА",
    "Nº ДП-17/2026 АБ-ВГД",
    "Открытое акционерное общество «Альфа Дельта Строй» (ОАО «АДС»), именуемое в",
    "дальнейшем Заказчик, и Акционерное общество «Бета», именуемое в дальнейшем",
    "Подрядчик, заключили настоящий договор:",
    "1.1. Подрядчик выполняет работы.",
]


def _build() -> TextIndex:
    text, spans, starts = "", [], []
    for i, line in enumerate(LINES):
        starts.append(len(text))
        spans.append((len(text), len(text) + len(line), 1, i))
        text += line + "\n"
    clauses = [
        ClauseRange("преамбула", "preamble", 0, starts[5]),
        ClauseRange("1.1", "clause", starts[5], len(text)),
    ]
    return TextIndex(text=text, shown_end=len(text), clauses=clauses, spans=spans,
                     text_sha256="b" * 64)


INDEX = _build()


@dataclass
class Answer:
    found: bool = True
    value: str | None = None
    quote: str | None = None
    clause: str | None = None


def check(field: str, **answer) -> FieldResult:
    return check_field(spec(field), Answer(**answer), INDEX)


# --- the contract number ---------------------------------------------------------------


@pytest.mark.parametrize(
    "value", ["Nº ДП-17/2026 АБ-ВГД", "ДП-17/2026 АБ-ВГД", "№ ДП-17/2026", "ДП-17/2026"]
)
def test_number_without_the_letter_code(value: str) -> None:
    r = check("contract_number", value=value, quote="ДОГОВОР ПОДРЯДА Nº ДП-17/2026 АБ-ВГД",
              clause="преамбула")
    assert r.result is Result.FOUND
    assert r.value_normalized == "ДП-17/2026"
    assert r.value_text == "ДП-17/2026"
    assert r.proposed_value == value  # what the model said stays for review


def test_the_rule_is_only_for_the_contract_number() -> None:
    # the generic identifier keeps an inner space (feature 05, research R-6)
    from docreader.fields import Kind
    from docreader.values import normalize

    assert normalize(Kind.IDENTIFIER, "ДП-17/2026 АБ-ВГД") == "ДП-17/2026 АБ-ВГД"


# --- the short name --------------------------------------------------------------------


def test_full_name_is_replaced_by_the_abbreviation_in_brackets() -> None:
    r = check(
        "customer_name_short",
        value="Открытое акционерное общество «Альфа Дельта Строй»",
        quote="Открытое акционерное общество «Альфа Дельта Строй» (ОАО «АДС»), именуемое в "
              "дальнейшем Заказчик",
        clause="преамбула",
    )
    assert r.result is Result.FOUND
    assert r.value_normalized == 'ОАО "АДС"'
    assert r.value_text == "ОАО «АДС»"
    assert r.clause_key == "преамбула"
    assert r.proposed_value == "Открытое акционерное общество «Альфа Дельта Строй»"


def test_short_name_given_by_the_model_is_kept() -> None:
    r = check("customer_name_short", value="ОАО «АДС»",
              quote="(ОАО «АДС»), именуемое в дальнейшем Заказчик")
    assert r.result is Result.FOUND
    assert r.value_normalized == 'ОАО "АДС"'


def test_full_name_without_an_abbreviation_is_rejected() -> None:
    r = check(
        "contractor_name_short",
        value="Акционерное общество «Бета»",
        quote="Акционерное общество «Бета», именуемое в дальнейшем Подрядчик",
        clause="преамбула",
    )
    assert r.result is Result.REJECTED
    assert r.reason == FULL_NAME
    assert r.proposed_value == "Акционерное общество «Бета»"


def test_full_name_in_lower_case_is_recognised() -> None:
    r = check("contractor_name_short", value="акционерное общество «Бета»",
              quote="Акционерное общество «Бета», именуемое в дальнейшем Подрядчик")
    assert r.result is Result.REJECTED
    assert r.reason == FULL_NAME
