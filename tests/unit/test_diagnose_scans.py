"""The scan diagnosis prints only numbers and ids, and parses the real flag reasons."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from docreader.quality import layout_flag

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "diagnose_scans.py"
spec = importlib.util.spec_from_file_location("diagnose_scans", SCRIPT)
assert spec is not None and spec.loader is not None
diagnose = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = diagnose  # @dataclass looks its module up there
spec.loader.exec_module(diagnose)


def reason(rotated: int, unresolved: int) -> str:
    flag = layout_flag(rotated_lines=rotated, unresolved_lines=unresolved)
    assert flag is not None
    return flag.reason


@pytest.mark.parametrize(
    ("rotated", "unresolved"), [(1, 0), (2, 0), (5, 0), (11, 0), (0, 3), (0, 21), (4, 12)]
)
def test_parses_reasons_written_by_layout_flag(rotated: int, unresolved: int) -> None:
    assert diagnose.parse_layout_reason(reason(rotated, unresolved)) == (rotated, unresolved)


def test_no_reason_is_zero() -> None:
    assert diagnose.parse_layout_reason(None) == (0, 0)


def test_buckets() -> None:
    assert diagnose.buckets([1, 3, 4, 7, 25]) == "1–2: 1, 3–5: 2, 6–10: 1, > 20: 1"
    assert diagnose.buckets([]) == "—"


def test_reading_order_summary_splits_sources_and_rules() -> None:
    rows = [
        ("D-0001", "pdf", 40, None),
        ("D-0001", "pdf", 40, reason(2, 0)),
        ("D-0002", "recognized", 30, reason(0, 6)),
        ("D-0002", "recognized", 30, reason(1, 3)),
        ("D-0002", "recognized", 30, None),
    ]
    text = "\n".join(diagnose.reading_order_lines(rows))
    assert "текстовый слой PDF: страниц 2, с флагом 1 (50.0%)" in text
    assert "распознанные сканы: страниц 3, с флагом 2 (66.7%)" in text
    assert "только повёрнутый текст 0, только строки из частей 1, оба 1" in text
    assert "строк из частей на странице: 3–5: 1, 6–10: 1" in text
    # the share ranks documents: D-0002 (2 of 3) before D-0001 (1 of 2)
    assert text.index("D-0002: 3, 2") < text.index("D-0001: 2, 1")


def page(number: int, **kw: object) -> object:
    values: dict = {
        "page": number,
        "size_pt": (595.3, 841.9),
        "rotate": 0,
        "image_px": (1654, 2339),
        "image_dpi": 200.0,
        "image_bpp": 1,
        "image_filters": ("CCITTFaxDecode",),
        "ink": 0.08,
        "stored_turn": 0,
        "stored_quality": 0.15,
        "osd_deg": 90,
        "osd_conf": 5.2,
        "osd_script": "Cyrillic",
        "osd_script_conf": 1.1,
        "quality": {0: 0.15, 90: 0.91, 180: 0.1, 270: 0.2},
        "score": {0: 0.05, 90: 0.88, 180: 0.02, 270: 0.04},
        "line_count": {0: 12, 90: 40, 180: 10, 270: 9},
        "text_height_px": 31.0,
        "vertical_share": 0.0,
        "extra_quality": 0.92,
    }
    values.update(kw)
    return diagnose.PageDiag(**values)


def test_best_turn_is_the_highest_quality_and_marked() -> None:
    p = page(3)
    assert p.best_turn == 90
    line = diagnose.page_line(p)
    assert "качество/рус. 0:0.15/0.05 90:0.91/0.88* 180:0.10/0.02 270:0.20/0.04" in line
    assert "1654×2339 px, 200 dpi, 1 бит, CCITTFaxDecode" in line
    assert "OSD 90° ув. 5.2, Cyrillic 1.1" in line
    assert "в базе 0°/0.15" in line


def test_a_tie_keeps_the_stored_turn() -> None:
    # Tesseract reads a quarter-turned page by itself: 0° and 270° give the same quality
    p = page(1, stored_turn=270, stored_quality=0.96,
             quality={0: 0.958, 90: 0.19, 180: 0.23, 270: 0.962})
    assert p.best_turn == 270
    assert p.gain is not None and abs(p.gain) < 0.01


def test_best_turn_without_any_quality_is_the_stored_turn() -> None:
    assert page(1, stored_turn=180, quality={}).best_turn == 180
    assert page(1, stored_turn=None, quality={}).best_turn == 0


def test_document_summary_counts_turns_and_osd() -> None:
    pages = [
        page(1),
        page(2, osd_deg=0, osd_conf=0.4),  # below the OSD cut: no answer
        page(3, quality={0: 0.2, 90: 0.1, 180: 0.1, 270: 0.1}),  # best 0° = stored, no gain
    ]
    text = "\n".join(diagnose.document_lines("D-0056", pages, 300, 400))
    assert "Документ D-0056: страниц-сканов 3, dpi 300, доп. dpi 400" in text
    assert "OSD: {'90°': 2, 'нет ответа': 1}" in text
    assert "лучший поворот по качеству: {'90°': 2, '0°': 1}" in text
    assert "другой поворот поднял бы качество на ≥ 0.10: 2" in text
    assert text.count("  стр. ") == 3


def test_document_without_scans() -> None:
    assert diagnose.document_lines("D-0001", [], 300, 0)[-1] == "  страниц-сканов нет"


def test_page_without_image_or_osd() -> None:
    line = diagnose.page_line(
        page(1, image_px=None, image_dpi=None, image_bpp=None, image_filters=(),
             osd_deg=None, osd_conf=None, stored_turn=None, errors=["OSD RuntimeError"])
    )
    assert "картинки нет" in line and "OSD нет ответа" in line
    assert "в базе —" in line and "ошибки: OSD RuntimeError" in line
