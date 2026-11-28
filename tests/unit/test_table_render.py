"""The text of `docreader ask-table` for an answered question (feature 10, T010).

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).

Interface (data-model.md, contracts/cli.md):
- `docreader.table_answer`: `TableOutcome` (StrEnum: `answered`, `refused`, `clarify`,
  `unsupported`, `rejected`, `failed`); `TableProvenance(code_version, llm_model,
  prompt_version, prompt_sha256, checks_version)`; `TableAnswer(question, outcome, result,
  reason, other, retried, today, provenance, seconds)`;
- `docreader.render.render_table_text(answer, list_rows) -> str`.

Text of an answered question: first line «По таблице — ответ: N договоров; учтено K из M,
не учтено J; повторов R; T с» (no value, no question); a blank line; «Условие: …»
(`table_query.describe`); «Совпали наименования: a, b» for a name condition with matches;
a blank line; «Договоры (N):» (`list`) or «Из каких договоров (N):» (`count`) with one line
per contract — «  D-0001   № <number>   заказчик <name>   подрядчик <name>   без НДС <amount>
  с НДС <amount>   окончание <date>   (<clause of the condition field>)»; a cell that is
not effective shows «<value>, требует просмотра» (unreviewed) or «—, <state>»; more than
`list_rows` contracts → «  … ещё N — полный список: --json»; zero contracts → «Таких
договоров нет.» instead of the list; a blank line; «Получено: код …; модель …, подсказка
10.1; правила 06.1; сегодня 2026-11-28».
"""

from __future__ import annotations

from datetime import date

import pytest

from docreader import render
from docreader import table_query as tq
from docreader.checks import CellState
from docreader.table_answer import TableAnswer, TableOutcome, TableProvenance
from docreader.table_prompt import TableReply

TODAY = date(2026, 11, 28)
EFF = CellState.EFFECTIVE
PROVENANCE = TableProvenance(
    code_version="1d241f9", llm_model="qwen3.6-27b-4bit", prompt_version="10.1",
    prompt_sha256="ab" * 32, checks_version="06.1",
)


def cell(state: CellState = EFF, value: str | None = None, clause: str | None = None) -> tq.Cell:
    return tq.Cell(state, value, clause, ())


def row(n: int, **cells: tq.Cell) -> tq.DocRow:
    doc = f"D-{n:04d}"
    base = {
        "contract_number": cell(EFF, f"К-{n}/2026", f"{doc}/преамбула"),
        "customer_name_short": cell(EFF, 'АО "Бета"', f"{doc}/преамбула"),
        "contractor_name_short": cell(EFF, 'ООО "Альфа"', f"{doc}/преамбула"),
        "amount_without_vat": cell(EFF, "1000000.00", f"{doc}/2.1"),
        "amount_with_vat": cell(EFF, "1200000.00", f"{doc}/2.1"),
        "contract_end_date": cell(EFF, "2026-03-31", f"{doc}/5.1"),
    }
    base.update(cells)
    return tq.DocRow(doc, base)


def query(**over) -> tq.TableQuery:
    base = {"kind": "query", "action": "list", "field": "contractor_name_short", "op": "eq",
            "value": "ООО «Альфа»"}
    base.update(over)
    got = tq.validate(TableReply.model_validate(base), TODAY)
    assert isinstance(got, tq.TableQuery)
    return got


def answer(q: tq.TableQuery, rows: list[tq.DocRow], *, retried: bool = False,
           seconds: float = 4.24, include_unreviewed: bool = False) -> TableAnswer:
    result = tq.execute(q, rows, include_unreviewed)
    return TableAnswer(
        question="Какие договоры с подрядчиком Альфа?", outcome=TableOutcome.ANSWERED,
        result=result, reason=None, other=None, retried=retried, today=TODAY,
        provenance=PROVENANCE, seconds=seconds,
    )


def text(a: TableAnswer, list_rows: int = 20) -> list[str]:
    return render.render_table_text(a, list_rows).splitlines()


def test_first_line_holds_counts_retries_and_time_only() -> None:
    rows = [row(3), row(7), row(5, contractor_name_short=cell(CellState.REJECTED))]
    lines = text(answer(query(), rows))
    assert lines[0] == ("По таблице — ответ: 2 договора; учтено 2 из 3, не учтено 1; "
                        "повторов 0; 4,2 с")
    lines = text(answer(query(), rows, retried=True, seconds=12.0))
    assert lines[0].endswith("; повторов 1; 12,0 с")


@pytest.mark.parametrize(
    ("n", "words"),
    [(0, "0 договоров"), (1, "1 договор"), (2, "2 договора"), (4, "4 договора"),
     (5, "5 договоров"), (11, "11 договоров"), (21, "21 договор"), (22, "22 договора")],
)
def test_plural_of_contracts(n: int, words: str) -> None:
    other = row(99, contractor_name_short=cell(EFF, 'ООО "Гамма"'))
    rows = [row(i) for i in range(1, n + 1)] + [other]
    first = text(answer(query(), rows), list_rows=50)[0]
    assert first.startswith(f"По таблице — ответ: {words}; ")


def test_condition_matched_names_and_list() -> None:
    rows = [row(3), row(7, contractor_name_short=cell(
        EFF, 'общество с ограниченной ответственностью "Альфа"', "D-0007/преамбула"))]
    lines = text(answer(query(), rows))
    assert lines[1] == ""
    assert lines[2] == 'Условие: подрядчик — ООО "Альфа"'
    assert lines[3] == ('Совпали наименования: ООО "Альфа", '
                        'общество с ограниченной ответственностью "Альфа"')
    assert lines[4] == ""
    assert lines[5] == "Договоры (2):"
    assert lines[6] == ('  D-0003   № К-3/2026   заказчик АО "Бета"   подрядчик ООО "Альфа"   '
                        "без НДС 1 000 000,00   с НДС 1 200 000,00   окончание 2026-03-31   "
                        "(D-0003/преамбула)")
    assert lines[7].startswith("  D-0007   ")


def test_clause_is_the_clause_of_the_condition_field() -> None:
    lines = text(answer(query(field="amount_with_vat", op="gt", value="1"), [row(3)]))
    assert lines[2] == "Условие: цена с НДС больше 1,00 руб."
    assert not any(line.startswith("Совпали наименования") for line in lines)
    listing = next(line for line in lines if line.startswith("  D-0003"))
    assert listing.endswith("(D-0003/2.1)")


def test_cells_that_are_not_effective_show_their_state() -> None:
    rows = [row(3, amount_with_vat=cell(CellState.UNREVIEWED, "1250000.00", "D-0003/2.1"),
                amount_without_vat=cell(CellState.REJECTED),
                contract_end_date=cell(CellState.NOT_FOUND))]
    listing = next(line for line in text(answer(query(), rows)) if line.startswith("  D-0003"))
    assert "с НДС 1 250 000,00, требует просмотра" in listing
    assert "без НДС —, отклонено" in listing
    assert "окончание —, не найдено" in listing


def test_count_lists_the_contracts_under_its_own_heading() -> None:
    lines = text(answer(query(action="count"), [row(3), row(4)]))
    assert "Из каких договоров (2):" in lines
    assert "Договоры (2):" not in lines


def test_list_is_cut_after_list_rows() -> None:
    rows = [row(i) for i in range(1, 8)]
    lines = text(answer(query(), rows), list_rows=5)
    listed = [line for line in lines if line.startswith("  D-")]
    assert [line.split()[0] for line in listed] == ["D-0001", "D-0002", "D-0003", "D-0004",
                                                    "D-0005"]
    assert "  … ещё 2 — полный список: --json" in lines
    assert lines[0].startswith("По таблице — ответ: 7 договоров; ")
    assert not any("ещё" in line for line in text(answer(query(), rows), list_rows=7))


def test_zero_contracts() -> None:
    lines = text(answer(query(value="Гамма"), [row(1), row(2)]))
    assert lines[0].startswith("По таблице — ответ: 0 договоров; учтено 2 из 2, не учтено 0; ")
    assert "Условие: подрядчик — Гамма" in lines
    assert "Таких договоров нет." in lines
    assert not any(line.startswith(("Договоры (", "Из каких договоров (")) for line in lines)


def test_provenance_line_is_last() -> None:
    lines = text(answer(query(), [row(1)]))
    assert lines[-2] == ""
    assert lines[-1] == ("Получено: код 1d241f9; модель qwen3.6-27b-4bit, подсказка 10.1; "
                         "правила 06.1; сегодня 2026-11-28")


def test_text_ends_with_a_newline() -> None:
    assert render.render_table_text(answer(query(), [row(1)]), 20).endswith("\n")
