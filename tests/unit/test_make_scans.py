"""Tests of the synthetic scan generator (task T011, research R-13).

The generator writes only under pytest tmp_path. Each variant is checked against the page
kind rule of docreader.pdfpages with the default thresholds and against its truth file.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pypdfium2 as pdfium
import pytest

from docreader.ocr import ink_share, render_page
from docreader.pdfpages import analyse_pdf, classify
from tests.synthetic import make_scans as ms
from tests.synthetic.make_pdfs import CONTRACT_RU_PAGES

DEFAULT = SimpleNamespace(text_min_chars=20, full_image_coverage=0.85)
PAGE_BOX = (0.0, 0.0, 595.0, 842.0)

VARIANTS: dict[str, tuple[Callable[[Path], Path], str]] = {
    "clean": (ms.make_scan_clean, "scan_clean.pdf"),
    "mixed": (ms.make_scan_mixed, "scan_mixed.pdf"),
    "faded_noisy": (ms.make_scan_faded_noisy, "scan_faded_noisy.pdf"),
    "page_rotate_90": (ms.make_scan_page_rotate_90, "scan_page_rotate_90.pdf"),
    "requisites_two_columns": (
        ms.make_scan_requisites_two_columns,
        "scan_requisites_two_columns.pdf",
    ),
    "rotated_90": (ms.make_scan_rotated_90, "scan_rotated_90.pdf"),
    "rotated_180": (ms.make_scan_rotated_180, "scan_rotated_180.pdf"),
    "skew_3deg": (ms.make_scan_skew_3deg, "scan_skew_3deg.pdf"),
    "table": (ms.make_scan_table, "scan_table.pdf"),
    "stamp_over_text": (ms.make_scan_stamp_over_text, "scan_stamp_over_text.pdf"),
    "stamp_only": (ms.make_scan_stamp_only, "scan_stamp_only.pdf"),
    "blank": (ms.make_scan_blank, "scan_blank.pdf"),
}
NEW_VARIANTS = (
    "rotated_90",
    "rotated_180",
    "skew_3deg",
    "table",
    "stamp_over_text",
    "stamp_only",
    "blank",
)
EMPTY_TRUTH = ("stamp_only", "blank")  # pages without any text to recognise
BLANK_MAX_INK_SHARE = 0.003  # docreader.ocr.ink_share limit of a blank page (research R-10)


def _truth(pdf: Path) -> dict:
    return json.loads(pdf.with_name(f"{pdf.stem}.truth.json").read_text(encoding="utf-8"))


def _generate(name: str, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    make, filename = VARIANTS[name]
    return make(folder / filename)


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Every variant generated once for the module (rendering is the slow part)."""
    folder = tmp_path_factory.mktemp("scans")
    return {name: _generate(name, folder / name) for name in VARIANTS}


@pytest.mark.parametrize("name", list(VARIANTS))
def test_writes_pdf_and_truth_with_version(name, generated):
    pdf = generated[name]
    assert pdf.exists() and pdf.read_bytes().startswith(b"%PDF-")
    truth = _truth(pdf)
    assert truth["generator_version"] == ms.SCAN_GENERATOR_VERSION == 2
    assert truth["variant"] == name
    assert [p["page"] for p in truth["pages"]] == list(range(1, len(truth["pages"]) + 1))
    assert all(p["kind"] in ("scan", "text") for p in truth["pages"])


@pytest.mark.parametrize("name", list(VARIANTS))
def test_page_kinds_follow_the_page_kind_rule(name, generated):
    pdf = generated[name]
    truth_pages = _truth(pdf)["pages"]
    metrics = analyse_pdf(pdf)
    assert len(metrics) == len(truth_pages)
    for page_metrics, page in zip(metrics, truth_pages, strict=True):
        assert classify(page_metrics, DEFAULT) == page["kind"], page


def test_clean_and_faded_are_all_scans(generated):
    for name in ("clean", "faded_noisy", "page_rotate_90", "requisites_two_columns"):
        assert {p["kind"] for p in _truth(generated[name])["pages"]} == {"scan"}
        assert {classify(m, DEFAULT) for m in analyse_pdf(generated[name])} == {"scan"}


def test_mixed_alternates_text_and_scan(generated):
    kinds = [p["kind"] for p in _truth(generated["mixed"])["pages"]]
    assert kinds == ["text", "scan", "text", "scan"]
    assert [classify(m, DEFAULT) for m in analyse_pdf(generated["mixed"])] == kinds


@pytest.mark.parametrize("name", list(VARIANTS))
def test_truth_boxes_lie_inside_the_page(name, generated):
    left0, bottom0, right0, top0 = PAGE_BOX
    for page in _truth(generated[name])["pages"]:
        if name not in EMPTY_TRUTH:
            assert page["lines"], page["page"]
        for line in page["lines"]:
            left, bottom, right, top = line["bbox"]
            assert left0 <= left < right <= right0, line
            assert bottom0 <= bottom < top <= top0, line


@pytest.mark.parametrize("name", list(VARIANTS))
def test_same_arguments_give_identical_bytes(name, tmp_path):
    first = _generate(name, tmp_path / "first")
    second = _generate(name, tmp_path / "second")
    assert first.read_bytes() == second.read_bytes()
    assert (
        first.with_name(f"{first.stem}.truth.json").read_bytes()
        == second.with_name(f"{second.stem}.truth.json").read_bytes()
    )


def test_contract_texts_in_reading_order(generated):
    for name, pages in (("clean", (0, 1)), ("faded_noisy", (0, 1))):
        truth_pages = _truth(generated[name])["pages"]
        for page, index in zip(truth_pages, pages, strict=True):
            texts = [line["text"] for line in page["lines"]]
            assert texts == list(CONTRACT_RU_PAGES[index])
    mixed_pages = _truth(generated["mixed"])["pages"]
    assert [line["text"] for line in mixed_pages[0]["lines"]] == list(CONTRACT_RU_PAGES[0])
    assert [line["text"] for line in mixed_pages[2]["lines"]] == list(CONTRACT_RU_PAGES[2])


def test_rotate_90_sets_the_page_rotation_and_keeps_truth_unrotated(generated):
    pdf = generated["page_rotate_90"]
    document = pdfium.PdfDocument(pdf.read_bytes())
    try:
        assert document[0].get_rotation() == 90  # degrees, as PDFium reports them
    finally:
        document.close()
    page = _truth(pdf)["pages"][0]
    # Unrotated space: the first line sits near the top of the A4 page, as drawn.
    _, _, _, top = page["lines"][0]["bbox"]
    assert top > PAGE_BOX[3] - 100


def test_requisites_read_left_column_first(generated):
    page = _truth(generated["requisites_two_columns"])["pages"][0]
    lines = page["lines"]
    texts = [line["text"] for line in lines]
    assert texts[0] == ms._REQ_HEADING
    body = lines[1:]  # the heading is also at the left margin
    left = [line for line in body if abs(line["bbox"][0] - ms._REQ_LEFT_X) < 1]
    right = [line for line in body if abs(line["bbox"][0] - ms._REQ_RIGHT_X) < 1]
    assert [line["text"] for line in left] == list(ms._REQ_CUSTOMER)
    assert [line["text"] for line in right] == list(ms._REQ_CONTRACTOR)
    # heading first, then the whole left column, then the whole right column
    assert texts == [ms._REQ_HEADING, *ms._REQ_CUSTOMER, *ms._REQ_CONTRACTOR]


@pytest.mark.parametrize("name", NEW_VARIANTS)
def test_new_variants_are_scans(name, generated):
    assert {p["kind"] for p in _truth(generated[name])["pages"]} == {"scan"}
    assert {classify(m, DEFAULT) for m in analyse_pdf(generated[name])} == {"scan"}


@pytest.mark.parametrize("name", EMPTY_TRUTH)
def test_empty_truth_for_stamp_only_and_blank(name, generated):
    pages = _truth(generated[name])["pages"]
    assert len(pages) == 1
    assert pages[0]["lines"] == []


def test_stamp_over_text_has_the_requisites_truth(generated):
    assert (
        _truth(generated["stamp_over_text"])["pages"]
        == _truth(generated["requisites_two_columns"])["pages"]
    )


def test_table_truth_is_row_by_row_cell_by_cell(generated):
    lines = _truth(generated["table"])["pages"][0]["lines"]
    assert [line["text"] for line in lines] == [cell for row in ms._TABLE_ROWS for cell in row]
    # the cells of one row share their top and bottom, and the amounts end at the right edge
    for row_index in range(len(ms._TABLE_ROWS)):
        row = lines[row_index * 3 : row_index * 3 + 3]
        assert len({line["bbox"][1] for line in row}) == 1
        assert len({line["bbox"][3] for line in row}) == 1


def test_turned_pages_store_the_turn_and_keep_truth_upright(generated):
    for name, turn in (("rotated_90", 90), ("rotated_180", 180)):
        pdf = generated[name]
        page = _truth(pdf)["pages"][0]
        assert page["turned"] == turn
        # the upright first line sits near the top of the page as drawn
        _, _, _, top = page["lines"][0]["bbox"]
        assert top > PAGE_BOX[3] - 100
    document = pdfium.PdfDocument(generated["rotated_90"].read_bytes())
    try:
        width, height = document[0].get_size()
        assert document[0].get_rotation() == 0
        assert width > height  # landscape A4: the turned picture fills it
    finally:
        document.close()
    document = pdfium.PdfDocument(generated["rotated_180"].read_bytes())
    try:
        width, height = document[0].get_size()
        assert width < height
    finally:
        document.close()
    assert "turned" not in _truth(generated["clean"])["pages"][0]


def _ink_share_at_100_dpi(pdf: Path) -> float:
    document = pdfium.PdfDocument(pdf.read_bytes())
    try:
        return ink_share(render_page(document[0], 100))
    finally:
        document.close()


def test_blank_page_has_little_ink(generated):
    assert _ink_share_at_100_dpi(generated["blank"]) < BLANK_MAX_INK_SHARE


def test_stamp_only_page_has_more_ink_than_a_blank_page(generated):
    assert _ink_share_at_100_dpi(generated["stamp_only"]) > BLANK_MAX_INK_SHARE


def test_main_writes_all_variants_and_contract(tmp_path):
    assert ms.main([str(tmp_path)]) == 0
    expected = {"contract_ru.pdf"}
    for name in VARIANTS:
        filename = VARIANTS[name][1]
        expected.add(filename)
        expected.add(filename.replace(".pdf", ".truth.json"))
    assert {p.name for p in tmp_path.iterdir()} == expected
