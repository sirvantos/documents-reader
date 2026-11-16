"""File type detection by content (research.md R-5)."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HEAD_SIZE = 1024

REASON_HIDDEN = "скрытый или служебный файл"
REASON_EMPTY = "пустой файл"
REASON_WORD = "формат не поддерживается: документ Word — сохраните его в PDF"
REASON_IMAGE = "формат не поддерживается: изображение — сохраните документ в PDF"
REASON_UNSUPPORTED = "формат не поддерживается"

REASONS: dict[str, str] = {
    "hidden": REASON_HIDDEN,
    "empty": REASON_EMPTY,
    "word": REASON_WORD,
    "image": REASON_IMAGE,
    "unsupported": REASON_UNSUPPORTED,
}

_OLE_HEADER = bytes.fromhex("D0CF11E0A1B11AE1")
_ZIP_HEADER = b"PK\x03\x04"
_IMAGE_HEADERS = (
    b"\xff\xd8\xff",
    b"\x89PNG\r\n\x1a\n",
    b"II*\x00",
    b"MM\x00*",
)


@dataclass(frozen=True)
class SniffResult:
    kind: Literal["pdf", "rejected"]
    reason_code: str | None = None
    reason: str | None = None


def _rejected(code: str) -> SniffResult:
    return SniffResult("rejected", code, REASONS[code])


def _zip_has_word_dir(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return any(name.startswith("word/") for name in archive.namelist())
    except (zipfile.BadZipFile, OSError):
        return False


def sniff(path: Path) -> SniffResult:
    path = Path(path)
    if path.name.startswith("."):
        return _rejected("hidden")
    if path.stat().st_size == 0:
        return _rejected("empty")
    with path.open("rb") as f:
        head = f.read(HEAD_SIZE)
    if b"%PDF-" in head:
        return SniffResult("pdf")
    if head.startswith(_OLE_HEADER):
        return _rejected("word")
    if head.startswith(_ZIP_HEADER):
        if path.name.lower().endswith(".docx") or _zip_has_word_dir(path):
            return _rejected("word")
        return _rejected("unsupported")
    if head.startswith(_IMAGE_HEADERS):
        return _rejected("image")
    return _rejected("unsupported")
