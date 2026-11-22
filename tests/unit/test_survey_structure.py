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
        (2, "Приложение № 2 к договору Зюзякин", False),
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


def test_main_text_ends_at_the_numbered_requisites_heading() -> None:
    b = survey.find_boundary(contract())
    # 2 — «1. ПРЕДМЕТ ДОГОВОРА»; 16 — «3. АДРЕСА И РЕКВИЗИТЫ СТОРОН»; 18 — appendix at a page top
    assert (b.first, b.end, b.how, b.appendix_after) == (2, 16, "requisites_numbered", 18)
    # «Приложение № 2 к договору» inside the clause text is not at a page top
    assert b.appendix_before == 0


def test_surveys_the_main_text_only() -> None:
    flags = {2: ["ocr_text", "recognized"], 3: ["scan_unread"]}
    s = survey.survey_document("D-0007", contract(), flags, pages=3)

    assert s.style == "«N. Заголовок» и «N.M»"
    assert s.how == "requisites_numbered" and s.requisites_section_lines == 2
    assert (s.level1_heading, s.level1_sentence, s.level1_short, s.level1_caps) == (2, 0, 2, 2)
    assert s.steps == {"first": 1, "next": 3, "new_section": 1, "repeat": 1, "gap": 1}
    assert s.level1_steps == {"first": 1, "next": 1}
    assert s.depth == {2: 7, 3: 1}
    assert s.starts["date"] == 1 and s.starts["letter"] == 1 and s.starts["appendix"] == 1
    assert s.table_lines == 1 and s.table_number_lines == 1
    assert len(s.clause_lengths) == 7
    # the appendix page 3 is outside the main text
    assert s.main_pages == 2
    assert s.main_flagged_pages == {"ocr_text": 1, survey.RECOGNIZED: 1}
    assert 0 < s.preamble_share < 0.2 and s.main_share > 0.5
    assert s.requisites_share > 0 and s.appendix_share > 0
    total = s.preamble_share + s.main_share + s.requisites_share + s.appendix_share
    assert total == pytest.approx(1.0)


def test_requisites_heading_in_capitals_without_a_number() -> None:
    lines = [
        Line(1, 0, "1.1. Первый пункт"),
        Line(1, 1, "1.2. Стороны сообщают об изменении реквизитов"),
        Line(1, 2, "1.3. Третий пункт"),
        Line(1, 3, "1.4. Четвёртый пункт"),
        Line(1, 4, "РЕКВИЗИТЫ И ПОДПИСИ СТОРОН"),
        Line(1, 5, "Заказчик"),
    ]
    s = survey.survey_document("D-0001", lines, {}, pages=1)
    assert s.how == "requisites_caps" and s.requisites_section_lines == 2
    assert s.style == "только «N.M»"
    assert s.preamble_share == 0 and s.appendix_share == 0
    assert len(s.clause_lengths) == 4


def test_appendix_at_a_page_top_ends_the_main_text_without_requisites() -> None:
    lines = [
        Line(1, 0, "1.1. Первый пункт"),
        Line(1, 1, "1.2. Второй пункт"),
        Line(1, 2, "1.3. Третий пункт"),
        Line(1, 3, "1.4. Четвёртый пункт"),
        Line(2, 0, "Приложение № 1"),
        Line(2, 1, "1.1. Перечень работ"),
    ]
    s = survey.survey_document("D-0003", lines, {}, pages=2)
    assert s.how == "appendix"
    assert s.appendix_share > 0 and s.requisites_section_lines is None
    assert "restart" not in s.steps


def test_flat_numbering_of_sentences() -> None:
    lines = [
        Line(1, 0, "1. Подрядчик обязуется выполнить работы в срок"),
        Line(1, 1, "2. Заказчик обязуется принять результат работ"),
        Line(1, 2, "3. Оплата производится после подписания акта"),
    ]
    s = survey.survey_document("D-0004", lines, {}, pages=1)
    assert s.style == "сквозная «N.» без «N.M»"
    assert (s.level1_heading, s.level1_sentence) == (0, 3)


@pytest.mark.parametrize(
    ("text", "kind"), [("5,2 Оплата частями", "comma"), ("5.2Оплата частями", "glued")]
)
def test_counts_numbers_damaged_by_recognition(text: str, kind: str) -> None:
    lines = [Line(1, 0, "1.1. Первый пункт"), Line(1, 1, text)]
    s = survey.survey_document("D-0005", lines, {}, pages=1)
    assert s.damaged_numbers == {kind: 1}


def test_no_numbering() -> None:
    lines = [Line(1, 0, "Стороны договорились о следующем"), Line(1, 1, "Работы выполняются")]
    s = survey.survey_document("D-0002", lines, {}, pages=1)
    assert s.style == "нумерация не найдена"
    assert s.how == "none" and s.preamble_share == 1.0 and s.main_share == 0


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
