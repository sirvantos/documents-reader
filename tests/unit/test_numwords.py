"""Russian cardinal numbers in words → integer, for the amount-in-words rule (feature 06, T004).

`numwords.words_to_int(text) -> int | None` reads units, tens, hundreds and the scales
«тысяча», «миллион», «миллиард» in any of their forms; reading stops at the rouble or the
kopeck word (what follows spells the kopecks); an unknown word gives None (research R-3).
`numwords.words_of_amount(value_text, after)` — the bracketed words that spell the amount:
inside the value text, or a bracket that opens right after it.
"""

from __future__ import annotations

import pytest

from docreader.numwords import words_of_amount, words_to_int


@pytest.mark.parametrize(
    ("words", "number"),
    [
        ("один миллион двести тысяч", 1_200_000),
        ("Четыре миллиона семьсот две тысячи четыреста", 4_702_400),
        ("Девятьсот тысяч", 900_000),
        ("Сто сорок тысяч", 140_000),
        ("тысяча", 1_000),
        ("одна тысяча", 1_000),
        ("две тысячи", 2_000),
        ("двадцать один миллион", 21_000_000),
        ("девятьсот девяносто девять тысяч девятьсот девяносто девять", 999_999),
        ("Два миллиарда триста миллионов одиннадцать", 2_300_000_011),
        ("ноль", 0),
        ("Триста тысяч рублей 00 копеек", 300_000),
        ("Семьсот тысяч рублей двадцать копеек", 700_000),
        ("пятьсот руб. сорок коп.", 500),
    ],
)
def test_words_to_int(words: str, number: int) -> None:
    assert words_to_int(words) == number


@pytest.mark.parametrize("words", ["без учёта НДС", "пять тысяч штук", "", "   "])
def test_not_a_number(words: str) -> None:
    assert words_to_int(words) is None


def test_words_inside_the_value_text() -> None:
    assert words_of_amount("1 200 000 (один миллион двести тысяч) рублей", "") == (
        "один миллион двести тысяч"
    )


def test_words_right_after_the_value() -> None:
    assert words_of_amount("1 200 000", " (один миллион двести тысяч) рублей") == (
        "один миллион двести тысяч"
    )
    assert words_of_amount("1 200 000", " — (один миллион)") == "один миллион"


def test_no_words() -> None:
    assert words_of_amount("1 200 000 рублей", " без НДС") is None
    assert words_of_amount("1 200 000", " рублей, НДС (20%) — 240 000") is None
    assert words_of_amount("1 200 000", " рублей (один миллион)") is None  # not right after
