"""The structure survey counts layouts of synthetic contracts and prints no text from them."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_structure.py"
spec = importlib.util.spec_from_file_location("survey_structure", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey  # @dataclass looks its module up there
spec.loader.exec_module(survey)

Line = survey.Line
WORD = re.compile(r"[А-Яа-яЁёA-Za-z]{3,}|\d{2,}")


@pytest.mark.parametrize(
    ("text", "kind", "number", "caps"),
    [
        ("5.2. Оплата производится частями", "multi", (5, 2), False),
        ("5.2.1 Аванс", "multi", (5, 2, 1), False),
        ("1. ПРЕДМЕТ ДОГОВОРА", "single", (1,), True),
        ("1. Подрядчик обязуется выполнить работы", "single", (1,), False),
        ("5.2", "bare_number", (5, 2), False),
        ("5.", "bare_number", (5,), False),
        ("01.03.2025 стороны подписали акт", "date", (), False),
        ("10.5 млн рублей", "sum", (), False),
        ("15 % от цены", "sum", (), False),
        ("а) поставка материалов", "letter", (), False),
        ("1) поставка материалов", "paren_num", (), False),
        ("Статья 5. Цена договора", "word_section", (5,), False),
        ("РАЗДЕЛ IV. ОТВЕТСТВЕННОСТЬ", "word_section", (4,), False),
        ("IV. ОТВЕТСТВЕННОСТЬ СТОРОН", "roman", (4,), False),
        ("Приложение № 1", "appendix", (), False),
        ("ПРЕДМЕТ ДОГОВОРА", "caps_heading", (), False),
    ],
)
def test_classifies_line_starts(text: str, kind: str, number: tuple[int, ...], caps: bool) -> None:
    start = survey.classify(text)
    assert start is not None
    assert (start.kind, start.number, start.caps_rest) == (kind, number, caps)


@pytest.mark.parametrize(
    "text", ["", "   ", "согласно п. 5.2 настоящего договора", "Подрядчик обязуется", "г. Москва"]
)
def test_ordinary_text_has_no_start(text: str) -> None:
    assert survey.classify(text) is None


@pytest.mark.parametrize(
    ("text", "value"), [("I", 1), ("IV", 4), ("IX", 9), ("XIV", 14), ("XL", 40), ("IA", 0)]
)
def test_roman_numerals(text: str, value: int) -> None:
    assert survey.roman_to_int(text) == value


@pytest.mark.parametrize(
    ("previous", "current", "kind"),
    [
        (None, (1, 1), "first"),
        ((5, 1), (5, 2), "next"),
        ((5, 3), (6, 1), "new_section"),
        ((5, 2), (5, 2), "repeat"),
        ((5, 1), (5, 3), "gap"),
        ((5, 3), (6, 2), "gap"),
        ((7, 4), (1, 1), "restart"),
        ((7, 4), (3, 2), "backwards"),
        ((2, 1), (9, 9), "jump"),
    ],
)
def test_depth2_steps(
    previous: tuple[int, ...] | None, current: tuple[int, ...], kind: str
) -> None:
    assert survey.step_kind(previous, current) == kind


@pytest.mark.parametrize(
    ("previous", "current", "kind"),
    [(None, 1, "first"), (1, 2, "next"), (2, 2, "repeat"), (2, 4, "gap"), (6, 1, "restart")],
)
def test_level1_steps(previous: int | None, current: int, kind: str) -> None:
    assert survey.level1_step(previous, current) == kind


def contract() -> list[Line]:
    """A fictional contract: «N. ЗАГОЛОВОК» with «N.M», a table, a numbered requisites
    section and an appendix that restarts the numbering. Lines hold marker words that the
    report must never show."""
    rows = [
        (1, "ДОГОВОР ПОДРЯДА Зюзякин", False),
        (1, "г. Квазиград, ООО «Зюзякин» именуемое Заказчиком", False),
        (1, "1. ПРЕДМЕТ ДОГОВОРА", False),
        (1, "1.1. Подрядчик Зюзякин выполняет работы", False),
        (1, "1.2. Работы выполняются по адресу Квазиград", False),
        (1, "а) разметка участка Зюзякин", False),
        (1, "1.3. Срок 30 дней Зюзякин", False),
        (1, "1 Земляные работы Зюзякин", True),
        (2, "2. ЦЕНА ДОГОВОРА", False),
        (2, "2.1. Цена Зюзякин составляет", False),
        (2, "2.1.1 Аванс Зюзякин", False),
        (2, "01.03.2025 Зюзякин вносит аванс", False),
        (2, "2.2. Оплата Зюзякин", False),
        (2, "2.2. Оплата повторно Зюзякин", False),
        (2, "2.4. Штраф Зюзякин", False),
        (2, "3. АДРЕСА И РЕКВИЗИТЫ СТОРОН", False),
        (2, "ИНН 7712345678 Зюзякин", False),
        (3, "Приложение № 1", False),
        (3, "1.1. Перечень работ Зюзякин", False),
    ]
    lines = []
    seen: dict[int, int] = {}
    for page, text, table in rows:
        index = seen.get(page, 0)
        seen[page] = index + 1
        lines.append(Line(page, index, text, table))
    return lines


def test_surveys_one_contract() -> None:
    flags = {2: ["ocr_text", "recognized"], 3: ["scan_unread"]}
    s = survey.survey_document("D-0007", contract(), flags, pages=3)

    assert s.style == "«N. ЗАГОЛОВОК» и «N.M»"
    assert s.level1_caps == 3 and s.level1_plain == 0
    assert s.steps["next"] == 3 and s.steps["new_section"] == 1
    assert s.steps["gap"] == 1 and s.steps["repeat"] == 1
    assert s.depth[3] == 1
    assert s.starts["date"] == 1 and s.starts["letter"] == 1
    assert s.table_number_lines == 1
    assert s.requisites_lines == 1 and s.requisites_numbered
    assert s.appendix_top == 1 and s.appendix_other == 0
    assert s.restart_after_appendix
    assert s.appendix_before_requisites is False
    assert s.preamble_share is not None and 0 < s.preamble_share < 0.2
    assert s.tail_share is not None and 0 < s.tail_share < 0.3
    assert s.flagged_pages == {"ocr_text": 1, survey.RECOGNIZED: 1, "unread": 1}


def test_requisites_heading_after_the_last_clause() -> None:
    lines = [
        Line(1, 0, "1.1. Первый пункт"),
        Line(1, 1, "1.2. Второй пункт"),
        Line(1, 2, "1.3. Третий пункт"),
        Line(1, 3, "1.4. Четвёртый пункт"),
        Line(1, 4, "РЕКВИЗИТЫ И ПОДПИСИ СТОРОН"),
        Line(1, 5, "Заказчик"),
    ]
    s = survey.survey_document("D-0001", lines, {}, pages=1)
    assert s.style == "только «N.M»"
    assert s.requisites_after_last and not s.requisites_numbered
    assert s.lines_last_to_tail == 1
    assert s.preamble_share == 0
    assert len(s.clause_lengths) == 4


def test_no_numbering() -> None:
    lines = [Line(1, 0, "Стороны договорились о следующем"), Line(1, 1, "Работы выполняются")]
    s = survey.survey_document("D-0002", lines, {}, pages=1)
    assert s.style == "нумерация не найдена"
    assert s.preamble_share is None and s.tail_share is None


def test_report_shows_no_text_from_the_documents() -> None:
    docs = [
        survey.survey_document("D-0007", contract(), {2: ["recognized"]}, pages=3),
        survey.survey_document("D-0008", contract()[:9], {}, pages=1),
    ]
    report = "\n".join(survey.summary_lines(docs))
    assert "Документов: 2; страниц: 4" in report
    assert "D-0007" in report

    # A word of the input may appear in the report only if the script itself prints it
    # as part of a label («ДОГОВОРА» in «ПРЕДМЕТ ДОГОВОРА»-like examples would not count).
    own_words = set(WORD.findall(SCRIPT.read_text(encoding="utf-8")))
    input_words = {w for line in contract() for w in WORD.findall(line.text)}
    leaked = (input_words & set(WORD.findall(report))) - own_words
    assert not leaked
    for marker in ("Зюзякин", "Квазиград", "7712345678", "2025"):
        assert marker not in report


def test_empty_set() -> None:
    assert survey.summary_lines([])[-1] == "Нет документов, доступных после чтения."
