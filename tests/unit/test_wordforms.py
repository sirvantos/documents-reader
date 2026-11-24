"""Dictionary forms for the word index (feature 07, research R-5; task T011).

Written by the main session; the implementer must not edit, weaken, skip or delete
these tests.
"""

from __future__ import annotations

from docreader import values, wordforms
from docreader.wordforms import lemmatize


def test_inflected_forms_become_the_dictionary_form() -> None:
    assert lemmatize("неустойки неустойку") == "неустойка неустойка"


def test_words_with_a_digit_are_kept_as_written() -> None:
    assert lemmatize("Договор № ДП-17/2026, пункт 5.2.1") == "договор ДП-17/2026 пункт 5.2.1"


def test_comma_and_percent_are_separators() -> None:
    assert lemmatize("0,1%") == "0 1"


def test_yo_becomes_ye_and_case_is_lowered() -> None:
    assert lemmatize("Ёлка") == "елка"
    assert lemmatize("ПОДРЯДЧИК") == "подрядчик"


def test_punctuation_and_quotes_are_dropped() -> None:
    assert lemmatize("ООО «Альфа» — (Заказчик); «Бета»!") == "ооо альфа заказчик бета"


def test_inner_hyphen_slash_and_dot_keep_a_word_whole() -> None:
    assert lemmatize("D-0001 · раздел 5. Цена") == "D-0001 раздел 5 цена"


def test_empty_and_blank_text() -> None:
    assert lemmatize("") == ""
    assert lemmatize("  \n\t") == ""


def test_label_and_text_as_one_input() -> None:
    got = lemmatize(
        "D-0001 · раздел 3. Ответственность · пункт 3.1\n3.1. Подрядчик уплачивает неустойку"
    )
    assert got == "D-0001 раздел 3 ответственность пункт 3.1 3.1 подрядчик уплачивать неустойка"


def test_one_analyzer_per_process_shared_with_values() -> None:
    first = wordforms.analyzer()
    assert wordforms.analyzer() is first
    assert values._analyzer() is first  # values takes its analyzer from here
