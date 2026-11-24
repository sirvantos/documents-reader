"""Ranking rules of the search (feature 08, research R-1, R-4; data-model.md).

Pure functions over plain values, no database and no model. Critical (decision rules,
CLAUDE.md «Model routing»): BM25 over the stored word forms, the fusion by places
(reciprocal rank fusion) and the order of equal scores, which makes a repeated search
give the same list (SC-004).

A passage is named by `PassageKey` = (document id, ordinal); the same key orders equal
scores: by document, then by the passage order in the document.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence

PassageKey = tuple[str, int]


def bm25(
    terms: Sequence[str],
    docs: Sequence[tuple[PassageKey, list[str]]],
    k1: float = 1.2,
    b: float = 0.75,
) -> list[tuple[PassageKey, float]]:
    """BM25 scores of `docs` for the query `terms` (research R-1).

    The statistics — number of passages, mean length, in how many passages a word
    occurs — are taken over `docs`, the scope of the search. Only passages with a score
    above zero are returned, by score descending, equal scores by key.
    """
    wanted = list(dict.fromkeys(terms))
    if not wanted or not docs:
        return []
    n = len(docs)
    mean_len = sum(len(words) for _, words in docs) / n or 1.0
    counts = [Counter(words) for _, words in docs]
    df = {t: sum(1 for c in counts if t in c) for t in wanted}
    idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in wanted if df[t]}
    scored: list[tuple[PassageKey, float]] = []
    for (passage, words), count in zip(docs, counts, strict=True):
        norm = k1 * (1 - b + b * len(words) / mean_len)
        score = 0.0
        for t, weight in idf.items():
            tf = count.get(t, 0)
            if tf:
                score += weight * tf * (k1 + 1) / (tf + norm)
        if score > 0:
            scored.append((passage, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def rrf(
    lists: Sequence[Sequence[PassageKey]], k: int
) -> list[tuple[PassageKey, float, list[int | None]]]:
    """Fuse ranked lists by places (research R-4): score `Σ 1 / (k + place)`.

    Places count from 1; the places of a passage in each list are returned with it,
    `None` where a list does not hold it. By score descending, equal scores by key.
    """
    places: dict[PassageKey, list[int | None]] = {}
    for i, ranked in enumerate(lists):
        for place, passage in enumerate(ranked, start=1):
            places.setdefault(passage, [None] * len(lists))[i] = place
    fused = [
        (passage, sum(1 / (k + p) for p in where if p is not None), where)
        for passage, where in places.items()
    ]
    fused.sort(key=lambda item: (-item[1], item[0]))
    return fused
