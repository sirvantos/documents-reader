"""Pure helpers of scripts/quickstart_table.py (feature 10, quickstart Б4; task T020).

The measurement asks each question through `table_answer.ask_table` and judges it against
the expected query or outcome and the list (research R-12, contracts/cli.md). The summary
holds numbers, question numbers and ids only — never a question or a value (principle I).
Written by the main session; the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).

Interface:
- `read_questions(path) -> list[Question]`; `Question(number, text, source, expected,
  expected_outcome, documents)`: `number` from 1 in file order; `source` `template` or
  `analyst`; exactly one of `expected` (dict) and `expected_outcome` (`refused`, `clarify`,
  `unsupported`); `documents` a tuple of ids or None; any other form → `QuestionsFileError`
  naming the question number (never its text);
- `judge(question, answer, rows, today) -> str` — `right`, `wrong_outcome`, `wrong_query`
  or `wrong_list`: the outcome first; then the query (action, field, op and the value after
  `table_query.validate` of `expected`: names by `match_names`, amounts as numbers; a
  `party` expectation matches a query whose side was chosen); then the ids of the answer's
  rows against `documents`, or, without them, against `table_query.execute` of the expected
  query over `rows` (side resolved as the program does);
- `Row(number, source, verdict, outcome, retried, seconds)`; `summarize(rows) -> Summary`;
  `render(summary) -> list[str]`.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from docreader import table_query as tq
from docreader.checks import CellState
from docreader.table_answer import TableAnswer, TableOutcome, TableProvenance
from docreader.table_prompt import TableReply

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_table", ROOT / "scripts" / "quickstart_table.py")
assert _spec is not None and _spec.loader is not None
qt = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = qt
_spec.loader.exec_module(qt)

TODAY = date(2026, 11, 28)
EFF = CellState.EFFECTIVE
SECRET = "ВОПРОС-СЕКРЕТ-8812"
PROV = TableProvenance("abc", "fake", "10.1", "0" * 64, "06.1")


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "table-10.toml"
    path.write_text(text, encoding="utf-8")
    return path


QUERY = '{action = "list", field = "amount_with_vat", op = "gt", value = "150000"}'


def entry(text: str = "один", source: str = "template", tail: str = f"expected = {QUERY}") -> str:
    return f'[[question]]\ntext = "{text}"\nsource = "{source}"\n{tail}\n\n'


# --- reading ---------------------------------------------------------------------


def test_reads_questions_in_order(tmp_path: Path) -> None:
    path = write(tmp_path, entry("один") + entry(
        "два", "analyst", 'expected_outcome = "refused"\ndocuments = ["D-0001"]'))
    got = qt.read_questions(path)
    assert [(q.number, q.text, q.source) for q in got] == [(1, "один", "template"),
                                                          (2, "два", "analyst")]
    assert got[0].expected == {"action": "list", "field": "amount_with_vat", "op": "gt",
                               "value": "150000"}
    assert got[0].expected_outcome is None and got[0].documents is None
    assert got[1].expected is None and got[1].expected_outcome == "refused"
    assert got[1].documents == ("D-0001",)


@pytest.mark.parametrize(
    "tail",
    [
        "",
        f'expected = {QUERY}\nexpected_outcome = "refused"',
        'expected_outcome = "answered"',
        'expected = {action = "list"}',
        f'expected = {QUERY}\ndocuments = "D-0001"',
    ],
)
def test_bad_questions_refused_by_number(tmp_path: Path, tail: str) -> None:
    path = write(tmp_path, entry("один") + entry(SECRET, tail=tail))
    with pytest.raises(qt.QuestionsFileError) as info:
        qt.read_questions(path)
    assert "2" in str(info.value) and SECRET not in str(info.value)


def test_bad_source_refused(tmp_path: Path) -> None:
    with pytest.raises(qt.QuestionsFileError):
        qt.read_questions(write(tmp_path, entry(SECRET, source="other")))


# --- judging ---------------------------------------------------------------------


def cell(value: str | None, state: CellState = EFF) -> tq.Cell:
    return tq.Cell(state, value, None, ())


def row(n: int, amount: str, customer: str = 'ООО "Альфа"',
        contractor: str = 'АО "Гамма"') -> tq.DocRow:
    return tq.DocRow(f"D-{n:04d}", {
        "contract_number": cell(f"К-{n}"),
        "customer_name_short": cell(customer),
        "contractor_name_short": cell(contractor),
        "amount_without_vat": cell(amount),
        "amount_with_vat": cell(amount),
        "contract_end_date": cell("2026-12-31"),
    })


ROWS = [row(1, "100000.00"), row(2, "200000.00"), row(3, "300000.00")]


def question(expected: dict | None = None, outcome: str | None = None,
             documents: tuple[str, ...] | None = None) -> object:
    return qt.Question(1, SECRET, "template", expected, outcome, documents)


def answered(reply: dict, rows: list[tq.DocRow] = ROWS) -> TableAnswer:
    q = tq.validate(TableReply.model_validate({"kind": "query", **reply}), TODAY)
    assert isinstance(q, tq.TableQuery)
    q = tq.resolve_party(q, rows, False)
    assert isinstance(q, tq.TableQuery)
    return TableAnswer(SECRET, TableOutcome.ANSWERED, tq.execute(q, rows, False), None, None,
                       False, TODAY, PROV, 1.0)


def other(outcome: TableOutcome) -> TableAnswer:
    return TableAnswer(SECRET, outcome, None, "причина", None, False, TODAY, PROV, 1.0)


AMOUNT = {"action": "list", "field": "amount_with_vat", "op": "gt", "value": "150000"}


def test_right_query_and_list() -> None:
    ans = answered({**AMOUNT, "value": "150 000,00"})
    assert qt.judge(question(AMOUNT), ans, ROWS, TODAY) == "right"


def test_wrong_query() -> None:
    for changed in ({"op": "ge"}, {"value": "150001"}, {"action": "count"},
                    {"field": "amount_without_vat"}):
        ans = answered({**AMOUNT, **changed})
        assert qt.judge(question(AMOUNT), ans, ROWS, TODAY) == "wrong_query", changed


def test_wrong_outcome() -> None:
    assert qt.judge(question(AMOUNT), other(TableOutcome.REFUSED), ROWS, TODAY) == "wrong_outcome"
    assert qt.judge(question(outcome="refused"), answered(AMOUNT), ROWS, TODAY) == "wrong_outcome"
    assert qt.judge(question(outcome="clarify"), other(TableOutcome.CLARIFY), ROWS, TODAY) == (
        "right")
    assert qt.judge(question(outcome="refused"), other(TableOutcome.REJECTED), ROWS, TODAY) == (
        "wrong_outcome")


def test_list_against_documents_when_given() -> None:
    ans = answered(AMOUNT)
    assert qt.judge(question(AMOUNT, documents=("D-0002", "D-0003")), ans, ROWS, TODAY) == "right"
    assert qt.judge(question(AMOUNT, documents=("D-0002",)), ans, ROWS, TODAY) == "wrong_list"


def test_list_against_the_expected_query_over_the_rows() -> None:
    # same query, but the answer was computed over other rows: the list differs
    ans = answered(AMOUNT, rows=[row(1, "100000.00"), row(2, "200000.00")])
    assert qt.judge(question(AMOUNT), ans, ROWS, TODAY) == "wrong_list"


def test_names_compared_by_the_name_rule() -> None:
    expected = {"action": "count", "field": "customer_name_short", "op": "eq",
                "value": 'ООО "Альфа"'}
    ans = answered({**expected, "value": "Альфа"})
    assert qt.judge(question(expected), ans, ROWS, TODAY) == "right"
    ans = answered({**expected, "value": "Бета"})
    assert qt.judge(question(expected), ans, ROWS, TODAY) == "wrong_query"


def test_party_matches_the_chosen_side() -> None:
    expected = {"action": "list", "field": "party", "op": "eq", "value": "Гамма"}
    ans = answered(expected)
    assert ans.result is not None and ans.result.query.side == "contractor"
    assert qt.judge(question(expected), ans, ROWS, TODAY) == "right"
    direct = answered({**expected, "field": "contractor_name_short"})
    assert qt.judge(question(expected), direct, ROWS, TODAY) == "right"


def test_period_compared_after_validation() -> None:
    expected = {"action": "list", "field": "contract_end_date", "op": "eq", "value": "this_year"}
    ans = answered({"action": "list", "field": "contract_end_date", "op": "between",
                    "value": "2026-01-01", "value_to": "2026-12-31"})
    assert qt.judge(question(expected), ans, ROWS, TODAY) == "right"


# --- the summary -----------------------------------------------------------------


def rows_of_a_run() -> list[object]:
    return [
        qt.Row(1, "template", "right", "answered", False, 2.0),
        qt.Row(2, "template", "wrong_query", "answered", True, 4.0),
        qt.Row(3, "template", "right", "answered", False, 3.0),
        qt.Row(4, "analyst", "wrong_outcome", "refused", False, 1.0),
        qt.Row(5, "analyst", "right", "clarify", False, 10.0),
        qt.Row(6, "analyst", "wrong_list", "answered", False, 5.0),
    ]


def test_summary_counts() -> None:
    s = qt.summarize(rows_of_a_run())
    assert (s.questions, s.right_template, s.template, s.right_analyst, s.analyst) == (
        6, 2, 3, 1, 3)
    assert s.wrong_query == [2] and s.wrong_outcome == [4] and s.wrong_list == [6]
    assert s.retried == 1
    assert s.outcomes == {"answered": 4, "refused": 1, "clarify": 1}
    assert (s.median_seconds, s.max_seconds) == (3.5, 10.0)


def test_render_holds_numbers_only() -> None:
    text = "\n".join(qt.render(qt.summarize(rows_of_a_run())))
    assert "по шаблонам 2 из 3" in text and "аналитика 1 из 3" in text
    assert "неверный запрос: 2" in text
    assert "неверный исход: 4" in text
    assert "неверный список: 6" in text
    assert "повторов 1" in text
    assert "медиана 3,5 с" in text and "наибольшее 10,0 с" in text
    assert SECRET not in text


# --- what the model asked, for a wrong query (no value; Б4 2026-11-28) ------------


def test_query_detail_names_action_field_and_op_only() -> None:
    expected = {**AMOUNT, "value": "2000000"}
    ans = answered({**AMOUNT, "field": "amount_without_vat", "value": "2000000"})
    got = qt.query_detail(question(expected), ans, TODAY)
    assert got == "ожидалось list amount_with_vat gt, модель list amount_without_vat gt"
    assert "2000000" not in got and "2 000 000" not in got


def test_query_detail_says_when_only_the_value_differs() -> None:
    ans = answered({**AMOUNT, "value": "150001"})
    assert qt.query_detail(question(AMOUNT), ans, TODAY) == (
        "ожидалось list amount_with_vat gt, модель list amount_with_vat gt; значение другое")


def test_query_detail_names_the_chosen_side() -> None:
    expected = {"action": "count", "field": "party", "op": "eq", "value": "Гамма"}
    ans = answered({**expected, "action": "list"})
    assert qt.query_detail(question(expected), ans, TODAY) == (
        "ожидалось count party eq, модель list party→contractor_name_short eq")


def test_summary_lists_the_details_of_wrong_queries() -> None:
    rows = [qt.Row(1, "template", "right", "answered", False, 2.0),
            qt.Row(2, "analyst", "wrong_query", "answered", False, 3.0,
                   "ожидалось count a eq, модель list a eq")]
    text = qt.render(qt.summarize(rows))
    assert "    2: ожидалось count a eq, модель list a eq" in text
