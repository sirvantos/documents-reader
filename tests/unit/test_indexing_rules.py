"""The model input limit and the state of a document (feature 07, research R-6, R-8; T013).

Pure functions; no database, no model. Critical part (plan.md «Критические части»),
written by the main session; the implementer must not edit, weaken, skip or delete
these tests.
"""

from __future__ import annotations

from docreader.indexing import embedding_input, index_state
from docreader.stages import State

MARKER = "МАРКЕР-9184"


def test_input_is_label_newline_text() -> None:
    assert embedding_input("D-0001 · пункт 1.1", "1.1. Текст.", 1000) == (
        "D-0001 · пункт 1.1\n1.1. Текст.", False
    )


def test_exactly_max_chars_is_not_truncated() -> None:
    label, text = "L", "x" * 8  # "L\n" + 8 = 10 characters
    assert embedding_input(label, text, 10) == ("L\nxxxxxxxx", False)


def test_one_more_character_is_truncated() -> None:
    label, text = "L", "x" * 9  # 11 characters
    assert embedding_input(label, text, 10) == ("L\nxxxxxxxx", True)


def test_no_truncation_is_done() -> None:
    assert index_state(["преамбула", "1.1"], set(), "D-0001") == (State.DONE, None)


def test_truncated_passages_need_review_in_passage_order() -> None:
    keys = ["преамбула", "5.2", "6.1", "реквизиты"]
    assert index_state(keys, {"реквизиты", "5.2"}, "D-0001") == (
        State.NEEDS_REVIEW,
        "отрывок длиннее предела модели: D-0001/5.2, D-0001/реквизиты",
    )


def test_more_than_five_truncated_are_shortened() -> None:
    keys = [f"{i}.1" for i in range(1, 9)]
    state, reason = index_state(keys, set(keys), "D-0003")
    assert state is State.NEEDS_REVIEW
    assert reason == (
        "отрывок длиннее предела модели: D-0003/1.1, D-0003/2.1, D-0003/3.1, D-0003/4.1, "
        "D-0003/5.1 и ещё 3"
    )


def test_no_passages_need_review() -> None:
    assert index_state([], set(), "D-0001") == (State.NEEDS_REVIEW, "нет отрывков")


def test_reason_holds_no_text() -> None:
    _, reason = index_state([f"{MARKER}"], {MARKER}, "D-0001")
    # the key is printed as an id; a label or a passage text never is
    assert reason is not None and "\n" not in reason
    assert embedding_input(MARKER, MARKER, 5)[0] == MARKER[:5]
