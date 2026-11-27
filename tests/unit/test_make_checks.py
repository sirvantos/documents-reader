"""Tests of the synthetic check contracts (feature 06, T006).

The generator writes only under pytest tmp_path. Each file is checked for its key lines in
the text layer; line breaks made by the generator's wrapping are normalised to spaces.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from tests.synthetic.make_pdfs import CHECK_GENERATOR_VERSION, make_check_contracts

FILES = (
    "check-clean.pdf",
    "check-words.pdf",
    "check-vat.pdf",
    "check-rate10.pdf",
    "check-exempt.pdf",
    "check-zero.pdf",
    "check-date.pdf",
    "check-same.pdf",
    "check-noamount.pdf",
)

CLEAN_PRICE = (
    "2.1. Цена Договора составляет 1 000 000 (один миллион) рублей 00 копеек без учёта НДС, "
    "НДС (20%) — 200 000 (двести тысяч) рублей 00 копеек, всего с учётом НДС "
    "1 200 000 (один миллион двести тысяч) рублей 00 копеек."
)

KEY_LINES: dict[str, tuple[str, ...]] = {
    "check-clean.pdf": (
        "ДОГОВОР ПОДРЯДА № К-21/2026",
        "Общество с ограниченной ответственностью «Альфа» (ООО «Альфа»), "
        "именуемое в дальнейшем «Заказчик»",
        "2. Цена Договора",
        CLEAN_PRICE,
        "5. Срок действия Договора",
        "5.1. Договор вступает в силу с даты подписания и действует до «31» декабря 2027 г.",
    ),
    "check-words.pdf": (
        "2.1. Цена Договора составляет 1 000 000 (один миллион сто тысяч) рублей 00 копеек "
        "без учёта НДС, НДС (20%) — 200 000 (двести тысяч) рублей 00 копеек, всего с учётом НДС "
        "1 200 000 (один миллион двести тысяч) рублей 00 копеек.",
    ),
    "check-vat.pdf": (
        "2.1. Цена Договора составляет 1 000 000 (один миллион) рублей 00 копеек без учёта НДС, "
        "НДС (20%) — 250 000 (двести пятьдесят тысяч) рублей 00 копеек, всего с учётом НДС "
        "1 250 000 (один миллион двести пятьдесят тысяч) рублей 00 копеек.",
    ),
    "check-rate10.pdf": (
        "2.1. Цена Договора составляет 1 000 000 (один миллион) рублей 00 копеек без учёта НДС, "
        "НДС (10%) — 100 000 (сто тысяч) рублей 00 копеек, всего с учётом НДС "
        "1 100 000 (один миллион сто тысяч) рублей 00 копеек.",
    ),
    "check-exempt.pdf": (
        "2.1. Цена Договора составляет 900 000 (девятьсот тысяч) рублей 00 копеек, "
        "НДС не облагается.",
    ),
    "check-zero.pdf": (
        "2.1. Цена Договора составляет 0 (ноль) рублей 00 копеек без учёта НДС, "
        "НДС (20%) — 0 (ноль) рублей 00 копеек, всего с учётом НДС 0 (ноль) рублей 00 копеек.",
    ),
    "check-date.pdf": (
        "5.1. Договор вступает в силу с даты подписания и действует до «31» декабря 2045 г.",
    ),
    "check-same.pdf": (
        "Общество с ограниченной ответственностью «Альфа» (ООО «Альфа»), "
        "именуемое в дальнейшем «Заказчик», и Общество с ограниченной ответственностью "
        "«Альфа» (ООО «Альфа»), именуемое в дальнейшем «Подрядчик»",
        CLEAN_PRICE,
    ),
    "check-noamount.pdf": (
        "2.1. Цена Договора составляет 1 000 000 (один миллион) рублей 00 копеек без учёта НДС.",
    ),
}


@pytest.fixture(scope="module")
def checks(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("checks")
    return {path.name: path for path in make_check_contracts(folder)}


def _text(path: Path) -> str:
    document = pdfium.PdfDocument(str(path))
    try:
        pages = [str(document[i].get_textpage().get_text_range()) for i in range(len(document))]
    finally:
        document.close()
    return " ".join(" ".join(pages).split())


def test_returns_nine_files_in_order(tmp_path: Path) -> None:
    paths = make_check_contracts(tmp_path)
    assert [path.name for path in paths] == list(FILES)
    for path in paths:
        assert path.is_file()


@pytest.mark.parametrize("name", FILES)
def test_key_lines_are_in_text(checks: dict[str, Path], name: str) -> None:
    text = _text(checks[name])
    for line in KEY_LINES[name]:
        assert " ".join(line.split()) in text, (name, line)


def test_noamount_has_no_amount_with_vat(checks: dict[str, Path]) -> None:
    assert "с учётом НДС" not in _text(checks["check-noamount.pdf"])


def test_exempt_has_no_amount_with_vat(checks: dict[str, Path]) -> None:
    assert "с учётом НДС" not in _text(checks["check-exempt.pdf"])


def test_check_version_is_one() -> None:
    assert CHECK_GENERATOR_VERSION == 1
