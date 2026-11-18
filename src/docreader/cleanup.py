"""Clean document text and the map «text range → page line» (R-4, R-6).

Pure functions over `pagetext.Line` lists; no database, no PDF.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from docreader.pagetext import Line

# Roles that go into the clean document text (R-4).
TEXT_ROLES = frozenset({"body", "rotated"})


@dataclass(frozen=True)
class Span:
    """`[start, end)` of the document text comes from line `line_index` of `page_number`."""

    start: int
    end: int
    page_number: int
    line_index: int


class DocumentText(NamedTuple):
    text: str
    spans: list[Span]
    sha256: str
    read_pages: int


def build_document_text(pages: Sequence[tuple[int, Sequence[Line]]]) -> DocumentText:
    """Join the lines of all pages (page number, lines in reading order) (task T014)."""
    parts: list[str] = []
    spans: list[Span] = []
    read_pages = 0
    position = 0
    for page_number, lines in pages:
        if any(line.text for line in lines):
            read_pages += 1
        for line in lines:
            if line.role not in TEXT_ROLES or not line.text:
                continue
            if parts:
                position += 1  # the "\n" separator
            spans.append(Span(position, position + len(line.text), page_number, line.index))
            parts.append(line.text)
            position += len(line.text)
    text = "\n".join(parts)
    return DocumentText(text, spans, hashlib.sha256(text.encode("utf-8")).hexdigest(), read_pages)
