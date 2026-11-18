"""Char normalization of the clean text (research R-5).

Composes decomposed letters first (NFC): some PDFs spell «й» as «и» + U+0306 and
«ё» as «е» + U+0308, which would not match quotes or a dictionary.

Then replaces typographic variants of spaces, hyphens and quotes with plain ASCII
characters, drops soft hyphens and collapses runs of spaces, so that a quote
from the contract matches the clean text verbatim.

The comparison rules (yo -> ye, dashes, quotes, Latin look-alikes -> Cyrillic, line
breaks) do not change the clean text: they live in `compare_form`, and `locate` finds
a quote in the text with them, so quotes and text are compared the same way.
"""

from __future__ import annotations

import re
import unicodedata

_SPACES = (
    ["\u00a0", "\u202f", "\u205f", "\u3000", "\t"]
    + [chr(c) for c in range(0x2000, 0x200B)]
)

_TABLE: dict[int, str | None] = {}
_TABLE.update({ord(c): " " for c in _SPACES})
_TABLE.update({ord(c): "-" for c in "\u2010\u2011\u2012\u2212"})
_TABLE.update({ord(c): '"' for c in "\u201e\u201c\u201d\u201f\u2033"})
_TABLE.update({ord(c): "'" for c in "\u2018\u2019\u201a\u201b"})
_TABLE[0x00AD] = None

_SPACE_RUN = re.compile(r" {2,}")


def normalize_chars(text: str) -> str:
    """Compose to NFC, normalize spaces, hyphens and quotes; newlines are kept as is."""
    translated = unicodedata.normalize("NFC", text).translate(_TABLE)
    return "\n".join(
        _SPACE_RUN.sub(" ", line).strip(" ") for line in translated.split("\n")
    )


# --- comparison form and quote locating (tech-context «Договорённости между этапами») ---

_COMPARE_TABLE: dict[int, str | None] = dict(_TABLE)
_COMPARE_TABLE.update({ord("ё"): "е", ord("Ё"): "Е"})
_COMPARE_TABLE.update({ord(c): "-" for c in "–—"})
_COMPARE_TABLE.update({ord(c): '"' for c in "«»"})

# Latin letters that look like Cyrillic ones; replaced only inside a word that has
# Cyrillic letters («CKAВ» with Latin C, K, A), never in Latin words or identifiers.
_LOOKALIKES = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")


def _is_cyrillic(ch: str) -> bool:
    return "Ѐ" <= ch <= "ӿ"


def _cyrillic_words(text: str) -> list[bool]:
    """For every char: True when it is inside a run of letters that has a Cyrillic one."""
    marks = [False] * len(text)
    i = 0
    while i < len(text):
        if not text[i].isalpha():
            i += 1
            continue
        j = i
        while j < len(text) and text[j].isalpha():
            j += 1
        if any(_is_cyrillic(ch) for ch in text[i:j]):
            marks[i:j] = [True] * (j - i)
        i = j
    return marks


def compare_form(text: str) -> tuple[str, list[int]]:
    """The form in which quotes are compared with the text, and where each char came from.

    Rules: the clean-text rules of `normalize_chars` (except NFC, which changes length:
    `text` must already be NFC, as the clean text is), any run of whitespace including
    line breaks → one space, «ё» → «е», «–»/«—» → «-», «»» → «"», Latin look-alikes →
    Cyrillic inside Cyrillic words. `offsets[i]` is the index in `text` of folded char `i`.
    """
    in_cyrillic = _cyrillic_words(text)
    chars: list[str] = []
    offsets: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace() or ch in _SPACES:
            if chars and chars[-1] != " ":
                chars.append(" ")
                offsets.append(i)
            continue
        mapped = ch.translate(_COMPARE_TABLE)
        if not mapped:
            continue  # soft hyphen
        if in_cyrillic[i]:
            mapped = mapped.translate(_LOOKALIKES)
        chars.append(mapped)
        offsets.append(i)
    if chars and chars[-1] == " ":
        chars.pop()
        offsets.pop()
    return "".join(chars), offsets


def locate(text: str, phrase: str) -> list[tuple[int, int]]:
    """`[start, end)` in `text` of every occurrence of `phrase` in the comparison form.

    Non-overlapping, left to right. The one function for `text --find`, the program
    check of quotes (principle III) and highlighting: a quote across a line or page
    break is found, and the offsets point into the original `text`.
    """
    needle, _ = compare_form(unicodedata.normalize("NFC", phrase))
    if not needle:
        return []
    haystack, offsets = compare_form(text)
    found: list[tuple[int, int]] = []
    pos = haystack.find(needle)
    while pos != -1:
        last = pos + len(needle) - 1
        found.append((offsets[pos], offsets[last] + 1))
        pos = haystack.find(needle, pos + len(needle))
    return found


def is_empty_phrase(phrase: str) -> bool:
    """True when nothing is left of `phrase` to search for."""
    return not compare_form(unicodedata.normalize("NFC", phrase))[0]
