"""Char normalization of the clean text (research R-5).

Composes decomposed letters first (NFC): some PDFs spell «й» as «и» + U+0306 and
«ё» as «е» + U+0308, which would not match quotes or a dictionary.

Then replaces typographic variants of spaces, hyphens and quotes with plain ASCII
characters, drops soft hyphens and collapses runs of spaces, so that a quote
from the contract matches the clean text verbatim.

The feature 02 comparison rules (yo -> ye, Latin look-alikes -> Cyrillic) are
deliberately not here. They will be a separate function in this module, so that
quotes and text are normalized the same way.
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
