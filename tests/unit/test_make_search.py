"""Tests of the synthetic search contracts (feature 007, task T001).

The generator writes only under pytest tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
import pytest

from tests.synthetic.make_pdfs import make_search_contracts

PAYMENT_CLAUSE = "2.2. Срок оплаты товара составляет 30 дней с даты поставки."

EXPECTED_LINES: dict[str, tuple[str, ...]] = {
    "search-a.pdf": (
        "ДОГОВОР ПОСТАВКИ № ДП-17/2026",
        "1. Предмет договора",
        "1.1. Поставщик передаёт товар по договору № ДП-17/2026.",
        "2. Цена и порядок расчётов",
        "2.1. Цена договора составляет 500 000 рублей.",
        PAYMENT_CLAUSE,
        "3. Ответственность",
        "3.1. За просрочку поставки Поставщик уплачивает неустойку 0,1% за каждый день.",
        "4. Гарантия",
        "4.1. Гарантийный срок составляет 12 месяцев.",
        "5. Адреса и реквизиты сторон",
        "Заказчик: ООО «Альфа», ИНН 0000000000",
        "Подрядчик: ООО «Бета», ИНН 0000000001",
    ),
    "search-b.pdf": (
        "ДОГОВОР ПОСТАВКИ",
        "1. Предмет договора",
        "1.1. Поставщик поставляет оборудование.",
        "2. Цена и порядок расчётов",
        PAYMENT_CLAUSE,
        "2.3. Покупатель перечисляет денежные средства на счёт Поставщика.",
        "3. Порядок приёмки",
        "3.1. Приёмка проводится на складе Покупателя.",
        "5. Адреса и реквизиты сторон",
        "Заказчик: ООО «Альфа», ИНН 0000000000",
        "Подрядчик: ООО «Бета», ИНН 0000000001",
    ),
    "search-c.pdf": (
        "ДОГОВОР ПОСТАВКИ",
        "1. Предмет договора",
        "1.1. Поставщик поставляет запасные части.",
        "2. Цена и порядок расчётов",
        PAYMENT_CLAUSE,
        "3. Форс-мажор",
        "3.1. Стороны освобождаются от ответственности при обстоятельствах "
        "непреодолимой силы.",
        "5. Адреса и реквизиты сторон",
        "Заказчик: ООО «Альфа», ИНН 0000000000",
        "Подрядчик: ООО «Бета», ИНН 0000000001",
    ),
}

PREAMBLE = (
    "Общество с ограниченной ответственностью «Альфа» (ООО «Альфа»), "
    "именуемое в дальнейшем Заказчик, и ООО «Бета», именуемое в дальнейшем Подрядчик, "
    "заключили настоящий договор:"
)


def _text(path: Path) -> str:
    document = pdfium.PdfDocument(str(path))
    try:
        return " ".join(
            " ".join(str(document[i].get_textpage().get_text_range()).split())
            for i in range(len(document))
        )
    finally:
        document.close()


@pytest.fixture(scope="module")
def contracts(tmp_path_factory: pytest.TempPathFactory) -> list[Path]:
    return make_search_contracts(tmp_path_factory.mktemp("search"))


def test_returns_three_files_in_order(contracts: list[Path]) -> None:
    assert [p.name for p in contracts] == ["search-a.pdf", "search-b.pdf", "search-c.pdf"]
    assert all(p.is_file() for p in contracts)


def test_each_file_holds_its_lines(contracts: list[Path]) -> None:
    for path in contracts:
        text = _text(path)
        assert PREAMBLE in text, path.name
        for line in EXPECTED_LINES[path.name]:
            assert " ".join(line.split()) in text, (path.name, line)


def test_payment_clause_identical_in_all_three(contracts: list[Path]) -> None:
    for path in contracts:
        assert PAYMENT_CLAUSE in _text(path), path.name


def test_writes_only_under_given_folder(tmp_path: Path) -> None:
    make_search_contracts(tmp_path / "out")
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == [
        "search-a.pdf",
        "search-b.pdf",
        "search-c.pdf",
    ]
