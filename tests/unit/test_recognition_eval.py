"""Pure calculations of `recognize-eval` (research R-12, task T027)."""

from __future__ import annotations

import pytest

from docreader.recognition_eval import (
    char_accuracy,
    extract_values,
    levenshtein,
    missing_lines,
    repeated_lines,
)


@pytest.mark.parametrize(
    ("a", "b", "distance"),
    [
        ("", "", 0),
        ("", "abc", 3),
        ("abc", "", 3),
        ("договор", "договор", 0),
        ("договор", "дагавор", 2),  # two substitutions
        ("договор", "договоор", 1),  # insertion
        ("договор", "доовор", 1),  # deletion
        ("kitten", "sitting", 3),
    ],
)
def test_levenshtein(a: str, b: str, distance: int) -> None:
    assert levenshtein(a, b) == distance
    assert levenshtein(b, a) == distance


def test_char_accuracy_is_one_minus_edits_per_expected_char() -> None:
    assert char_accuracy("договор", "договор") == 1.0
    assert char_accuracy("договор", "дагавор") == pytest.approx(1 - 2 / 7)


def test_line_breaks_and_spaces_are_not_errors() -> None:
    expected = "1.1. Подрядчик обязуется\nвыполнить работы"
    got = "1.1.  Подрядчик   обязуется выполнить\n\nработы"
    assert char_accuracy(expected, got) == 1.0


def test_char_normalisation_is_the_common_one() -> None:
    assert char_accuracy("ООО «Альфа» 1 500", "ООО «Альфа» 1 500") == 1.0


def test_accuracy_does_not_go_below_zero_and_empty_cases() -> None:
    assert char_accuracy("аб", "совсем другой длинный текст") == 0.0
    assert char_accuracy("", "") == 1.0
    assert char_accuracy("", "лишнее") == 0.0


def test_extract_values_finds_requisites_amounts_dates_and_clauses() -> None:
    text = "\n".join(
        [
            "Договор подряда № 123/45-У от 12.03.2024",
            "1.1. Подрядчик обязуется выполнить работы.",
            "5.2.1. Срок «12» марта 2024 г.",
            "Стоимость работ составляет 1 500 000 рублей, аванс 250 000,50 руб.",
            "ИНН 7701234567 КПП 770101001 ОГРН 1027700000001",
            "ИНН 770123456789",
            "ОГРНИП 304770000000012",
            "р/с 40702810900000000001 БИК 044525000",
        ]
    )
    values = extract_values(text)
    assert ("date", "12.03.2024") in values
    assert ("date", "«12» марта 2024") in values
    assert ("clause", "1.1") in values and ("clause", "5.2.1") in values
    assert ("amount", "1 500 000") in values and ("amount", "250 000,50") in values
    assert ("inn", "7701234567") in values and ("inn", "770123456789") in values
    assert ("kpp", "770101001") in values
    assert ("ogrn", "1027700000001") in values and ("ogrn", "304770000000012") in values
    kinds = {kind for kind, _ in values}
    assert kinds == {"date", "clause", "amount", "inn", "kpp", "ogrn"}
    # the bank account and the БИК are not requisites of the list
    assert not any(v in ("40702810900000000001", "044525000") for _, v in values)


def test_extract_values_in_plain_prose_finds_nothing() -> None:
    assert extract_values("Заказчик обязуется принять и оплатить работы в срок.") == []


def test_missing_and_repeated_lines() -> None:
    expected = "первая строка\nвторая строка\nтретья строка"
    got = "первая строка\nтретья строка\nтретья строка"
    assert missing_lines(expected, got) == ["вторая строка"]
    assert repeated_lines(got) == ["третья строка"]
    assert repeated_lines("а\nб") == []


def test_missing_lines_tolerate_small_recognition_errors() -> None:
    # a line with one wrong letter is not «missing»: it is counted in char accuracy
    assert missing_lines("Подрядчик обязуется", "Подрядчнк обязуется") == []


def test_form_blanks_do_not_count() -> None:
    # Runs of underscores are empty form fields, not text; engines drop them (R-12).
    expected = "г. Москва «___» __________ 2024 г."
    assert char_accuracy(expected, "г. Москва « » 2024 г.") == 1.0
    assert char_accuracy("подпись ____ В.В. Иванов", "подпись В.В. Иванов") == 1.0
    assert char_accuracy("snake_case", "snakecase") < 1.0  # a single underscore is text
