"""The question set of quickstart Б3 (feature 08) from the extracted fields of feature 05.

Run from the repository root on the Mac, after `extract` and `index`:

    uv run --env-file .env python scripts/make_search_questions.py [--count 20] [--seed 0]

No model is used. Every found field whose quote lies in a current passage of its document
gives one candidate question from a fixed template («Какая цена договора без НДС?»); the
answer is that passage (`D-0015/2.1`). The chosen questions are written as TOML to
`$DOCREADER_DATA_DIR/questions/rerank-08.toml` (never over an existing file without
`--force`), with a commented example for the analyst's own questions. The analyst adds
5–10 questions about conditions (payment, penalties, terms) that the fields do not cover.

Printed: counts by field only — never a value, a quote or a question text (principle I).
"""

# No `from __future__ import annotations`: the tests load this file without registering it in
# sys.modules at first, and `@dataclass` then cannot resolve string annotations.

import argparse
import os
import random
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import psycopg

from docreader import search
from docreader.config import load_settings
from docreader.db import connect
from docreader.errors import EnvironmentProblem
from docreader.fields import FIELD_NAMES
from docreader.ids import format_clause_id

DEFAULT_FILE = Path("questions") / "rerank-08.toml"

# One question per prototype field; the answer is the clause of the field's quote.
TEMPLATES: dict[str, str] = {
    "contract_number": "Какой номер договора?",
    "customer_name_short": "Кто заказчик по договору?",
    "contractor_name_short": "Кто подрядчик (исполнитель) по договору?",
    "amount_without_vat": "Какая цена договора без НДС?",
    "amount_with_vat": "Какая цена договора с учётом НДС?",
    "contract_end_date": "До какого срока действует договор?",
}

_ANALYST_EXAMPLE = (
    "# Свои вопросы об условиях (оплата, неустойка, сроки) — по одному договору каждый;\n"
    "# ответ проверьте командой docreader passage D-…/…:\n"
    "#\n"
    "# [[question]]\n"
    '# text = "Какой срок оплаты?"\n'
    '# answer = "D-0015/2.2.1"\n'
    '# source = "analyst"\n'
)


class OutputExists(Exception):
    """The questions file exists and `--force` was not given."""


@dataclass(frozen=True, order=True)
class Candidate:
    document_id: str
    clause_key: str
    field: str


def collect(conn: psycopg.Connection) -> tuple[list[Candidate], int]:
    """Found fields whose quote clause is a current passage of the document's current text,
    and the number of found fields that are not (their answer could not be searched)."""
    rows = conn.execute(
        "SELECT f.document_id, f.clause_key, f.field,"
        " EXISTS (SELECT 1 FROM passage p JOIN document_text t"
        "  ON t.document_id = p.document_id"
        f"  WHERE {search.CURRENT_PASSAGE}"
        "  AND p.document_id = f.document_id AND p.clause_key = f.clause_key"
        "  AND f.source_text_sha256 = t.text_sha256)"
        " FROM field_value f WHERE f.result = 'found'"
        " ORDER BY f.document_id, f.field"
    ).fetchall()
    good = [Candidate(doc, key, field) for doc, key, field, ok in rows if ok]
    return good, len(rows) - len(good)


def choose(candidates: Sequence[Candidate], count: int, seed: int) -> list[Candidate]:
    """`count` candidates, the same for the same input and seed: fields in turn (in the
    order of the field catalogue), and a document is not repeated while unused documents
    are still reachable."""
    rng = random.Random(seed)
    queues: dict[str, list[Candidate]] = {}
    for field in FIELD_NAMES:
        group = sorted(c for c in candidates if c.field == field)
        rng.shuffle(group)
        if group:
            queues[field] = group
    chosen: list[Candidate] = []
    used_docs: set[str] = set()
    while len(chosen) < count and any(queues.values()):
        fresh = {c.document_id for q in queues.values() for c in q} - used_docs
        for queue in queues.values():
            if not queue or len(chosen) >= count:
                continue
            pick = next((c for c in queue if not fresh or c.document_id in fresh), None)
            if pick is None:
                continue
            queue.remove(pick)
            chosen.append(pick)
            used_docs.add(pick.document_id)
            fresh.discard(pick.document_id)
    return chosen


def _quoted(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_toml(chosen: Sequence[Candidate]) -> str:
    """The questions as TOML, then the commented example for the analyst's own ones."""
    parts = [
        "# Вопросы замера реранкера (quickstart Б3 фичи 08) из извлечённых полей фичи 05.\n"
        "# Записано scripts/make_search_questions.py; лишние вопросы можно удалить.\n"
    ]
    for c in chosen:
        parts.append(
            "\n[[question]]\n"
            f"text = {_quoted(TEMPLATES[c.field])}\n"
            f"answer = {_quoted(format_clause_id(c.document_id, c.clause_key))}\n"
            f"source = {_quoted('field:' + c.field)}\n"
        )
    parts.append("\n" + _ANALYST_EXAMPLE)
    return "".join(parts)


def _plural(n: int) -> str:
    if n % 100 in range(11, 15):
        return "вопросов"
    return {1: "вопрос", 2: "вопроса", 3: "вопроса", 4: "вопроса"}.get(n % 10, "вопросов")


def summary_lines(chosen: Sequence[Candidate], skipped: int, out: Path) -> list[str]:
    """Counts only: how many questions, by field, and found fields without a passage."""
    by_field = [
        f"{field} {n}"
        for field in FIELD_NAMES
        if (n := sum(1 for c in chosen if c.field == field))
    ]
    return [
        f"Записано {len(chosen)} {_plural(len(chosen))} в {out}",
        "  по полям: " + (", ".join(by_field) or "—"),
        f"  найденных полей без актуального отрывка: {skipped}",
        "Добавьте 5–10 своих вопросов об условиях (пример в конце файла).",
    ]


def write_set(out: Path, text: str, *, force: bool) -> None:
    if out.exists() and not force:
        raise OutputExists(f"файл {out} уже есть — перезаписать: --force")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--out", help="the questions file (default: <data>/questions/rerank-08.toml)"
    )
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
            candidates, skipped = collect(conn)
    except EnvironmentProblem as exc:
        print(exc, file=sys.stderr)
        return 2
    if not candidates:
        print(
            f"нет найденных полей с актуальным отрывком (без отрывка: {skipped}) — "
            "выполните docreader extract и docreader index",
            file=sys.stderr,
        )
        return 1
    chosen = choose(candidates, args.count, args.seed)
    out = Path(args.out) if args.out else settings.data_dir / DEFAULT_FILE
    try:
        write_set(out, to_toml(chosen), force=args.force)
    except OutputExists as exc:
        print(exc, file=sys.stderr)
        return 1
    print("\n".join(summary_lines(chosen, skipped, out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
