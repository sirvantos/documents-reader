"""Comparison form and quote locating (task T066, tech-context «Договорённости между этапами»)."""

from __future__ import annotations

import pytest

from docreader.textnorm import compare_form, is_empty_phrase, locate

TEXT = "Договор подряда\n№ 123/45-У на работы\n«Срок» — 10 дней; объём CKAВ"


def spans(text: str, phrase: str) -> list[str]:
    return [text[a:b] for a, b in locate(text, phrase)]


def test_phrase_across_a_line_break():
    assert spans(TEXT, "подряда № 123/45-У") == ["подряда\n№ 123/45-У"]


def test_offsets_point_into_the_original_text():
    ((start, end),) = locate(TEXT, "на работы «Срок»")
    assert TEXT[start:end] == "на работы\n«Срок»"
    assert TEXT[start] == "н"
    assert TEXT[end - 1] == "»"


@pytest.mark.parametrize(
    "phrase",
    ['"Срок" - 10', "«Срок» – 10", "«Срок» — 10", "«Срок»  —\n10"],
)
def test_dash_quote_and_space_variants(phrase):
    assert spans(TEXT, phrase) == ["«Срок» — 10"]


def test_yo_and_ye_match_both_ways():
    assert spans(TEXT, "объем") == ["объём"]
    assert spans("объем работ", "объём") == ["объем"]


def test_latin_lookalikes_inside_cyrillic_words():
    assert spans(TEXT, "СКАВ") == ["CKAВ"]  # Latin C, K, A in the text
    # a Latin identifier is not turned into Cyrillic
    assert locate("ключ b55183f5-ac", "b55183f5-ас") == []
    assert spans("ключ b55183f5-ac", "b55183f5-ac") == ["b55183f5-ac"]


def test_decomposed_phrase_matches_composed_text():
    decomposed = "Росси" + "и\u0306" + "ская"  # «й» as «и» + combining breve
    assert spans("Российская Федерация", decomposed) == ["Российская"]


def test_case_is_kept():
    assert locate(TEXT, "договор подряда") == []


def test_non_overlapping_left_to_right():
    assert locate("ааа ааа", "аа") == [(0, 2), (4, 6)]


def test_empty_phrase():
    assert locate(TEXT, " \n ") == []
    assert is_empty_phrase(" \n ")
    assert not is_empty_phrase("а")


def test_compare_form_offsets():
    folded, offsets = compare_form(" а\n\n б ")
    assert folded == "а б"
    assert offsets == [1, 2, 5]
