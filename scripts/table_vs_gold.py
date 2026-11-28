"""Check one table answer against the gold set of feature 02 (feature 10, quickstart Б3).

Run from the repository root on the Mac, with the language model server running:

    uv run --env-file .env python scripts/table_vs_gold.py "Сколько договоров дороже миллиона?"

The question is asked with `table_answer.ask_table`; the checked query it gave is then run
by `table_query.execute` over the analyst's gold values (`gold_field`) instead of the
extracted ones. The two lists are compared. A document without a gold value of the
condition field is listed apart: a difference there is not an error of the answer.

Printed: the outcome, counts and document ids only — never the question, the condition or
a value (principle I).
"""

# No `from __future__ import annotations`: the tests load this file with importlib.

import argparse
import sys
from collections.abc import Iterable, Sequence

from docreader import table_answer
from docreader import table_query as tq
from docreader.checks import FIELDS, CellState
from docreader.config import load_settings
from docreader.db import connect
from docreader.errors import EnvironmentProblem, UserError

GoldRecord = tuple[str, str, str, Sequence[str]]  # document, field, state, values_normalized


def gold_rows(registry: Sequence[str], records: Iterable[GoldRecord]) -> list[tq.DocRow]:
    """The table of gold values: `value` → effective, `absent` → not found, none → no gold."""
    cells: dict[str, dict[str, tq.Cell]] = {doc: {} for doc in registry}
    for doc, field, state, values in records:
        if doc not in cells or field not in FIELDS:
            continue
        if state == "value" and values:
            cells[doc][field] = tq.Cell(CellState.EFFECTIVE, values[0], None, ())
        else:
            cells[doc][field] = tq.Cell(CellState.NOT_FOUND, None, None, ())
    missing = tq.Cell(CellState.NO_EXTRACTION, None, None, ())
    return [tq.DocRow(doc, {f: cells[doc].get(f, missing) for f in FIELDS}) for doc in registry]


def compare_lines(answer_ids: Sequence[str], gold: tq.Result) -> list[str]:
    a = set(answer_ids)
    g = {item.row.document_id for item in gold.rows}
    no_gold = list(gold.excluded.get(CellState.NO_EXTRACTION.value, ()))
    lines = [
        f"ответ {len(a)}, эталон {len(g)}, совпало {len(a & g)}",
        f"лишние в ответе: {' '.join(sorted(a - g)) or '—'}",
        f"нет в ответе: {' '.join(sorted(g - a)) or '—'}",
    ]
    if no_gold:
        lines.append(f"без эталона поля условия: {len(no_gold)} — {' '.join(no_gold)}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Сверить ответ по таблице с эталоном фичи 02")
    p.add_argument("question", metavar="ВОПРОС")
    args = p.parse_args(argv)
    try:
        settings = load_settings()
        with connect(settings) as conn:
            answer = table_answer.ask_table(conn, settings, args.question)
            if answer.result is None:
                print(f"исход: {answer.outcome.value} — сверять нечего")
                return 0
            registry = [r[0] for r in conn.execute("SELECT id FROM document ORDER BY seq")]
            records = conn.execute(
                "SELECT document_id, field, state, values_normalized FROM gold_field"
            ).fetchall()
    except UserError as exc:
        print(exc, file=sys.stderr)
        return 1
    except EnvironmentProblem as exc:
        print(exc, file=sys.stderr)
        return 2
    gold = tq.execute(answer.result.query, gold_rows(registry, records), False)
    ids = [item.row.document_id for item in answer.result.rows]
    for line in compare_lines(ids, gold):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
