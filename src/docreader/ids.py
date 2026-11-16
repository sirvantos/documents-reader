"""Document identifiers of the form D-0001 (research R-3)."""

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
