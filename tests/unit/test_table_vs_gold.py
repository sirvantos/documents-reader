"""Pure helpers of scripts/table_vs_gold.py (feature 10, quickstart Б3 check).

The script asks one question with `ask_table`, runs the same checked query over the
analyst's gold values (feature 02) instead of the extracted ones and prints how the lists
differ — counts and document ids only (principle I).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

from docreader import table_query as tq
from docreader.checks import CellState
from docreader.table_prompt import TableReply

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "table_vs_gold", ROOT / "scripts" / "table_vs_gold.py")
assert _spec is not None and _spec.loader is not None
tg = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = tg
_spec.loader.exec_module(tg)

SECRET = 'ООО "Секрет-Вымысел"'


def test_gold_rows_from_records() -> None:
    rows = tg.gold_rows(
        ["D-0001", "D-0002", "D-0003"],
        [("D-0001", "amount_with_vat", "value", ["1200000.00"]),
         ("D-0001", "contract_end_date", "absent", []),
         ("D-0002", "amount_with_vat", "value", ["900000.00", "900000.00"])],
    )
    assert [r.document_id for r in rows] == ["D-0001", "D-0002", "D-0003"]
    one = rows[0].cells
    assert (one["amount_with_vat"].state, one["amount_with_vat"].value) == (CellState.EFFECTIVE,
                                                                            "1200000.00")
    assert one["contract_end_date"].state is CellState.NOT_FOUND
    assert one["contract_number"].state is CellState.NO_EXTRACTION  # no gold for the field
    assert rows[2].cells["amount_with_vat"].state is CellState.NO_EXTRACTION


def test_compare_lines_hold_counts_and_ids_only() -> None:
    q = tq.validate(TableReply.model_validate(
        {"kind": "query", "action": "list", "field": "customer_name_short", "op": "eq",
         "value": SECRET}), date(2026, 11, 28))
    assert isinstance(q, tq.TableQuery)
    rows = tg.gold_rows(["D-0001", "D-0002", "D-0003"], [
        ("D-0001", "customer_name_short", "value", [SECRET]),
        ("D-0002", "customer_name_short", "value", [SECRET]),
    ])
    gold = tq.execute(q, rows, False)
    lines = tg.compare_lines(["D-0001", "D-0003"], gold)
    text = "\n".join(lines)
    assert lines[0] == "ответ 2, эталон 2, совпало 1"
    assert "лишние в ответе: D-0003" in lines
    assert "нет в ответе: D-0002" in lines
    assert "без эталона поля условия: 1 — D-0003" in lines
    assert "Секрет" not in text
