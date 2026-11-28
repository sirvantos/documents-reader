"""Pure helpers of scripts/make_table_questions.py (feature 10, quickstart Б4; task T020).

Questions from fixed templates over the effective values (research R-12), each with the
query it expects. Printed: counts only, never a value or a question (principle I).
Written by the main session; the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).

Interface:
- `generate(rows: Sequence[DocRow], seed: int) -> list[Question]`;
  `Question(text, source, expected)`, `source == "template"`, `expected` a dict with
  `action`, `field`, `op`, `value` and, for `between`, `value_to` — strings as the model
  would write them; only cells `effective` are used;
- per field both actions («Сколько …» → count, «Какие …» → list): names — per distinct
  organisation (the table spelling); number — 5 contracts chosen with `seed`; amounts —
  `gt` thresholds at `statistics.quantiles(values, n=4)` (default method) rounded to whole
  rubles; dates — the
  most frequent year (`between` YYYY-01-01 … YYYY-12-31) and the period `next_year` (`eq`);
- `to_toml(questions) -> str` — `[[question]]` with `text`, `source`, `expected`, plus
  commented examples for the analyst (`expected_outcome`, `documents`);
- `summary_lines(questions, out) -> list[str]` — counts by field and action and the path;
- `write_set(out, text, *, force)` — `OutputExists` without `force` over an existing file;
- `DEFAULT_FILE == Path("questions") / "table-10.toml"`.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from docreader import table_query as tq
from docreader.checks import CellState
from docreader.table_prompt import TableReply

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_table_questions", ROOT / "scripts" / "make_table_questions.py")
assert _spec is not None and _spec.loader is not None
mk = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mk
_spec.loader.exec_module(mk)

EFF = CellState.EFFECTIVE


def cell(value: str | None, state: CellState = EFF) -> tq.Cell:
    return tq.Cell(state, value, None, ())


def row(n: int, customer: str, contractor: str, amount: str, end: str,
        state: CellState = EFF) -> tq.DocRow:
    return tq.DocRow(f"D-{n:04d}", {
        "contract_number": cell(f"К-{n}/2026"),
        "customer_name_short": cell(customer),
        "contractor_name_short": cell(contractor),
        "amount_without_vat": cell(amount, state),
        "amount_with_vat": cell(amount),
        "contract_end_date": cell(end),
    })


ROWS = [
    row(1, 'ООО "Альфа"', 'АО "Гамма"', "100000.00", "2026-12-31"),
    row(2, 'ООО "Альфа"', 'АО "Дельта"', "200000.00", "2026-06-30"),
    row(3, 'ООО "Бета"', 'АО "Гамма"', "300000.00", "2026-03-31"),
    row(4, 'ООО "Бета"', 'АО "Гамма"', "400000.00", "2027-12-31"),
    row(5, 'ООО "Бета"', 'АО "Гамма"', "500000.00", "2026-09-30"),
    row(6, 'ООО "Бета"', 'АО "Гамма"', "999999999.00", "2030-01-01", CellState.UNREVIEWED),
    row(7, 'ООО "Альфа"', 'АО "Гамма"', "600000.00", "2028-01-01"),
]


def by(questions, field: str):  # type: ignore[no-untyped-def]
    return [q for q in questions if q.expected["field"] == field]


def test_default_file() -> None:
    assert mk.DEFAULT_FILE == Path("questions") / "table-10.toml"


def test_every_question_is_a_valid_template_query() -> None:
    from datetime import date

    questions = mk.generate(ROWS, 0)
    assert questions
    for q in questions:
        assert q.source == "template" and q.text.strip()
        got = tq.validate(TableReply.model_validate({"kind": "query", **q.expected}),
                          date(2026, 11, 28))
        assert isinstance(got, tq.TableQuery), q


def test_both_actions_and_the_six_fields() -> None:
    questions = mk.generate(ROWS, 0)
    pairs = Counter((q.expected["field"], q.expected["action"]) for q in questions)
    for field in ("contract_number", "customer_name_short", "contractor_name_short",
                  "amount_without_vat", "amount_with_vat", "contract_end_date"):
        assert pairs[(field, "count")] >= 1 and pairs[(field, "list")] >= 1, field
    for q in questions:
        word = q.text.split()[0]
        assert word in ({"Сколько"} if q.expected["action"] == "count" else {"Какие", "Какой"})


def test_names_per_organisation() -> None:
    questions = mk.generate(ROWS, 0)
    customers = {q.expected["value"] for q in by(questions, "customer_name_short")}
    contractors = {q.expected["value"] for q in by(questions, "contractor_name_short")}
    assert customers == {'ООО "Альфа"', 'ООО "Бета"'}
    assert contractors == {'АО "Гамма"', 'АО "Дельта"'}
    assert len(by(questions, "customer_name_short")) == 4  # two organisations × two actions


def test_five_numbers_chosen_by_the_seed() -> None:
    first = {q.expected["value"] for q in by(mk.generate(ROWS, 0), "contract_number")}
    assert len(first) == 5
    assert first == {q.expected["value"] for q in by(mk.generate(ROWS, 0), "contract_number")}
    other = [{q.expected["value"] for q in by(mk.generate(ROWS, s), "contract_number")}
             for s in range(1, 6)]
    assert any(o != first for o in other)


def test_amount_thresholds_at_the_quartiles_of_effective_values() -> None:
    questions = by(mk.generate(ROWS, 0), "amount_without_vat")
    # effective: 100k…600k (D-0006 is unreviewed and left out)
    assert {q.expected["op"] for q in questions} == {"gt"}
    assert {q.expected["value"] for q in questions} == {"175000", "350000", "525000"}
    assert len(questions) == 6


def test_dates_by_the_most_frequent_year_and_next_year() -> None:
    questions = by(mk.generate(ROWS, 0), "contract_end_date")
    year = [q for q in questions if q.expected["op"] == "between"]
    assert {(q.expected["value"], q.expected["value_to"]) for q in year} == {
        ("2026-01-01", "2026-12-31")}
    period = [q for q in questions if q.expected["value"] == "next_year"]
    assert {q.expected["op"] for q in period} == {"eq"}
    assert len(year) == 2 and len(period) == 2


def test_toml_round_trip_with_analyst_examples() -> None:
    questions = mk.generate(ROWS, 0)
    text = mk.to_toml(questions)
    data = tomllib.loads(text)
    assert len(data["question"]) == len(questions)
    for q, item in zip(questions, data["question"], strict=True):
        assert item == {"text": q.text, "source": "template", "expected": q.expected}
    commented = [line for line in text.splitlines() if line.startswith("#")]
    assert any("expected_outcome" in line for line in commented)
    assert any("documents" in line for line in commented)
    assert any('source = "analyst"' in line for line in commented)


def test_summary_holds_counts_only(tmp_path: Path) -> None:
    questions = mk.generate(ROWS, 0)
    text = "\n".join(mk.summary_lines(questions, tmp_path / "table-10.toml"))
    for secret in ("Альфа", "Гамма", "К-1/2026", "175000", "175 000", "2026-01-01"):
        assert secret not in text
    assert str(len(questions)) in text
    assert "table-10.toml" in text


def test_write_set_refuses_to_overwrite(tmp_path: Path) -> None:
    out = tmp_path / "questions" / "table-10.toml"
    mk.write_set(out, "a = 1\n", force=False)
    assert out.read_text(encoding="utf-8") == "a = 1\n"
    with pytest.raises(mk.OutputExists):
        mk.write_set(out, "a = 2\n", force=False)
    mk.write_set(out, "a = 2\n", force=True)
    assert out.read_text(encoding="utf-8") == "a = 2\n"
