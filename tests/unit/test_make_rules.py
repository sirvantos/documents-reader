"""Tests of the synthetic rules contracts (feature 009, task T003).

The generator writes only under pytest tmp_path. Each file is checked for its key lines in
the text layer; line breaks made by the generator's wrapping are normalised to spaces.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from tests.synthetic.make_pdfs import RULES_GENERATOR_VERSION, make_rules_contracts

FILES = ("rules-a.pdf", "rules-b.pdf", "rules-c.pdf", "rules-d.pdf")

KEY_LINES: dict[str, tuple[str, ...]] = {
    "rules-a.pdf": (
        "ДОГОВОР ПОДРЯДА № Р-11/2026",
        "Общество с ограниченной ответственностью «Альфа» (ООО «Альфа»), "
        "именуемое в дальнейшем «Заказчик»",
        "Общество с ограниченной ответственностью «Бета» (ООО «Бета»), "
        "именуемое в дальнейшем «Подрядчик»",
        "2. Цена Договора",
        "2.1. Цена Договора составляет 2 400 000 (два миллиона четыреста тысяч) рублей "
        "00 копеек без учёта НДС, НДС 20% — 480 000 рублей 00 копеек, всего с учётом НДС "
        "2 880 000 (два миллиона восемьсот восемьдесят тысяч) рублей 00 копеек.",
        "5. Срок действия Договора",
        "5.1. Договор вступает в силу с даты подписания и действует до «31» декабря "
        "2027 г.",
        "8. Адреса и реквизиты сторон",
    ),
    "rules-b.pdf": (
        "Протокол № 314 от 12 мая 2026 г.",
        "ДОГОВОР № Р-12/2026",
        "действующее на основании доверенности № 77-Д от 03 марта 2026 г.",
        "2.1. Цена Договора составляет 3 600 000 (три миллиона шестьсот тысяч) рублей "
        "00 копеек без учёта НДС, НДС 20% — 720 000 рублей 00 копеек, всего с учётом НДС "
        "4 320 000 (четыре миллиона триста двадцать тысяч) рублей 00 копеек.",
        "7. Ответственность",
        "7.1. За просрочку Подрядчик уплачивает штраф 50 000 рублей 00 копеек.",
        "7.2. Обеспечение исполнения Договора составляет 120 000 рублей 00 копеек.",
        "5.1. Договор вступает в силу с даты подписания и действует до «30» июня 2028 г.",
        "Акт сверки составляется до 15 января 2028 г.",
    ),
    "rules-c.pdf": (
        "ДОГОВОР ПОДРЯДА № Р-13/2026",
        "2.1. Цена Договора составляет 900 000 (девятьсот тысяч) рублей 00 копеек "
        "без учёта НДС, НДС 20% — 180 000 рублей 00 копеек, всего с учётом НДС "
        "1 080 000 (один миллион восемьдесят тысяч) рублей 00 копеек.",
        "2.2. Стоимость первого этапа составляет 300 000 рублей 00 копеек без учёта НДС.",
        "5.1. Договор вступает в силу с даты подписания и действует до «31» декабря "
        "2027 г.",
    ),
    "rules-d.pdf": (
        "ДОГОВОР ПОДРЯДА № Р-14/2026",
        "2.1. Цена Договора составляет 1 200 000 рублей 00 копеек, включая НДС.",
        "5. Приёмка работ",
        "8. Адреса и реквизиты сторон",
    ),
}


@pytest.fixture(scope="module")
def rules(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("rules")
    paths = make_rules_contracts(folder)
    return {path.name: path for path in paths}


def _text(path: Path) -> str:
    document = pdfium.PdfDocument(str(path))
    try:
        pages = [
            str(document[i].get_textpage().get_text_range())
            for i in range(len(document))
        ]
    finally:
        document.close()
    return " ".join(" ".join(pages).split())


def test_returns_four_files_in_order(tmp_path: Path) -> None:
    paths = make_rules_contracts(tmp_path)
    assert [path.name for path in paths] == list(FILES)
    for path in paths:
        assert path.is_file()


@pytest.mark.parametrize("name", FILES)
def test_key_lines_are_in_text(rules: dict[str, Path], name: str) -> None:
    text = _text(rules[name])
    for line in KEY_LINES[name]:
        assert " ".join(line.split()) in text, (name, line)


def test_rules_d_has_no_term_and_no_vat_free_amount(rules: dict[str, Path]) -> None:
    text = _text(rules["rules-d.pdf"])
    assert "действует до" not in text
    assert "без учёта НДС" not in text


def test_rules_version_is_one() -> None:
    assert RULES_GENERATOR_VERSION == 1
