"""The field survey counts synthetic contracts and prints no text from them (feature 05)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_fields.py"
spec = importlib.util.spec_from_file_location("survey_fields", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey  # @dataclass looks its module up there
spec.loader.exec_module(survey)

Record = survey.Record

PREAMBLE = (
    "Договор № 17/ЭН-2026\n"
    "г. Энск\n"
    "Открытое акционерное общество «Альфа» (ОАО «Альфа»), именуемое в дальнейшем "
    "«Заказчик», и общество с ограниченной ответственностью «Бета» (ООО «Бета»), "
    "именуемое в дальнейшем «Подрядчик», заключили настоящий Договор:\n"
)
SECTIONS = [
    ("1. Предмет договора\n", "1. Предмет договора"),
    ("1.1. Подрядчик выполняет работы.\n", None),
    ("2. Цена Договора\n", "2. Цена Договора"),
    ("2.1. Цена составляет 1 234 567,89 (один миллион …) рублей без учета НДС, "
     "с учетом НДС 1 481 481,47 рублей.\n", None),
    ("3. Срок действия Договора\n", "3. Срок действия Договора"),
    ("3.1. Договор вступает в силу с даты подписания и действует по 25 марта 2027 г.\n", None),
    ("4. Ответственность\n", "4. Ответственность"),
    ("4.1. Неустойка — 10 000 рублей.\n", None),
]
TAIL = (
    "5. Адреса и реквизиты сторон\nИНН 0000000000\n"
    "Приложение № 1\nСмета работ на 1 000 рублей\n"
)


def build() -> tuple[str, list]:
    parts = [PREAMBLE]
    records = [Record("preamble", 0, len(PREAMBLE))]
    pos = len(PREAMBLE)
    for text, heading in SECTIONS:
        kind = "section" if heading else "clause"
        title = heading.split(". ", 1)[1] if heading else None
        records.append(Record(kind, pos, pos + len(text), title))
        parts.append(text)
        pos += len(text)
    records.append(Record("tail", pos, pos + len(TAIL)))
    parts.append(TAIL)
    return "".join(parts), records


def test_survey_document_counts_the_synthetic_contract() -> None:
    text, records = build()
    d = survey.survey_document("D-0001", text, records)
    assert d.total == len(text)
    assert d.preamble == len(PREAMBLE)
    assert d.requisites == len("5. Адреса и реквизиты сторон\nИНН 0000000000\n")
    assert d.appendices == len("Приложение № 1\nСмета работ на 1 000 рублей\n")
    assert d.roles == {"Заказчик", "Подрядчик"}
    assert d.short_names == 2
    assert d.number == "заполнен"
    assert d.price_sections == 1
    assert (d.without_vat, d.with_vat) == (1, 1)
    assert d.price_sums == 2  # the sums of the price section only
    assert d.main_sums == 3  # plus the penalty
    assert d.term == {"дата словом"}


def test_number_form() -> None:
    assert survey.number_form("ДОГОВОР № 634/ОКЭ-ЦДИ/24/6/1\nг. Энск") == "заполнен"
    assert survey.number_form("Договор подряда № ____________\nг. Энск") == "пустой"
    assert survey.number_form("Договор подряда №\nг. Энск") == "пустой"
    assert survey.number_form("Соглашение сторон\nг. Энск") == "нет"


def test_term_forms() -> None:
    assert survey.term_forms("Договор действует до 31.12.2026.") == {"дата цифрами"}
    assert survey.term_forms(
        "Договор действует до полного исполнения Сторонами обязательств."
    ) == {"до исполнения обязательств"}
    # a sentence about something else than the contract does not count
    assert survey.term_forms("Гарантия действует по 25 марта 2027 г.") == set()


def test_part_sizes_without_a_tail() -> None:
    text = "Преамбула\n1. Раздел\n"
    records = [Record("preamble", 0, 10), Record("section", 10, len(text), "Раздел")]
    assert survey.part_sizes(text, records) == (10, len(text) - 10, 0, 0)


def test_size_buckets_and_value_counts() -> None:
    assert survey.size_buckets([5_000, 30_000, 45_000, 450_000]) == (
        "0–20 тыс.: 1, 20–50 тыс.: 2, ≥ 400 тыс.: 1"
    )
    assert survey.value_counts([0, 2, 2, 5], 3) == "0: 1, 2: 2, 3 и больше: 1"


def test_summary_prints_no_text_or_numbers_of_the_documents() -> None:
    text, records = build()
    docs = [survey.survey_document("D-0001", text, records)]
    summary = "\n".join(survey.summary_lines(docs))
    # words of the document that the summary does not have in its own labels
    own = set(re.findall(r"[А-Яа-яЁё]{4,}", "\n".join(survey.summary_lines([]))))
    words = set(re.findall(r"[А-Яа-яЁё]{4,}", text)) - own
    assert sorted(w for w in words if re.search(rf"\b{w}\b", summary)) == []
    for secret in ("17/ЭН-2026", "1 234 567", "Альфа", "Бета", "0000000000", "2027"):
        assert secret not in summary
