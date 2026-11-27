"""Gold questions: key and file parsing (feature 02, T033, research R-11). Pure, no database."""

from __future__ import annotations

import pytest

from docreader.questions import (
    QuestionKind,
    QuestionOrigin,
    parse_question_file,
    question_key,
)


def test_key_is_stable_to_spaces_yo_and_case() -> None:
    k = question_key("D-0001", "Какой  счёт оплаты?")
    assert k == question_key("D-0001", " какой счет\nоплаты? ")
    assert k != question_key("D-0002", "Какой счёт оплаты?")
    assert k.startswith("Q-") and len(k) == 12


SET08 = """
[[question]]
text = "Какой срок оплаты?"
answer = "D-0002/2.2"
"""


def test_feature_08_form() -> None:
    parsed = parse_question_file(SET08)
    [q] = parsed.questions
    assert (q.number, q.document_id, q.clause_keys, q.has_answer) == (1, "D-0002", ("2.2",), True)
    assert q.kind is QuestionKind.TEXT and not q.false_premise and q.expected == ()
    assert parsed.origin is None and parsed.errors == []


SET09 = """
[[question]]
text = "Какой срок оплаты?"
document = "D-0001"
expected = "answer"

[[question]]
text = "Предусмотрен ли аванс?"
document = "D-0001"
expected = "none"

[[question]]
text = "Какой срок?"
answer = "D-0001/2.2"
contains = "30 дней"
"""


def test_feature_09_forms() -> None:
    no_clause, none, with_answer = parse_question_file(SET09).questions
    assert (no_clause.has_answer, no_clause.clause_keys) == (True, ())
    assert (none.has_answer, none.clause_keys) == (False, ())
    assert with_answer.expected == ("30 дней",)


def test_new_keys_and_origin() -> None:
    parsed = parse_question_file('''
origin = "set09"

[[question]]
text = "Почему цена — 5 000 000 руб.?"
answers = ["D-0015/5.2", "D-0015/5.3"]
false_premise = true
kind = "both"
contains = ["1000000.00"]
''')
    [q] = parsed.questions
    assert parsed.origin is QuestionOrigin.SET09
    assert q.clause_keys == ("5.2", "5.3") and q.document_id == "D-0015"
    assert q.false_premise and q.kind is QuestionKind.BOTH and q.expected == ("1000000.00",)


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        ('text = "a"', "answer"),
        ('text = "a"\nanswer = "D-0001/2.1"\nexpected = "none"\ndocument = "D-0001"', "одно"),
        ('text = "a"\nexpected = "none"', "document"),
        ('text = "a"\nanswer = "D-01/2.1"', "пункт"),
        ('text = "a"\nanswers = ["D-0001/2.1", "D-0002/2.1"]', "документ"),
        ('text = "a"\nanswer = "D-0001/2.1"\ndocument = "D-0002"', "документ"),
        ('text = ""\nanswer = "D-0001/2.1"', "текст"),
        ('text = "a"\nanswer = "D-0001/2.1"\nkind = "graph"', "kind"),
        ('text = "a"\ndocument = "D-0001"\nexpected = "maybe"', "expected"),
    ],
)
def test_errors_carry_the_question_number(body: str, reason: str) -> None:
    good = '[[question]]\ntext = "b"\nanswer = "D-0001/1.1"\n\n'
    parsed = parse_question_file(good + "[[question]]\n" + body + "\n")
    assert len(parsed.questions) == 1
    [(number, message)] = parsed.errors
    assert number == 2
    assert reason in message
    assert '"a"' not in message


def test_not_toml_is_a_file_error() -> None:
    with pytest.raises(ValueError, match="TOML"):
        parse_question_file("[[question]\ntext =")


def test_unknown_origin_is_a_file_error() -> None:
    with pytest.raises(ValueError, match="origin"):
        parse_question_file('origin = "other"\n')
