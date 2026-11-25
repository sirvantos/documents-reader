"""The program check of the answer: quote check, retry merge, outcome (feature 09; T006, T007).

Research R-4 (a quote is confirmed only inside the shown passages, the named one first),
R-6 (the retry by claim numbers — analyst's decision U1: a claim the model says nothing
about stays visible), R-8 (outcome). Pure functions on hand-built values: no database,
no model. Written by the main session (critical part, CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from docreader import answer_check as ac
from docreader.answer_check import AnswerOutcome, ClaimStatus

# --- a small two-document set ---------------------------------------------------

LINES_1 = [
    # (line text, page)
    ("Преамбула: ООО «Альфа», именуемое Заказчик, и ООО «Бета».", 1),
    ("2.2. Срок оплаты товара составляет 30 дней с даты", 1),
    ("поставки товара Покупателю.", 2),
    ("3.1. Неустойка — 0,1% за каждый день; ёмкость склада не важна.", 2),
    ("3.2. Срок оплаты указан в пункте 2.2.", 2),
    ("4.1. Текст, которого модель не видела: гарантия 12 месяцев.", 2),
]
LINES_2 = [
    ("2.2. Оплата производится в течение 45 дней.", 1),
]


def build(lines: list[tuple[str, int]]) -> ac.DocumentText:
    text = "\n".join(t for t, _ in lines)
    spans = []
    pos = 0
    for i, (t, page) in enumerate(lines):
        spans.append((pos, pos + len(t), page, i))
        pos += len(t) + 1
    return ac.DocumentText(text=text, spans=spans)


DOC1 = build(LINES_1)
DOC2 = build(LINES_2)
TEXTS = {"D-0001": DOC1, "D-0002": DOC2}


def shown(doc: str, key: str, first: str, last: str | None = None, **over) -> ac.ShownPassage:
    """A passage from the line starting with `first` to the end of the line starting
    with `last` (or of `first`)."""
    text = TEXTS[doc].text
    start = text.index(first)
    last_start = text.index(last) if last else start
    end = text.index("\n", last_start) if "\n" in text[last_start:] else len(text)
    fields = {
        "clause_id": f"{doc}/{key}",
        "document_id": doc,
        "clause_key": key,
        "label": f"{doc} · пункт {key}",
        "start": start,
        "end": end,
        "first_page": 1,
        "last_page": 2,
    }
    fields.update(over)
    return ac.ShownPassage(**fields)


PRE = shown("D-0001", "преамбула", "Преамбула:")
P22 = shown("D-0001", "2.2", "2.2. Срок", "поставки товара")
P31 = shown("D-0001", "3.1", "3.1.")
P32 = shown("D-0001", "3.2", "3.2.")
Q22 = shown("D-0002", "2.2", "2.2. Оплата")
SHOWN = [P22, P31, P32, PRE]


def claim(quote: str, clause: str = "D-0001/2.2", text: str = "Утверждение.") -> SimpleNamespace:
    return SimpleNamespace(text=text, clause=clause, quote=quote)


def check(quote: str, clause: str = "D-0001/2.2", passages=None) -> ac.CheckedClaim:
    return ac.check_claim(claim(quote, clause), passages or SHOWN, TEXTS)


# --- check_claim (R-4) ----------------------------------------------------------


def test_quote_in_the_named_passage_is_confirmed() -> None:
    c = check("Неустойка — 0,1% за каждый день", "D-0001/3.1")
    assert c.status is ClaimStatus.CONFIRMED
    assert c.clause_id == "D-0001/3.1"
    assert c.quote_text == "Неустойка — 0,1% за каждый день"
    assert DOC1.text[c.start : c.end] == c.quote_text
    assert c.pages == (2,)
    assert c.named_clause == "D-0001/3.1"
    assert c.confirmed and not c.from_retry


def test_quote_in_another_shown_passage_corrects_the_reference() -> None:
    c = check("Неустойка — 0,1% за каждый день", "D-0001/2.2")
    assert c.status is ClaimStatus.CONFIRMED_ELSEWHERE
    assert c.clause_id == "D-0001/3.1"
    assert c.named_clause == "D-0001/2.2"
    assert c.confirmed


def test_quote_outside_every_shown_passage_is_not_confirmed() -> None:
    c = check("гарантия 12 месяцев", "D-0001/4.1")
    assert c.status is ClaimStatus.QUOTE_NOT_FOUND
    assert c.clause_id is None and c.start is None and c.pages == ()
    assert not c.confirmed


def test_paraphrase_is_not_confirmed() -> None:
    assert check("Оплата в течение тридцати дней").status is ClaimStatus.QUOTE_NOT_FOUND


@pytest.mark.parametrize("quote", ["", "   ", "\n"])
def test_blank_quote_is_no_quote(quote: str) -> None:
    c = check(quote)
    assert c.status is ClaimStatus.NO_QUOTE and not c.confirmed


def test_quote_across_a_line_and_page_break_is_found_on_two_pages() -> None:
    c = check("30 дней с даты поставки товара")
    assert c.status is ClaimStatus.CONFIRMED
    assert c.pages == (1, 2)
    assert "\n" in c.quote_text


@pytest.mark.parametrize(
    "quote",
    [
        "Срок  оплаты   товара",  # extra spaces
        "Неустойка - 0,1% за каждый день",  # hyphen for the dash
        "емкость склада",  # е for ё
        'ООО "Альфа"',  # straight quotes for «»
    ],
)
def test_quote_found_in_the_comparison_form(quote: str) -> None:
    assert check(quote, "D-0001/3.1").confirmed


def test_quote_across_two_adjacent_passages_is_not_found() -> None:
    c = check("каждый день; ёмкость склада не важна.\n3.2. Срок оплаты", "D-0001/3.1")
    assert c.status is ClaimStatus.QUOTE_NOT_FOUND


@pytest.mark.parametrize(
    "clause", ["D-0001/3.1", "3.1", "п. 3.1", "3.1.", "пункт 3.1", " d-0001 / 3.1 "]
)
def test_forms_of_the_named_clause(clause: str) -> None:
    c = check("Неустойка — 0,1%", clause)
    assert c.status is ClaimStatus.CONFIRMED, clause


def test_preamble_named_in_words() -> None:
    c = check("именуемое Заказчик", "Преамбула")
    assert c.status is ClaimStatus.CONFIRMED and c.clause_id == "D-0001/преамбула"


def test_prefix_of_another_document_is_searched_in_the_others() -> None:
    c = check("Неустойка — 0,1%", "D-0002/3.1")
    assert c.status is ClaimStatus.CONFIRMED_ELSEWHERE and c.clause_id == "D-0001/3.1"


def test_key_without_prefix_means_every_shown_passage_with_it() -> None:
    c = ac.check_claim(claim("в течение 45 дней", "2.2"), [P22, Q22], TEXTS)
    assert c.status is ClaimStatus.CONFIRMED and c.clause_id == "D-0002/2.2"


def test_first_occurrence_in_the_named_passage() -> None:
    # «Срок оплаты» stands in 2.2 and in 3.2
    c = check("Срок оплаты", "D-0001/3.2")
    assert c.status is ClaimStatus.CONFIRMED and c.clause_id == "D-0001/3.2"
    c = check("Срок оплаты", "D-0001/2.2")
    assert c.clause_id == "D-0001/2.2"
    assert c.start == DOC1.text.index("Срок оплаты")


def test_not_named_quote_goes_to_the_first_shown_passage_holding_it() -> None:
    c = check("Срок оплаты", "D-0001/9.9")
    assert c.status is ClaimStatus.CONFIRMED_ELSEWHERE and c.clause_id == "D-0001/2.2"
    c = ac.check_claim(claim("Срок оплаты", "D-0001/9.9"), [P32, P22], TEXTS)
    assert c.clause_id == "D-0001/3.2"


def test_text_and_quote_of_the_model_kept() -> None:
    c = ac.check_claim(claim("Срок оплаты", text="Срок — 30 дней."), SHOWN, TEXTS)
    assert c.text == "Срок — 30 дней." and c.quote == "Срок оплаты"


def test_module_imports_no_model_or_database_library() -> None:
    source = Path(ac.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"openai", "instructor", "psycopg", "httpx2"}


# --- needs_retry, merge_retry (R-6, analyst's decision U1) ----------------------


def ok(quote: str, clause: str = "D-0001/2.2", text: str = "ok") -> ac.CheckedClaim:
    c = ac.check_claim(claim(quote, clause, text), SHOWN, TEXTS)
    assert c.confirmed
    return c


def bad(text: str = "bad", quote: str = "нет такой цитаты") -> ac.CheckedClaim:
    c = ac.check_claim(claim(quote, text=text), SHOWN, TEXTS)
    assert not c.confirmed
    return c


def test_needs_retry_numbers_the_unconfirmed_from_one() -> None:
    a, b, c = ok("Срок оплаты"), bad("b"), bad("c", "")
    assert ac.needs_retry([b, a, c]) == [(1, b), (2, c)]
    assert ac.needs_retry([a]) == []
    assert ac.needs_retry([]) == []


def test_no_retry_keeps_the_first_answer() -> None:
    a = ok("Срок оплаты")
    merged = ac.merge_retry([a], [], None)
    assert merged.claims == [a]
    assert (merged.not_found_first, merged.not_found_final) == (0, 0)


def test_confirmed_of_the_first_answer_unchanged_and_first() -> None:
    a, b = ok("Срок оплаты", text="a"), bad("b")
    fixed = ok("Неустойка — 0,1%", "D-0001/3.1", text="b fixed")
    merged = ac.merge_retry([b, a], [(1, b)], {1: fixed})
    assert merged.claims[0] == a
    assert merged.claims[1] == dataclasses.replace(fixed, from_retry=True)
    assert (merged.not_found_first, merged.not_found_final) == (1, 0)


def test_retry_not_fixing_keeps_its_version_marked() -> None:
    a, b = ok("Срок оплаты"), bad("b")
    still = bad("b again", "другая неверная цитата")
    merged = ac.merge_retry([a, b], [(1, b)], {1: still})
    assert merged.claims == [a, dataclasses.replace(still, from_retry=True)]
    assert merged.not_found_final == 1


def test_claim_the_retry_does_not_return_stays_from_the_first_answer() -> None:
    # the U1 case: two asked, one returned and confirmed, one not returned
    a, b, c = ok("Срок оплаты", text="a"), bad("b"), bad("c")
    fixed = ok("Неустойка — 0,1%", "D-0001/3.1", text="b fixed")
    merged = ac.merge_retry([a, b, c], [(1, b), (2, c)], {1: fixed})
    assert merged.claims == [a, dataclasses.replace(fixed, from_retry=True), c]
    assert merged.claims[2].status is ClaimStatus.QUOTE_NOT_FOUND
    assert (merged.not_found_first, merged.not_found_final) == (2, 1)


@pytest.mark.parametrize("retry", [None, {}])
def test_retry_without_answer_keeps_every_asked_claim(retry) -> None:
    a, b, c = ok("Срок оплаты"), bad("b"), bad("c", "")
    merged = ac.merge_retry([a, b, c], [(1, b), (2, c)], retry)
    assert merged.claims == [a, b, c]
    assert (merged.not_found_first, merged.not_found_final) == (2, 2)


def test_number_not_asked_is_ignored() -> None:
    a, b = ok("Срок оплаты"), bad("b")
    stray = ok("Неустойка — 0,1%", "D-0001/3.1", text="stray")
    merged = ac.merge_retry([a, b], [(1, b)], {7: stray})
    assert merged.claims == [a, b]


def test_retry_confirming_an_already_confirmed_place_is_not_doubled() -> None:
    a, b = ok("Срок оплаты", text="a"), bad("b")
    same_place = ok("Срок оплаты", text="b fixed")
    merged = ac.merge_retry([a, b], [(1, b)], {1: same_place})
    assert merged.claims == [a]
    assert (merged.not_found_first, merged.not_found_final) == (1, 0)


def test_order_is_confirmed_then_unconfirmed() -> None:
    b, a, c = bad("b"), ok("Срок оплаты", text="a"), bad("c")
    fixed = ok("Неустойка — 0,1%", "D-0001/3.1", text="c fixed")
    merged = ac.merge_retry([b, a, c], [(1, b), (2, c)], {2: fixed})
    assert [x.text for x in merged.claims] == ["a", "c fixed", "b"]


@pytest.mark.parametrize(
    "retry",
    [
        None,
        {},
        {1: "fix"},
        {2: "fix"},
        {1: "still"},
        {1: "fix", 2: "still"},
        {1: "same"},
    ],
)
def test_retry_never_drops_or_changes_a_confirmed_claim(retry) -> None:
    a1, a2 = ok("Срок оплаты", text="a1"), ok("именуемое Заказчик", "Преамбула", text="a2")
    b, c = bad("b"), bad("c")
    versions = {
        "fix": ok("Неустойка — 0,1%", "D-0001/3.1", text="fix"),
        "still": bad("still"),
        "same": ok("Срок оплаты", text="same"),
    }
    mapped = None if retry is None else {n: versions[v] for n, v in retry.items()}
    merged = ac.merge_retry([a1, b, a2, c], [(1, b), (2, c)], mapped)
    assert merged.claims[:2] == [a1, a2]
    # every asked number gives exactly one claim unless its fix is already confirmed
    assert len(merged.claims) == 4 - (1 if retry == {1: "same"} else 0)


# --- outcome (R-8) -----------------------------------------------------------------


def merged_of(*claims: ac.CheckedClaim) -> ac.MergedClaims:
    return ac.merge_retry(list(claims), [], None)


def test_outcome_failed_first() -> None:
    assert ac.outcome(None, model_kind=None, failed=True) is AnswerOutcome.FAILED


def test_outcome_not_found_when_the_model_was_not_called() -> None:
    assert ac.outcome(None, model_kind=None) is AnswerOutcome.NOT_FOUND


def test_outcome_not_found_from_the_model() -> None:
    assert ac.outcome(merged_of(), model_kind="not_found") is AnswerOutcome.NOT_FOUND


def test_outcome_answered_with_one_confirmed() -> None:
    merged = merged_of(ok("Срок оплаты"), bad())
    assert ac.outcome(merged, model_kind="answer") is AnswerOutcome.ANSWERED


def test_outcome_unconfirmed_without_any_confirmed() -> None:
    assert ac.outcome(merged_of(bad(), bad("c", "")), model_kind="answer") is (
        AnswerOutcome.UNCONFIRMED
    )
