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
