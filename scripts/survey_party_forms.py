"""The shapes of the party names in the table, counts only (feature 10, Б4 question 51).

Run from the repository root on the Mac, after `check`; no model runs:

    uv run --env-file .env python scripts/survey_party_forms.py

For the effective values (feature 06) of the customer and the contractor it counts the
shapes of the names: an abbreviated legal form with a name in quotes, the form written in
full, a name in quotes alone, and the shapes of an individual entrepreneur («ИП» or
«индивидуальный предприниматель» with a surname, initials or a full name). The rule that
matches «ИП Фамилия» of a question with the table rests on these numbers. Printed: shapes
and counts only — never a name (principle I); the output may be sent to the agent.
"""

# No `from __future__ import annotations`: the tests load this file with importlib.

import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence

from docreader.values import SPELLED_FORMS

SIDES = ("customer_name_short", "contractor_name_short")
_FORMS = ("ОАО", "ЗАО", "ПАО", "НАО", "АО", "ООО", "ОДО", "ФГУП", "ГУП", "МУП")
_WORD = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?"
_INITIALS = r"[А-ЯЁ]\.\s?[А-ЯЁ]\.?"
_SHAPES = (
    ("form_quoted", re.compile(r"(?:" + "|".join(_FORMS) + r') "[^"]+"')),
    ("spelled_quoted", re.compile(r"(?:" + "|".join(SPELLED_FORMS) + r') "[^"]+"', re.I)),
    ("quoted_no_form", re.compile(r'"[^"]+"')),
    ("ip_surname_initials", re.compile(rf"ИП {_WORD} {_INITIALS}")),
    ("ip_full_name", re.compile(rf"ИП {_WORD} {_WORD} {_WORD}")),
    ("ip_surname", re.compile(rf"ИП {_WORD}")),
    ("ip_spelled_initials", re.compile(rf"индивидуальный предприниматель {_WORD} {_INITIALS}",
                                       re.I)),
    ("ip_spelled_full_name", re.compile(
        rf"индивидуальный предприниматель {_WORD} {_WORD} {_WORD}", re.I)),
    ("ip_other", re.compile(r"(?:ИП|индивидуальный предприниматель)\b.*", re.I)),
    ("person_initials", re.compile(rf"{_WORD} {_INITIALS}")),
)


def shape(name: str) -> str:
    text = " ".join(name.split())
    return next((label for label, rx in _SHAPES if rx.fullmatch(text)), "other")


def summary_lines(values: Mapping[str, Sequence[str]]) -> list[str]:
    lines = ["Формы наименований сторон (действующие значения):"]
    for side in SIDES:
        names = values.get(side, ())
        counts = Counter(shape(n) for n in names)
        parts = ", ".join(f"{label} {n}" for label, n in counts.most_common())
        lines.append(f"  {side}: {len(names)} — {parts or 'нет'}")
    return lines


def main() -> int:
    from docreader.checks import CellState
    from docreader.config import load_settings
    from docreader.db import connect
    from docreader.errors import EnvironmentProblem
    from docreader.table_answer import load_rows

    try:
        settings = load_settings()
        with connect(settings) as conn:
            rows = load_rows(conn, settings)
    except EnvironmentProblem as exc:
        print(exc, file=sys.stderr)
        return 2
    values: dict[str, list[str]] = {side: [] for side in SIDES}
    for row in rows:
        for side in SIDES:
            cell = row.cells[side]
            if cell.state is CellState.EFFECTIVE and cell.value is not None:
                values[side].append(cell.value)
    for line in summary_lines(values):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
