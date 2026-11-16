"""Unit tests for the page kind rule (task T030, research R-2) and report warnings."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from docreader.intake import page_ranges, page_warnings
from docreader.pdfpages import PageMetrics, classify

DEFAULT = SimpleNamespace(text_min_chars=20, full_image_coverage=0.85)


def kind(chars: int, coverage: float, thresholds=DEFAULT) -> str:
    return classify(PageMetrics(1, chars, coverage, None), thresholds)


@pytest.mark.parametrize("coverage", [0.0, 0.5, 1.0])
def test_few_chars_is_scan_regardless_of_coverage(coverage):
    assert kind(19, coverage) == "scan"


def test_enough_chars_and_small_coverage_is_text():
    assert kind(20, 0.84) == "text"


def test_enough_chars_and_full_coverage_is_scan_with_text():
    assert kind(20, 0.85) == "scan_with_text"
    assert kind(500, 1.0) == "scan_with_text"


def test_blank_page_is_scan():
    assert kind(0, 0.0) == "scan"


def test_custom_thresholds_are_respected():
    custom = SimpleNamespace(text_min_chars=5, full_image_coverage=0.5)
    assert kind(4, 0.0, custom) == "scan"
    assert kind(5, 0.49, custom) == "text"
    assert kind(5, 0.5, custom) == "scan_with_text"
    # default thresholds would call these differently
    assert kind(10, 0.6, DEFAULT) == "scan"
    assert kind(10, 0.6, custom) == "scan_with_text"


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        ([1, 2, 3, 7, 9, 10], "1–3, 7, 9, 10"),
        ([3, 7], "3, 7"),
        ([1, 2], "1, 2"),
        (list(range(1, 13)), "1–12"),
    ],
)
def test_page_ranges(numbers, expected):
    assert page_ranges(numbers) == expected


def codes(warnings):
    return [w["code"] for w in warnings]


def test_page_warnings_lists_scan_pages():
    warnings = page_warnings(["text", "scan", "text", "scan"], large_file_pages=200)
    assert codes(warnings) == ["scan_pages"]
    assert warnings[0]["pages"] == [2, 4]
    assert warnings[0]["message"] == "страницы-сканы на первом этапе не читаются: стр. 2, 4"


def test_page_warnings_lists_scan_with_text_pages():
    warnings = page_warnings(["scan_with_text", "scan_with_text"], large_file_pages=200)
    assert codes(warnings) == ["scan_with_text_pages"]
    assert warnings[0]["pages"] == [1, 2]
    assert warnings[0]["message"] == (
        "текст стр. 1, 2 получен распознаванием и может содержать ошибки"
    )


def test_page_warnings_none_for_text_only():
    assert page_warnings(["text"] * 3, large_file_pages=3) == []


def test_large_file_only_above_threshold():
    assert page_warnings(["text"] * 5, large_file_pages=5) == []
    warnings = page_warnings(["text"] * 6, large_file_pages=5)
    assert codes(warnings) == ["large_file"]
    assert warnings[0]["message"] == "6 страниц — больше 5"
