"""Ranking rules of the search (feature 08, research R-1, R-4; tasks T004, T017).

Written by the main session: BM25, the fusion and the order of equal scores are
decision rules (CLAUDE.md «Model routing»).
"""

import math

import pytest

from docreader.ranking import bm25, rrf


def key(doc: str, ordinal: int) -> tuple[str, int]:
    return (doc, ordinal)


# --- bm25 -----------------------------------------------------------------------------


def test_rare_word_outweighs_common_word() -> None:
    docs = [
        (key("D-0001", 0), ["договор", "оплата"]),
        (key("D-0001", 1), ["договор", "поставка"]),
        (key("D-0001", 2), ["договор", "приемка"]),
        (key("D-0001", 3), ["договор", "гарантия"]),
    ]
    scores = dict(bm25(["договор", "оплата"], docs))
    assert next(iter(dict(bm25(["договор", "оплата"], docs)))) == key("D-0001", 0)
    assert scores[key("D-0001", 0)] > scores[key("D-0001", 1)]
    # «оплата» alone scores more than «договор» alone in the same passage
    only_rare = dict(bm25(["оплата"], docs))[key("D-0001", 0)]
    only_common = dict(bm25(["договор"], docs))[key("D-0001", 0)]
    assert only_rare > only_common


def test_longer_passage_with_same_word_scores_lower() -> None:
    docs = [
        (key("D-0001", 0), ["неустойка", "день"]),
        (key("D-0001", 1), ["неустойка"] + ["слово"] * 20),
        (key("D-0001", 2), ["приемка"]),
    ]
    ranked = bm25(["неустойка"], docs)
    assert [k for k, _ in ranked] == [key("D-0001", 0), key("D-0001", 1)]
    assert ranked[0][1] > ranked[1][1]


def test_number_matches_only_whole() -> None:
    docs = [
        (key("D-0001", 0), ["договор", "дп-17/2026"]),
        (key("D-0001", 1), ["дп", "17"]),
    ]
    assert [k for k, _ in bm25(["дп-17/2026"], docs)] == [key("D-0001", 0)]


def test_only_positive_scores_returned() -> None:
    docs = [(key("D-0001", 0), ["оплата"]), (key("D-0001", 1), ["приемка"])]
    assert [k for k, _ in bm25(["оплата"], docs)] == [key("D-0001", 0)]


def test_equal_scores_by_document_then_ordinal() -> None:
    docs = [
        (key("D-0003", 1), ["оплата"]),
        (key("D-0001", 5), ["оплата"]),
        (key("D-0001", 2), ["оплата"]),
        (key("D-0002", 0), ["оплата"]),
        (key("D-0002", 9), ["приемка"]),
    ]
    assert [k for k, _ in bm25(["оплата"], docs)] == [
        key("D-0001", 2), key("D-0001", 5), key("D-0002", 0), key("D-0003", 1)
    ]


def test_no_terms_or_no_docs() -> None:
    assert bm25([], [(key("D-0001", 0), ["оплата"])]) == []
    assert bm25(["оплата"], []) == []


def test_repeated_word_in_passage_raises_score_with_saturation() -> None:
    docs = [
        (key("D-0001", 0), ["оплата", "x"]),
        (key("D-0001", 1), ["оплата", "оплата"]),
        (key("D-0001", 2), ["y", "z"]),
    ]
    scores = dict(bm25(["оплата"], docs))
    assert scores[key("D-0001", 1)] > scores[key("D-0001", 0)]
    assert scores[key("D-0001", 1)] < 2 * scores[key("D-0001", 0)]


def test_formula_on_one_case() -> None:
    # N = 2, df = 1, avgdl = 1.5, |d| = 1, tf = 1, k1 = 1.2, b = 0.75
    docs = [(key("D-0001", 0), ["оплата"]), (key("D-0001", 1), ["x", "y"])]
    idf = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    expected = idf * (1 * 2.2) / (1 + 1.2 * (1 - 0.75 + 0.75 * 1 / 1.5))
    ((_, score),) = bm25(["оплата"], docs)
    assert score == pytest.approx(expected)


# --- rrf -----------------------------------------------------------------------------


def test_found_by_both_above_found_by_one_at_same_place() -> None:
    a, b, c = key("D-0001", 0), key("D-0001", 1), key("D-0001", 2)
    fused = rrf([[a, b], [c, a]], k=60)
    order = [k for k, _, _ in fused]
    assert order[0] == a
    # b (words, place 2) and c (meaning, place 1): c is higher
    assert order.index(c) < order.index(b)


def test_places_reported_per_list() -> None:
    a, b, c = key("D-0001", 0), key("D-0001", 1), key("D-0002", 0)
    fused = {k: places for k, _, places in rrf([[a, b], [c, a]], k=60)}
    assert fused[a] == [1, 2]
    assert fused[b] == [2, None]
    assert fused[c] == [None, 1]


def test_score_formula_and_k() -> None:
    a = key("D-0001", 0)
    ((_, score60, _),) = rrf([[a], [a]], k=60)
    ((_, score1, _),) = rrf([[a], [a]], k=1)
    assert score60 == pytest.approx(2 / 61)
    assert score1 == pytest.approx(2 / 2)


def test_equal_fused_scores_by_document_then_ordinal() -> None:
    a, b = key("D-0002", 0), key("D-0001", 3)
    order = [k for k, _, _ in rrf([[a], [b]], k=60)]
    assert order == [b, a]


def test_empty_lists() -> None:
    assert rrf([[], []], k=60) == []
    a = key("D-0001", 0)
    assert [k for k, _, _ in rrf([[], [a]], k=60)] == [a]
