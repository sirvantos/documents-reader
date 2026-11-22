"""The part of a contract's text shown to the language model (feature 05, research R-4).

Preamble, main text and requisites: everything before the first line inside the tail
(the requisites section and what follows, feature 04) that starts with the word
«Приложение». Without a tail, or without such a line in it, the whole text is shown.
The same expression decided the numbers of the survey (`scripts/survey_fields.py`).
"""

from __future__ import annotations

import re

# A line that starts with the word «Приложение» (any case); «Приложения: …» is a list of
# appendices, not an appendix, and does not match.
APPENDIX_LINE = re.compile(r"(?m)^\s*приложение(?:\s|$)", re.IGNORECASE)


def shown_end(text: str, tail_start: int | None) -> int:
    """The end (exclusive) of the shown part of `text`; `tail_start` — start of the tail."""
    if tail_start is None:
        return len(text)
    match = APPENDIX_LINE.search(text, tail_start)
    if match is None:
        return len(text)
    # `\s*` may start on an empty line before the appendix line: the boundary is the
    # start of the line where the match begins, which is never before the tail
    return max(match.start(), tail_start)
