"""Dictionary forms of words for the word index (feature 07, research R-5).

One `pymorphy3` analyzer per process (shared with `values`) and `lemmatize`, which turns
a text into the space-joined dictionary forms of its words. Words that contain a digit
(contract numbers, clause numbers, document ids) are kept exactly as written.
"""

from __future__ import annotations

import re
from functools import cache
from typing import Any

# A word: letters and digits, with single inner "-", "/" or "." between them
# ("ДП-17/2026", "5.2.1", "D-0001"); a trailing dot ("3.1.") is not part of the word.
_WORD = re.compile(r"[^\W_]+(?:[-/.][^\W_]+)*")
_HAS_DIGIT = re.compile(r"\d")


@cache
def analyzer() -> Any:
    """The process-wide `pymorphy3.MorphAnalyzer` (the dictionary loads from disk once)."""
    import pymorphy3  # loads the dictionary package from disk; no network

    return pymorphy3.MorphAnalyzer()


def _fold_yo(text: str) -> str:
    return text.replace("ё", "е")


def _normal_form(word: str) -> str:
    folded = _fold_yo(word.lower())
    # pymorphy3 may answer with «ё» again («елка» -> «ёлка»), so fold the result too.
    return _fold_yo(analyzer().parse(folded)[0].normal_form)


def lemmatize(text: str) -> str:
    """Dictionary forms of the words of `text`, joined by single spaces in text order."""
    forms = [
        word if _HAS_DIGIT.search(word) else _normal_form(word)
        for word in (m.group() for m in _WORD.finditer(text))
    ]
    return " ".join(forms)


# Parts of speech that carry no meaning of their own in a search query (research R-2).
_FUNCTION_POS = frozenset({"PREP", "CONJ", "PRCL", "INTJ"})


def _is_function_word(word: str) -> bool:
    return analyzer().parse(_fold_yo(word.lower()))[0].tag.POS in _FUNCTION_POS


def query_terms(query: str) -> list[str]:
    """The words of a search query as the word index stores them (feature 08, R-1, R-2).

    The same dictionary forms as `lemmatize`, lower-cased, in order, without repeats and
    without prepositions, conjunctions, particles and interjections. Words with a digit
    are kept as written, lower-cased.
    """
    terms: list[str] = []
    seen: set[str] = set()
    for match in _WORD.finditer(query):
        word = match.group()
        if _HAS_DIGIT.search(word):
            term = word.lower()
        elif _is_function_word(word):
            continue
        else:
            term = _normal_form(word)
        if term not in seen:
            seen.add(term)
            terms.append(term)
    return terms
