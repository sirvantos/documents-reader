"""The pure structure rule (feature 04; tasks T006, T011; research R-2…R-5, R-7).

Lines are built the way parsing.py builds them from `document_text` and `text_span`:
each line is a span, lines are joined with "\\n", a glued span is not a line start.
Numbering starts at 1 and the requisites heading takes the next section number, so a
test sees only the findings it is about.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from docreader.config import StructureSettings
from docreader.structure import Line, ParseResult, candidate, parse_lines


@dataclass(frozen=True)
class L:
    """A line of a test document: page, text, table mark, glued to the previous line."""

    page: int
    text: str
    table: bool = False
    glued: bool = False


def build(*rows: L | tuple[int, str]) -> tuple[list[Line], str]:
    lines: list[Line] = []
    parts: list[str] = []
    position = 0
    for row in rows:
        r = row if isinstance(row, L) else L(*row)
        if parts and not r.glued:
            parts.append("\n")
            position += 1
        lines.append(Line(position, position + len(r.text), r.page, r.text, r.table, not r.glued))
        parts.append(r.text)
        position += len(r.text)
    return lines, "".join(parts)


@dataclass(frozen=True)
class Parsed:
    result: ParseResult
    text: str

    def keys(self) -> list[str]:
        return [r.key for r in self.result.records]

    def record(self, key: str):
        (found,) = [r for r in self.result.records if r.key == key]
        return found

    def own(self, key: str) -> str:
        r = self.record(key)
        return self.text[r.start : r.end]

    def kinds(self) -> list[str]:
        return [f.kind for f in self.result.findings]

    @property
    def reason(self) -> str | None:
        return self.result.reason


def parse(*rows: L | tuple[int, str], unread: tuple[int, ...] = (), **settings) -> Parsed:
    lines, text = build(*rows)
    result = parse_lines(lines, len(text), StructureSettings(**settings), unread)
    # Records are contiguous, ordered and cover [0, len(text)) (FR-006, SC-003).
    position = 0
    for i, rec in enumerate(result.records):
        assert rec.ordinal == i
        assert rec.start == position, rec.key
        assert rec.end > rec.start
        position = rec.end
    assert position == len(text)
    return Parsed(result, text)


def req(number: int, page: int = 9) -> tuple[int, str]:
    """The requisites heading as section `number`: starts the tail."""
    return (page, f"{number}. Адреса и реквизиты сторон")


# --- candidates (R-2) -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "number", "printed", "rest"),
    [
        ("5. Цена договора", (5,), "5.", "Цена договора"),
        ("5.", (5,), "5.", ""),
        ("5.2 Оплата", (5, 2), "5.2", "Оплата"),
        ("5.2. Оплата", (5, 2), "5.2.", "Оплата"),
        ("5.2.1.1. Подготовка", (5, 2, 1, 1), "5.2.1.1.", "Подготовка"),
        ("5.2Оплата производится", (5, 2), "5.2", "Оплата производится"),
        ("5.Реквизиты", (5,), "5.", "Реквизиты"),
        ("6.2", (6, 2), "6.2", ""),
        ("2.1.10. Часть 10.", (2, 1, 10), "2.1.10.", "Часть 10."),
        ("12.3 Работы", (12, 3), "12.3", "Работы"),
    ],
)
def test_candidate(text: str, number: tuple[int, ...], printed: str, rest: str) -> None:
    found = candidate(text)
    assert found is not None
    assert (found.number, found.printed, found.rest) == (number, printed, rest)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "5 Цена",  # one number without a dot
        "5) поставка",
        "а) разметку участка;",
        "1) завоз материалов.",
        "01.03.2025 Заказчик вносит аванс.",  # leading zero
        "5.03 Работы",
        "0.5 Работы",
        "5.3 млн рублей",
        "5.3 руб. в месяц",
        "5.3 % годовых",
        "5.3%",
        "2.5 тонны",
        "1234.5 Работы",  # four digits
        "5.2, как указано",
        "согласно п. 5.2 настоящего договора",
        "Работы выполняются",
    ],
)
def test_not_a_candidate(text: str) -> None:
    assert candidate(text) is None


# --- continuation (R-3) and records (R-5) ------------------------------------------------


def test_four_levels_with_parents_and_titles() -> None:
    p = parse(
        (1, "1. Цена договора"),
        (1, "1.1. Цена составляет"),
        (1, "1.1.1. Первая часть"),
        (1, "1.1.1.1. Аванс"),
        (1, "1.1.2. Вторая часть"),
        (1, "1.2. Оплата"),
        req(2),
    )
    assert p.keys() == ["1", "1.1", "1.1.1", "1.1.1.1", "1.1.2", "1.2", "реквизиты"]
    assert {r.key: r.parent_key for r in p.result.records} == {
        "1": None, "1.1": "1", "1.1.1": "1.1", "1.1.1.1": "1.1.1", "1.1.2": "1.1",
        "1.2": "1", "реквизиты": None,
    }
    section = p.record("1")
    assert (section.kind, section.depth, section.number, section.number_printed) == (
        "section", 1, (1,), "1.",
    )
    assert (section.title, section.section_number, section.section_title) == (
        "Цена договора", 1, "Цена договора",
    )
    sub = p.record("1.1.1.1")
    assert (sub.kind, sub.depth, sub.number_printed, sub.title) == ("clause", 4, "1.1.1.1.", None)
    assert (sub.section_number, sub.section_title) == (1, "Цена договора")
    assert p.result.findings == ()
    assert p.reason is None


def test_key_comes_from_the_number_not_the_printed_form() -> None:
    p = parse((1, "1. Предмет"), (1, "1.1 Работы"), (1, "1.2. Срок"), req(2))
    assert [(r.key, r.number_printed) for r in p.result.records[:3]] == [
        ("1", "1."), ("1.1", "1.1"), ("1.2", "1.2."),
    ]


def test_own_text_runs_to_the_next_record_of_any_level() -> None:
    p = parse(
        (1, "1. Предмет"),
        (1, "1.1. Работы"),
        (1, "продолжение пункта."),
        (1, "1.1.1. Подпункт"),
        (1, "1.2. Срок"),
        req(2),
    )
    assert p.own("1") == "1. Предмет\n"
    assert p.own("1.1") == "1.1. Работы\nпродолжение пункта.\n"
    assert p.own("1.1.1") == "1.1.1. Подпункт\n"
    assert p.own("1.2") == "1.2. Срок\n"


def test_section_without_subclauses() -> None:
    p = parse(
        (1, "1. Форс-мажор"),
        (1, "Стороны освобождаются от ответственности."),
        (1, "2. Сроки"),
        (1, "2.1. Начало работ"),
        req(3),
    )
    assert p.keys() == ["1", "2", "2.1", "реквизиты"]
    assert p.own("1") == "1. Форс-мажор\nСтороны освобождаются от ответственности.\n"
    assert p.result.findings == ()


def test_missing_section_heading() -> None:
    p = parse(
        (1, "1. Ответственность"),
        (1, "1.1. Неустойка"),
        (1, "2.1. Пункт раздела без заголовка"),
        (1, "2.2. Ещё пункт"),
        (1, "3. Цена"),
        req(4),
    )
    assert p.keys() == ["1", "1.1", "2.1", "2.2", "3", "реквизиты"]
    first = p.record("2.1")
    assert (first.parent_key, first.section_number, first.section_title) == (None, None, None)
    assert p.record("2.2").parent_key is None
    # FR-007 (з): the lost heading is not silent (clarify 2026-11-22, U1)
    assert p.reason == "нет заголовка раздела 2 (стр. 1)"


def test_missing_headings_of_several_sections_are_joined() -> None:
    p = parse(
        (1, "1.1. Пункт"), (2, "2.1. Пункт"), (3, "3. Цена"), (3, "3.1. Оплата"), req(4),
    )
    assert p.reason == "нет заголовка раздела 1 (стр. 1), нет заголовка раздела 2 (стр. 2)"


def test_descent_with_a_missing_middle_level() -> None:
    p = parse((1, "1. Цена"), (1, "1.1.1. Подпункт без пункта 1.1"), req(2))
    assert p.keys() == ["1", "1.1.1", "реквизиты"]
    assert p.record("1.1.1").parent_key == "1"
    assert p.result.findings == ()


@pytest.mark.parametrize(
    ("rows", "new_key", "expected"),
    [
        (
            [(4, "1. Приёмка"), (4, "1.1. Акт"), (4, "1.3. Споры"), req(2)],
            "1.3",
            "пропуск: после 1.1 идёт 1.3 (стр. 4)",
        ),
        (
            [(2, "1. Ответственность"), (2, "1.1. Закон"), (3, "3. Сроки"), req(4)],
            "3",
            "пропуск: после 1.1 идёт 3 (стр. 3)",
        ),
        (
            [(1, "2. Цена"), (1, "2.1. Части"), req(3)],
            "2",
            "пропуск: в начале идёт 2 (стр. 1)",
        ),
        (
            [(1, "1. Цена"), (1, "1.2. Оплата"), req(2)],
            "1.2",
            "пропуск: после 1 идёт 1.2 (стр. 1)",
        ),
    ],
)
def test_gap_is_accepted_with_a_finding(rows, new_key: str, expected: str) -> None:
    p = parse(*rows)
    assert new_key in p.keys()
    assert p.reason == expected


def test_gaps_of_one_kind_are_joined() -> None:
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Работы"), (1, "1.3. Срок"),
        (2, "2. Цена"), (2, "2.2. Оплата"),
        req(3),
    )
    assert p.reason == "пропуск: после 1.1 идёт 1.3 (стр. 1), после 2 идёт 2.2 (стр. 2)"


def test_step_larger_than_max_gap_is_a_number_out_of_order() -> None:
    p = parse(
        (4, "1. Приёмка"), (4, "1.1. Акт"), (4, "1.9. Споры"), (4, "1.2. Срок"),
        req(2),
        max_gap=5,
    )
    assert p.keys() == ["1", "1.1", "1.2", "реквизиты"]
    assert p.reason == "номер вне порядка: 1.9 после 1.1 (стр. 4)"
    assert "1.9. Споры" in p.own("1.1")


def test_max_gap_zero_turns_every_gap_into_a_number_out_of_order() -> None:
    p = parse((1, "1. Приёмка"), (1, "1.1. Акт"), (1, "1.3. Споры"), req(2), max_gap=0)
    assert "1.3" not in p.keys()
    assert p.kinds() == ["out_of_order"]


def test_number_out_of_order_in_another_section() -> None:
    p = parse(
        (1, "1. Приёмка"), (1, "1.1. Акт"), (1, "4.1. Пункт"), (1, "1.2. Срок"),
        req(2),
        max_gap=1,
    )
    assert "4.1" not in p.keys()
    assert p.reason == "номер вне порядка: 4.1 после 1.1 (стр. 1)"


def test_number_backwards_is_rejected_silently() -> None:
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Работы"), (1, "2. Цена"), (1, "2.1. Оплата"),
        (1, "1.5 материалов поставляет Подрядчик."), (1, "2.2. Срок"),
        req(3),
    )
    assert "1.5" not in p.keys()
    assert "1.5 материалов" in p.own("2.1")
    assert p.result.findings == ()


def test_repeat_is_rejected_with_a_finding() -> None:
    p = parse(
        (9, "1. Ответственность сторон"),
        (9, "1.1. Закон"),
        (9, "1. Ответственность сторон"),
        (9, "1.2. Неустойка"),
        req(2, page=10),
    )
    assert p.keys() == ["1", "1.1", "1.2", "реквизиты"]
    assert p.reason == "повтор: 1 (стр. 9)"
    assert p.own("1.1") == "1.1. Закон\n1. Ответственность сторон\n"


def test_repeat_of_the_current_clause_or_its_parent() -> None:
    p = parse(
        (3, "1. Предмет"), (3, "1.1. Работы"), (3, "1.1.1. Подготовка"),
        (3, "1.1 Работы выполняются в срок."),  # the parent of the current 1.1.1
        (3, "1.1.1. Подготовка"),  # the current record itself
        (3, "1.2. Срок"),
        req(2),
    )
    assert p.keys() == ["1", "1.1", "1.1.1", "1.2", "реквизиты"]
    assert p.reason == "повтор: 1.1 (стр. 3), 1.1.1 (стр. 3)"


@pytest.mark.parametrize(
    "reference",
    [
        "1.2 настоящего договора определяет срок.",  # an earlier clause of another section
        "2.1 настоящего договора применяется.",  # an earlier sibling of the current 2.3
        "1. Предмет договора, указанный выше.",  # an earlier section heading
    ],
)
def test_already_accepted_number_outside_the_branch_is_a_reference(reference: str) -> None:
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Работы"), (1, "1.2. Срок"),
        (2, "2. Цена"), (2, "2.1. Части"), (2, "2.2. Аванс"), (2, "2.3. Оплата"),
        (2, reference),
        (2, "2.4. Расчёт"),
        req(3),
    )
    assert p.keys() == ["1", "1.1", "1.2", "2", "2.1", "2.2", "2.3", "2.4", "реквизиты"]
    assert reference in p.own("2.3")
    assert p.result.findings == ()  # FR-005: a reference does not change the state


@pytest.mark.parametrize(
    ("before", "number_line"),
    [
        ("в порядке, указанном пунктом", "1.2 настоящего Договора."),  # own branch
        ("с последствиями, указанными в пунктах 1.1,", "4.2 настоящего Договора."),  # forward
        ("по правилам статьи", "99.1 Кодекса."),  # a law article
        ("согласно п.", "9.1 настоящего Договора."),
        ("в соответствии с ч.", "2.1 настоящего Договора."),
        ("по правилам раздела", "12. настоящего Договора."),
        ("с учётом требований главы", "12 и 13 Кодекса."),
        ("по правилам пунктов 1.1 и", "1.2 настоящего Договора."),  # after a conjunction
        ("указанных в пунктах 1.1,", "2.1 настоящего Договора."),  # would continue numbering
    ],
)
def test_wrapped_reference_after_an_unfinished_line_is_silent(
    before: str, number_line: str
) -> None:
    # A reference that the line break moved to the start of a line (diagnosis 2026-11-22):
    # the previous line ends with a reference word or a comma; FR-005 — no finding.
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Работы"), (1, "1.2. Срок работ"),
        (1, "1.2.1. Работы оплачиваются"), (1, before), (1, number_line),
        (1, "1.2.2. Остаток оплачивается по акту."),
        req(2),
    )
    assert p.keys() == ["1", "1.1", "1.2", "1.2.1", "1.2.2", "реквизиты"]
    assert number_line in p.own("1.2.1")
    assert p.result.findings == ()


@pytest.mark.parametrize("ending", ["Первая часть", "Общие положения раздела 1", "Пункт"])
def test_heading_like_endings_do_not_block_the_next_clause(ending: str) -> None:
    p = parse((1, "1. Предмет"), (1, f"1.1. {ending}"), (1, "1.1.1. Подпункт"), req(2))
    assert p.keys() == ["1", "1.1", "1.1.1", "реквизиты"]


def test_clause_after_a_conjunction_still_starts() -> None:
    # a heading line lost by recognition may leave «… и» right before a real clause
    p = parse((1, "1. Предмет"), (1, "1.1. Работы и"), (1, "1.2. Срок"), req(2))
    assert p.keys() == ["1", "1.1", "1.2", "реквизиты"]


def test_number_after_a_finished_line_is_still_a_finding() -> None:
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Работы"), (1, "Работы выполняются в срок."),
        (1, "14. Ответственность сторон"),  # a lost dot: «1.4.» read as «14.»
        (1, "1.2. Срок"),
        req(2),
    )
    assert p.reason == "номер вне порядка: 14 после 1.1 (стр. 1)"


def test_section_heading_after_its_clause() -> None:
    p = parse(
        (11, "1. Ответственность"), (11, "1.1. Закон"),
        (12, "2.1. Пункт без заголовка"), (12, "2. Цена"), (12, "2.2. Оплата"),
        req(3),
    )
    assert "2" not in p.keys()
    assert p.reason == "заголовок раздела 2 после пункта 2.1 (стр. 12)"
    assert p.own("2.1") == "2.1. Пункт без заголовка\n2. Цена\n"


def test_date_like_subclause_is_accepted_and_a_date_is_not() -> None:
    rows: list[tuple[int, str]] = [(2, "1. Цена"), (2, "1.1. Части:")]
    rows += [(2, f"1.1.{i}. Часть {i}.") for i in range(1, 11)]
    rows += [(2, "01.03.2025 Заказчик вносит аванс."), (2, "1.1.11. Часть 11."), req(2)]
    p = parse(*rows)
    assert "1.1.10" in p.keys() and "1.1.11" in p.keys()
    assert p.own("1.1.10") == "1.1.10. Часть 10.\n01.03.2025 Заказчик вносит аванс.\n"
    assert p.result.findings == ()


def test_number_alone_on_its_line_starts_the_record() -> None:
    p = parse(
        (1, "1. Ответственность"), (1, "1.1. Закон"), (1, "1.2"),
        (1, "Неустойка начисляется за просрочку."),
        req(2),
    )
    assert p.record("1.2").number_printed == "1.2"
    assert p.own("1.2") == "1.2\nНеустойка начисляется за просрочку.\n"


def test_table_lines_and_glued_lines_are_not_candidates() -> None:
    p = parse(
        (2, "1. Цена"),
        (2, "1.1. Части:"),
        L(2, "1.2", table=True),
        L(2, "Разметка участка", table=True),
        (2, "работы раздела"),
        L(2, "1.2. Работы", glued=True),  # a span glued to the previous one
        (2, "1.2Оплата производится по счёту."),
        req(2),
    )
    assert p.keys() == ["1", "1.1", "1.2", "реквизиты"]
    assert p.own("1.2") == "1.2Оплата производится по счёту.\n"
    assert p.result.findings == ()


def test_record_pages_across_a_page_boundary() -> None:
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Работы"), (2, "продолжаются на странице 2"),
        (2, "1.2. Срок"), req(2, page=3),
    )
    assert (p.record("1.1").first_page, p.record("1.1").last_page) == (1, 2)
    assert (p.record("1.2").first_page, p.record("1.2").last_page) == (2, 2)
    assert (p.record("реквизиты").first_page, p.record("реквизиты").last_page) == (3, 3)


def test_unread_pages_before_the_tail_are_findings() -> None:
    p = parse(
        (2, "1. Предмет"), (2, "1.1. Работы"), (4, "1.2. Срок"), req(2, page=6),
        (7, "Приложение № 1"),
        unread=(1, 3, 5, 8),
    )
    # 1 is before the main text, 3 inside it, 5 before the tail page; 8 is in the tail
    assert p.reason == "не прочитана страница: стр. 1, стр. 3, стр. 5"


def test_unread_page_in_the_preamble() -> None:
    p = parse(
        (1, "Договор подряда № 1"), (3, "1. Предмет"), (3, "1.1. Работы"), req(2, page=3),
        unread=(2,),
    )
    assert p.keys()[0] == "преамбула"
    assert p.reason == "не прочитана страница: стр. 2"  # FR-007 (г), clarify 2026-11-22 U3


def test_unread_page_without_a_tail() -> None:
    p = parse((1, "1. Предмет"), (1, "1.1. Работы"), unread=(2,))
    assert p.reason == "раздел реквизитов не найден; не прочитана страница: стр. 2"


def test_clause_across_an_unread_page_stays_one_record() -> None:
    p = parse(
        (2, "1. Предмет"), (2, "1.1. Работы выполняются"), (4, "в два этапа."),
        (4, "1.2. Срок"), req(2, page=5),
        unread=(3,),
    )
    assert p.keys() == ["1", "1.1", "1.2", "реквизиты"]
    assert (p.record("1.1").first_page, p.record("1.1").last_page) == (2, 4)


def test_reason_kinds_in_order() -> None:
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Работы"), (1, "1.3. Срок"), (1, "1.3. Срок"),
        (1, "1.9. Споры"), (3, "2.1. Цена"), (3, "2. Цена"), (4, "2.2. Оплата"),
        (4, "3.1. Пункт без заголовка"),
        (5, "9. Адреса и реквизиты сторон"), (6, "10. Ответственность"),
        unread=(2,),
        max_gap=1,
    )
    assert p.kinds() == [
        "after_tail", "gap", "gap", "repeat", "out_of_order", "heading_after_clause",
        "no_heading", "unread",
    ]
    assert p.reason == (
        "после начала хвоста идёт раздел 10 (стр. 6); "
        "пропуск: после 1.1 идёт 1.3 (стр. 1), после 3.1 идёт 9 (стр. 5); "
        "повтор: 1.3 (стр. 1); "
        "номер вне порядка: 1.9 после 1.3 (стр. 1); "
        "заголовок раздела 2 после пункта 2.1 (стр. 3); "
        "нет заголовка раздела 3 (стр. 4); "
        "не прочитана страница: стр. 2"
    )


def test_same_input_same_result() -> None:
    rows = [(1, "1. Предмет"), (1, "1.1. Работы"), (1, "1.3. Срок"), req(2)]
    assert parse(*rows) == parse(*rows)


# --- preamble and tail (R-4, task T011) ---------------------------------------------------


def test_preamble_before_the_first_record() -> None:
    p = parse(
        (1, "Договор подряда № 7/2026"), (1, "г. Энск"), (1, "1. Предмет"),
        (1, "1.1. Работы"), req(2),
    )
    preamble = p.result.records[0]
    assert (preamble.key, preamble.kind, preamble.depth, preamble.number) == (
        "преамбула", "preamble", 0, None,
    )
    assert (preamble.number_printed, preamble.parent_key, preamble.first_page) == (None, None, 1)
    assert p.own("преамбула") == "Договор подряда № 7/2026\nг. Энск\n"


def test_no_preamble_record_when_the_text_starts_with_a_number() -> None:
    p = parse((1, "1. Предмет"), (1, "1.1. Работы"), req(2))
    assert p.keys()[0] == "1"


@pytest.mark.parametrize(
    "heading",
    [
        "2. Адреса и реквизиты сторон",
        "2. АДРЕСА И РЕКВИЗИТЫ СТОРОН",
        "2. Подписи сторон",
        "2. Юридические адреса сторон",
        "2.Реквизиты",
    ],
)
def test_tail_starts_at_the_requisites_heading(heading: str) -> None:
    p = parse(
        (1, "1. Сроки"), (1, "1.1. Начало"), (2, heading), (2, "Заказчик: ООО «Альфа»"),
        (3, "Приложение № 1"), (3, "1. Перечень работ"), (3, "1.1. Земляные работы."),
    )
    assert p.keys() == ["1", "1.1", "реквизиты"]
    tail = p.record("реквизиты")
    assert (tail.kind, tail.depth, tail.number, tail.first_page, tail.last_page) == (
        "tail", 0, None, 2, 3,
    )
    assert p.own("реквизиты").startswith(heading)
    assert p.result.findings == ()  # the appendix «1.» does not continue the numbering


def test_requisites_inside_a_clause_do_not_start_the_tail() -> None:
    p = parse(
        (1, "1. Предмет"), (1, "1.1. Стороны сообщают об изменении реквизитов"),
        (1, "2. Цена"), req(3),
    )
    assert p.keys() == ["1", "1.1", "2", "реквизиты"]
    assert p.record("реквизиты").first_page == 9


def test_requisites_heading_with_a_skipped_number() -> None:
    p = parse((1, "1. Сроки"), (1, "1.1. Начало"), (2, "4. Реквизиты сторон"))
    assert p.keys()[-1] == "реквизиты"
    assert p.reason == "пропуск: после 1.1 идёт 4 (стр. 2)"


def test_requisites_heading_after_a_gap_larger_than_max_gap() -> None:
    p = parse(
        (1, "1. Сроки"), (1, "1.1. Начало"), (2, "14. Адреса и реквизиты сторон"),
        (2, "Заказчик: ООО «Альфа»"),
        max_gap=5,
    )
    assert p.keys() == ["1", "1.1", "реквизиты"]  # FR-013: no max_gap limit for the tail
    assert p.reason == "пропуск: после 1.1 идёт 14 (стр. 2)"


def test_section_continuing_after_the_tail_start() -> None:
    p = parse(
        (1, "1. Сроки"), (1, "1.1. Начало"), (2, "2. Порядок изменения реквизитов"),
        (2, "2.1. Стороны сообщают"), (20, "3. Ответственность"),
    )
    assert p.keys() == ["1", "1.1", "реквизиты"]  # the tail is left as it is
    assert p.reason == "после начала хвоста идёт раздел 3 (стр. 20)"


def test_no_tail() -> None:
    p = parse((1, "1. Предмет"), (1, "1.1. Работы"), (2, "Заказчик: ООО «Альфа»"))
    assert p.keys() == ["1", "1.1"]
    assert p.reason == "раздел реквизитов не найден"


def test_no_numbering() -> None:
    p = parse((1, "Стороны договорились о следующем"), (1, "Работы выполняются в срок"))
    assert p.keys() == ["преамбула"]
    assert p.reason == "нумерация не найдена"


def test_no_numbering_comes_alone_in_the_reason() -> None:
    p = parse((1, "Стороны договорились"), (3, "о следующем"), unread=(2,))
    assert p.reason == "нумерация не найдена"


def test_unread_page_in_the_tail_gives_no_finding() -> None:
    p = parse((1, "1. Предмет"), (1, "1.1. Работы"), req(2, page=2), (4, "Приложение № 1"),
              unread=(3,))
    assert p.result.findings == ()
