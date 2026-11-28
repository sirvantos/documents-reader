"""The question set of quickstart Б4 (feature 10) from the effective values of the table.

Run from the repository root on the Mac, after `extract` and `check` (and the analyst's
decisions):

    uv run --env-file .env python scripts/make_table_questions.py [--force] [--seed 0]

No model is used. Questions come from fixed templates over the effective values (research
R-12): per field the actions «сколько» (count) and «какие» (list). Names: one pair per
organisation; contract number: 5 contracts chosen with `--seed`; amounts: `gt` thresholds
at the quartiles of the values; dates: the most frequent year and the next year. Each
question carries the query it expects. The set is written as TOML to
`$DOCREADER_DATA_DIR/questions/table-10.toml` (never over an existing file without
`--force`), with commented examples for the analyst's own questions.

Printed: counts by field and action only — never a value or a question text (principle I).
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules at first, and `@dataclass` then cannot resolve string annotations.

import argparse
import os
import random
import statistics
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from docreader.checks import CellState
from docreader.config import load_settings
from docreader.db import connect
from docreader.errors import EnvironmentProblem
from docreader.table_answer import load_rows
from docreader.table_query import DocRow

DEFAULT_FILE = Path("questions") / "table-10.toml"
NUMBER_QUESTIONS = 5

_ANALYST_EXAMPLE = (
    "# Свои вопросы (отказ, уточнение, нетабличные вопросы, составные условия) — по одному\n"
    "# запросу или по одному ожидаемому исходу на вопрос; `documents` необязателен:\n"
    "#\n"
    "# [[question]]\n"
    '# text = "Какие договоры с ценой больше миллиона?"\n'
    '# source = "analyst"\n'
    '# expected = {action = "list", field = "amount_with_vat", op = "gt", value = "1000000"}\n'
    '# documents = ["D-0003", "D-0007"]\n'
    "#\n"
    "# [[question]]\n"
    '# text = "Что такое неустойка?"\n'
    '# source = "analyst"\n'
    '# expected_outcome = "refused"  # или "clarify", "unsupported"\n'
)


class OutputExists(Exception):
    """The questions file exists and `--force` was not given."""


@dataclass(frozen=True)
class Question:
    text: str
    source: str
    expected: dict[str, str]


def _effective(rows: Sequence[DocRow], field: str) -> list[str]:
    return [
        c.value
        for row in rows
        if (c := row.cells[field]).state is CellState.EFFECTIVE and c.value is not None
    ]


def _expected(
    action: str, field: str, op: str, value: str, value_to: str | None = None
) -> dict[str, str]:
    result = {"action": action, "field": field, "op": op, "value": value}
    if value_to is not None:
        result["value_to"] = value_to
    return result


def _pair(
    count_text: str, list_text: str, field: str, op: str, value: str, value_to: str | None = None
) -> list[Question]:
    return [
        Question(count_text, "template", _expected("count", field, op, value, value_to)),
        Question(list_text, "template", _expected("list", field, op, value, value_to)),
    ]


def _thousands(number: int) -> str:
    return f"{number:,}".replace(",", " ")


def generate(rows: Sequence[DocRow], seed: int) -> list[Question]:
    """The questions for the effective values of `rows`; the same input and seed, the same set."""
    questions: list[Question] = []
    sides = (("customer_name_short", "заказчиком"), ("contractor_name_short", "подрядчиком"))
    for field, word in sides:
        for name in sorted(set(_effective(rows, field))):
            questions += _pair(
                f"Сколько договоров с {word} {name}?",
                f"Какие договоры с {word} {name}?",
                field, "eq", name,
            )
    numbers = sorted(set(_effective(rows, "contract_number")))
    for number in sorted(random.Random(seed).sample(numbers, min(NUMBER_QUESTIONS, len(numbers)))):
        questions += _pair(
            f"Сколько договоров с номером {number}?",
            f"Какой договор с номером {number}?",
            "contract_number", "eq", number,
        )
    for field, label in (("amount_without_vat", "без НДС"), ("amount_with_vat", "с НДС")):
        amounts = [Decimal(v) for v in _effective(rows, field)]
        if len(amounts) < 2:
            continue
        cuts = statistics.quantiles(amounts, n=4)
        for threshold in dict.fromkeys(
            int(cut.quantize(Decimal(1), rounding=ROUND_HALF_UP)) for cut in cuts
        ):
            text = _thousands(threshold)
            questions += _pair(
                f"Сколько договоров с ценой {label} больше {text} рублей?",
                f"Какие договоры с ценой {label} больше {text} рублей?",
                field, "gt", str(threshold),
            )
    years = Counter(v[:4] for v in _effective(rows, "contract_end_date"))
    if years:
        year = min(years, key=lambda y: (-years[y], y))
        questions += _pair(
            f"Сколько договоров заканчивается в {year} году?",
            f"Какие договоры заканчиваются в {year} году?",
            "contract_end_date", "between", f"{year}-01-01", f"{year}-12-31",
        )
        questions += _pair(
            "Сколько договоров заканчивается в следующем году?",
            "Какие договоры заканчиваются в следующем году?",
            "contract_end_date", "eq", "next_year",
        )
    return questions


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_toml(questions: Sequence[Question]) -> str:
    """The questions as TOML, then the commented examples for the analyst's own ones."""
    parts = [
        "# Вопросы замера табличных ответов (quickstart Б4 фичи 10) из действующих значений.\n"
        "# Записано scripts/make_table_questions.py; лишние вопросы можно удалить.\n"
    ]
    for q in questions:
        expected = ", ".join(f"{key} = {_quoted(value)}" for key, value in q.expected.items())
        parts.append(
            "\n[[question]]\n"
            f"text = {_quoted(q.text)}\n"
            f"source = {_quoted(q.source)}\n"
            f"expected = {{{expected}}}\n"
        )
    parts.append("\n" + _ANALYST_EXAMPLE)
    return "".join(parts)


def _plural(n: int) -> str:
    if n % 100 in range(11, 15):
        return "вопросов"
    return {1: "вопрос", 2: "вопроса", 3: "вопроса", 4: "вопроса"}.get(n % 10, "вопросов")


def summary_lines(questions: Sequence[Question], out: Path) -> list[str]:
    """Counts only: how many questions, by field and action."""
    pairs = Counter((q.expected["field"], q.expected["action"]) for q in questions)
    fields = list(dict.fromkeys(field for field, _ in pairs))
    by_field = [
        f"{field} {pairs[(field, 'count')] + pairs[(field, 'list')]}"
        f" (count {pairs[(field, 'count')]}, list {pairs[(field, 'list')]})"
        for field in fields
    ]
    return [
        f"Записано {len(questions)} {_plural(len(questions))} в {out}",
        "  по полям: " + (", ".join(by_field) or "—"),
        "Добавьте свои вопросы (пример в конце файла).",
    ]


def write_set(out: Path, text: str, *, force: bool) -> None:
    if out.exists() and not force:
        raise OutputExists(f"файл {out} уже есть — перезаписать: --force")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    parser.add_argument("--env-file", help="an env file; without it the environment is used")
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            for line in Path(args.env_file).read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() and not key.lstrip().startswith("#"):
                    os.environ[key.strip()] = value.strip()
        settings = load_settings()
        with connect(settings) as conn:
            rows = load_rows(conn, settings)
    except EnvironmentProblem as exc:
        print(exc, file=sys.stderr)
        return 2
    questions = generate(rows, args.seed)
    if not questions:
        print(
            "нет действующих значений — выполните docreader extract и docreader check",
            file=sys.stderr,
        )
        return 1
    out = settings.data_dir / DEFAULT_FILE
    try:
        write_set(out, to_toml(questions), force=args.force)
    except OutputExists as exc:
        print(exc, file=sys.stderr)
        return 1
    print("\n".join(summary_lines(questions, out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
