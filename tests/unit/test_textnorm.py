"""Unit tests for char normalization of the clean text (research R-5)."""

from __future__ import annotations

import pytest

from docreader.textnorm import normalize_chars

SPACES = ["\u00a0", *(chr(c) for c in range(0x2000, 0x200B)), "\u202f", "\u205f", "\u3000", "\t"]


@pytest.mark.parametrize("ch", SPACES, ids=lambda c: f"U+{ord(c):04X}")
def test_space_variants_become_space(ch: str) -> None:
    assert normalize_chars(f"а{ch}б") == "а б"


@pytest.mark.parametrize("ch", ["\u2010", "\u2011", "\u2012", "\u2212"], ids=lambda c: f"U+{ord(c):04X}")
def test_hyphens_and_minus_become_hyphen(ch: str) -> None:
    assert normalize_chars(f"а{ch}б") == "а-б"


@pytest.mark.parametrize("ch", ["\u201e", "\u201c", "\u201d", "\u201f", "\u2033"])
def test_double_quotes_become_ascii(ch: str) -> None:
    assert normalize_chars(f"{ch}а{ch}") == '"а"'


@pytest.mark.parametrize("ch", ["\u2018", "\u2019", "\u201a", "\u201b"])
def test_single_quotes_become_ascii(ch: str) -> None:
    assert normalize_chars(f"{ch}а{ch}") == "'а'"


def test_soft_hyphen_removed() -> None:
    assert normalize_chars("до\u00adговор") == "договор"


def test_space_runs_collapse_and_edges_strip() -> None:
    assert normalize_chars("  а   б \u00a0\u00a0 в  ") == "а б в"


def test_newlines_kept_spaces_collapsed_per_line() -> None:
    assert normalize_chars(" а  б \n  в   г ") == "а б\nв г"


@pytest.mark.parametrize(
    "text",
    [
        "а–б",
        "а—б",
        "«Договор»",
        "ёЁ",
        "CKA\u0412",  # Latin C, K, A + Cyrillic Ve
        "\u0421\u041a\u0410\u0412",  # all Cyrillic
        "123 4567",
        "№ 5",
        "«___» __________ 2024 г.",
        "а\ufffeб",
        "а\ufffdб",
    ],
)
def test_must_not_change(text: str) -> None:
    assert normalize_chars(text) == text


def test_combined_line() -> None:
    src = "\u00a0\u201eДо\u00adговор\u201d\u2009№\u00a05 \u2012 \u2018а\u2019  от «___»  2024\u202fг. — CKAВ\ufffe"
    assert normalize_chars(src) == "\"Договор\" № 5 - 'а' от «___» 2024 г. — CKAВ\ufffe"
