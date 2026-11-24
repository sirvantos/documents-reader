"""The passage survey counts synthetic parse records and prints no text (feature 07)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_passages.py"
spec = importlib.util.spec_from_file_location("survey_passages", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey  # @dataclass looks its module up there
spec.loader.exec_module(survey)

Record = survey.Record

MARKER = "Зеленоглазовск"  # a word of the synthetic text that must never be printed
LONG = "Подрядчик выполняет работы в городе " + MARKER + ". " + "Слово " * 400

# (text, kind, depth, section_number, section_title)
PARTS = [
    ("Договор подряда\nООО «Альфа» и ООО «Бета» заключили договор:\n",
     "preamble", 0, None, None),
    ("1. Предмет договора\n", "section", 1, 1, "Предмет договора"),
    ("1.1. Подрядчик выполняет работы.\n", "clause", 2, 1, "Предмет договора"),
    ("1.1.1. " + LONG + "\n", "clause", 3, 1, "Предмет договора"),
    ("2. Цена\nЦена указана в смете.\n", "section", 1, 2, "Цена"),
    ("2.1. Не применяется.\n", "clause", 2, 2, "Цена"),
    ("7.3. Пункт без раздела.\n", "clause", 2, None, None),
    ("5. Адреса и реквизиты сторон\nИНН 0000000000\n"
     "Приложение № 1\nСмета на 1 000 рублей\nПриложение № 2\nГрафик работ\n",
     "tail", 0, None, None),
]


def build() -> tuple[str, list]:
    text, records, pos = "", [], 0
    for part, kind, depth, number, title in PARTS:
        records.append(Record(kind, depth, pos, pos + len(part), number, title))
        text += part
        pos += len(part)
    return text, records


def test_heading_only_section_has_no_passage() -> None:
    assert survey.own_body("1. Предмет договора\n", "section") == ""
    assert survey.own_body("2. Цена\nЦена указана в смете.\n", "section") == (
        "Цена указана в смете."
    )
    assert survey.own_body("2.1. Не применяется.\n", "clause") == "2.1. Не применяется."


def test_survey_document_counts_passages_by_kind() -> None:
    text, records = build()
    d = survey.survey_document("D-0001", text, records)
    assert d.records == 8
    assert d.heading_only_sections == 1
    assert d.sections_with_body == 1
    kinds = sorted(p.kind for p in d.passages)
    assert kinds == ["clause", "clause", "clause", "preamble", "section", "subclause", "tail"]
    assert d.no_section == 1
    # under 30 characters: the body of section 2, «2.1. Не применяется.», «7.3. …»
    assert d.short == 3


def test_passage_lengths_are_own_text_lengths() -> None:
    text, records = build()
    d = survey.survey_document("D-0001", text, records)
    sub = next(p for p in d.passages if p.kind == "subclause")
    assert sub.chars == len(PARTS[3][0].strip())
    assert sub.label_chars > len("D-0001")


def test_tail_is_split_into_requisites_and_appendices() -> None:
    text, records = build()
    d = survey.survey_document("D-0001", text, records)
    assert d.tail_requisites == len("5. Адреса и реквизиты сторон\nИНН 0000000000\n")
    assert d.tail_appendices == len(PARTS[7][0]) - d.tail_requisites
    assert d.appendix_lines == 2
    assert d.total == len(text)


def test_no_tail() -> None:
    text, records = build()
    d = survey.survey_document("D-0001", text[: records[-1].start], records[:-1])
    assert (d.tail_requisites, d.tail_appendices, d.appendix_lines) == (0, 0, 0)


def test_token_estimate_is_conservative() -> None:
    assert survey.tokens_estimate(0) == 0
    assert survey.tokens_estimate(300) == 100
    assert survey.tokens_estimate(301) == 101


def test_over_limits_counts_passages_and_text_share() -> None:
    text, records = build()
    d = survey.survey_document("D-0001", text, records)
    lines = survey.summary_lines([d])
    joined = "\n".join(lines)
    assert "512" in joined and "8192" in joined
    # the long subclause with its label is over 512 estimated tokens, nothing over 8192
    over = survey.over_limit([d], 512)
    assert over[0] == 1
    assert survey.over_limit([d], 8192)[0] == 0


def test_summary_prints_no_text() -> None:
    text, records = build()
    d = survey.survey_document("D-0001", text, records)
    joined = "\n".join(survey.summary_lines([d]))
    for word in (MARKER, "Подрядчик", "Альфа", "смете", "Предмет", "Не применяется", "0000000000"):
        assert word not in joined, word
    assert "D-0001" in joined  # ids may be printed


def test_summary_on_no_documents() -> None:
    assert survey.summary_lines([])[0] == "Документов: 0"
