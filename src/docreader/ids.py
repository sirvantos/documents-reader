"""Document identifiers of the form D-0001 (research R-3) and clause identifiers D-0001/5.2."""

import re

from docreader.errors import UserError


def format_document_id(seq: int) -> str:
    if seq < 1:
        raise ValueError(f"seq must be >= 1, got {seq}")
    return f"D-{seq:04d}"


def parse_document_id(text: str) -> int:
    stripped = text.strip()
    digits = stripped[2:]
    if (
        stripped[:2].upper() == "D-"
        and digits.isascii()
        and digits.isdigit()
        and int(digits) >= 1
    ):
        return int(digits)
    raise UserError(f"Неверный идентификатор документа «{text}» — ожидается вид D-0001")


# --- clause identifiers D-0001/5.2 (feature 04, research R-5) -------------------------

PREAMBLE_KEY = "преамбула"
TAIL_KEY = "реквизиты"
_NAMED_KEYS = frozenset({PREAMBLE_KEY, TAIL_KEY})
_NUMBER_KEY = re.compile(r"[1-9]\d{0,2}(?:\.[1-9]\d{0,2})*")


def clause_key(number: tuple[int, ...]) -> str:
    """The key of a section or clause: `(5, 2)` → `5.2`."""
    if not number:
        raise ValueError("a clause number has at least one part")
    return ".".join(str(n) for n in number)


def format_clause_id(doc_id: str, key: str) -> str:
    return f"{doc_id}/{key}"


def parse_clause_id(text: str) -> tuple[int, str]:
    """`D-0001/5.2` → (1, "5.2"); the key is `преамбула`, `реквизиты` or a number."""
    stripped = text.strip()
    doc_part, sep, key = stripped.partition("/")
    if sep and (key in _NAMED_KEYS or _NUMBER_KEY.fullmatch(key)):
        try:
            return parse_document_id(doc_part), key
        except UserError:
            pass
    raise UserError(f"Неверный идентификатор пункта «{text}» — ожидается вид D-0001/5.2")
