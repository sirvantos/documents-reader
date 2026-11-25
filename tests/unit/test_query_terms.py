"""Words of a search query for the word index (feature 08, research R-1, R-2; task T003).

Written by the main session: the rule that decides which query words count is a
decision rule (CLAUDE.md «Model routing»).
"""

import pytest

from docreader.wordforms import lemmatize, query_terms


def test_word_forms_to_dictionary_form() -> None:
    assert query_terms("неустойки") == ["неустойка"]
    assert query_terms("неустойку") == query_terms("неустойка")


def test_number_kept_whole_and_lower_cased() -> None:
    assert query_terms("ДП-17/2026") == ["дп-17/2026"]
    assert query_terms("пункт 2.2.1") == ["пункт", "2.2.1"]


def test_function_words_dropped() -> None:
    assert query_terms("и в на по") == []
    assert query_terms("срок оплаты по договору") == ["срок", "оплата", "договор"]


def test_particles_and_interjections_dropped() -> None:
    assert query_terms("не ли ах") == []


def test_pronouns_kept() -> None:
    # their weight is lowered by BM25, not by a list (research R-2)
    assert "какой" in query_terms("какой срок")


def test_repeats_removed_order_kept() -> None:
    assert query_terms("оплата срок оплаты оплату") == ["оплата", "срок"]


def test_yo_folded() -> None:
    assert query_terms("ёлка") == ["елка"]


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "—, .;"])
def test_empty(text: str) -> None:
    assert query_terms(text) == []


def test_same_forms_as_the_index() -> None:
    # the index stores lemmatize(label + text); every query word is one of its tokens
    text = "Покупатель оплачивает неустойку по договору № ДП-17/2026"
    index_tokens = {t.lower() for t in lemmatize(text).split()}
    assert set(query_terms(text)) <= index_tokens


# The number sign is the word «номер» in a query too (task T027).
def test_number_sign_is_the_word_number() -> None:
    assert query_terms("№ 5") == ["номер", "5"]
    assert query_terms("договор №ДП-17/2026") == ["договор", "номер", "дп-17/2026"]
    assert query_terms("номер №") == ["номер"]
    assert "номер" in query_terms("Какой номер договора?")
