"""How parties and contract numbers repeat across contracts, for table answers (feature 10).

Counts only. Run from the repository root after extraction (`docreader extract`); no model
runs:

    uv run --env-file .env python scripts/survey_table_answers.py

It reads the found values of feature 05 for the two short names and the contract number
and counts, never printing a value, a name or a file name:

1–2. Short names of the customer and of the contractor: values, distinct spellings,
   organisations (groups of spellings that the feature 02 rule `values.same_value` counts
   as the same), organisations written in more than one way, organisations by number of
   contracts; what a wider match «by part of the name» would join (the same name in quotes
   with another legal form; a name in quotes inside another's, or holding another's);
   names without a legal form and quotes; legal forms (abbreviations only).
3. Organisations that are a customer in one contract and a contractor in another.
4. Contract numbers: values, distinct, numbers found in more than one contract.

The answers of clarify on how a name in a question is matched with the table (spec
`specs/011-table-answers/spec.md`, FR-005) rest on these numbers. The summary is saved
to `$DOCREADER_DATA_DIR/reports/survey-table-answers-….txt` and may be sent to the agent.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from docreader import catalog
from docreader.values import canonical_short_name, same_value

VERSION = 1
SIDES = ("customer_name_short", "contractor_name_short")
NUMBER = "contract_number"
FIELDS = (*SIDES, NUMBER)

_FORM_AND_QUOTED = re.compile(r'^(\S+) "([^"]+)"$')
NO_FORM = "без формы"


# --- pure counting ------------------------------------------------------------------------


def group_names(field_name: str, names: Sequence[str]) -> list[list[str]]:
    """Groups of the names (one entry per contract) that `same_value` joins, transitively."""
    spec = catalog.field(field_name)
    parent = list(range(len(names)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if root(i) != root(j) and same_value(spec, names[i], names[j]):
                parent[root(j)] = root(i)
    groups: dict[int, list[str]] = {}
    for i, name in enumerate(names):
        groups.setdefault(root(i), []).append(name)
    return list(groups.values())


def _form_and_quoted(name: str) -> tuple[str, str] | None:
    match = _FORM_AND_QUOTED.match(canonical_short_name(name))
    return (match[1], match[2].casefold()) if match else None


def partial_stats(groups: Sequence[Sequence[str]]) -> dict[str, int]:
    """What a match by part of the name would join that the feature 02 rule keeps apart."""
    parts = [_form_and_quoted(g[0]) for g in groups]
    quoted = [p[1] for p in parts if p is not None]
    same = sum(1 for q in quoted if quoted.count(q) > 1)
    inside = sum(
        1 for i, q in enumerate(quoted)
        if any(j != i and o != q and (q in o or o in q) for j, o in enumerate(quoted))
    )
    return {
        "same_quoted_other_form": same,
        "quoted_inside_another": inside,
        "without_quotes": sum(1 for p in parts if p is None),
    }


def size_buckets(groups: Sequence[Sequence[str]]) -> dict[str, int]:
    """Organisations by the number of contracts they appear in."""
    buckets = {"1": 0, "2–5": 0, "6+": 0}
    for group in groups:
        n = len(group)
        buckets["1" if n == 1 else "2–5" if n <= 5 else "6+"] += 1
    return buckets


def on_both_sides(customers: Sequence[Sequence[str]], contractors: Sequence[Sequence[str]]) -> int:
    """Customer organisations that are also a contractor somewhere (by the same rule)."""
    spec = catalog.field(SIDES[1])
    return sum(
        1 for c in customers
        if any(same_value(spec, c[0], k[0]) for k in contractors)
    )


def form_counts(names: Sequence[str]) -> dict[str, int]:
    """Legal forms of the names, abbreviated; a name without form and quotes is «без формы»."""
    counts: Counter[str] = Counter()
    for name in names:
        part = _form_and_quoted(name)
        counts[part[0] if part else NO_FORM] += 1
    return dict(counts)


def number_stats(numbers: Sequence[str]) -> dict[str, int]:
    counts = Counter(n.strip() for n in numbers)
    return {
        "values": len(numbers),
        "distinct": len(counts),
        "repeated": sum(1 for n in counts.values() if n > 1),
    }


@dataclass
class Survey:
    documents: int = 0
    names: dict[str, list[str]] = field(default_factory=lambda: {s: [] for s in SIDES})
    numbers: list[str] = field(default_factory=list)


def survey_documents(docs: Sequence[Mapping[str, str]]) -> Survey:
    """`docs`: per contract, the found normalized values by field name."""
    survey = Survey(documents=len(docs))
    for doc in docs:
        for side in SIDES:
            if doc.get(side):
                survey.names[side].append(doc[side])
        if doc.get(NUMBER):
            survey.numbers.append(doc[NUMBER])
    return survey


def _share(n: int, total: int) -> str:
    return f"{n} ({100 * n / total:.0f}%)" if total else str(n)


def summary_lines(survey: Survey) -> list[str]:
    lines = [f"Договоров с полями: {survey.documents}"]
    groups = {side: group_names(side, survey.names[side]) for side in SIDES}
    for i, side in enumerate(SIDES, start=1):
        names, side_groups = survey.names[side], groups[side]
        variants = sum(1 for g in side_groups if len(set(g)) > 1)
        partial = partial_stats(side_groups)
        sizes = size_buckets(side_groups)
        forms = form_counts(names)
        total = len(side_groups)
        lines += [
            "",
            f"{i}. {side}:",
            f"  значений {len(names)}, разных написаний {len(set(names))}, "
            f"организаций по правилу фичи 02 {total}",
            f"  организаций с несколькими написаниями: {_share(variants, total)}",
            "  организаций по числу договоров: "
            + ", ".join(f"{k} — {v}" for k, v in sizes.items()),
            "  при сопоставлении по части названия объединились бы:",
            "    то же название в кавычках, другая форма: "
            + _share(partial["same_quoted_other_form"], total),
            "    название в кавычках входит в другое: "
            + _share(partial["quoted_inside_another"], total),
            f"  без формы и кавычек: {_share(partial['without_quotes'], total)}",
            "  формы: " + ", ".join(
                f"{k} {v}" for k, v in sorted(forms.items(), key=lambda kv: (-kv[1], kv[0]))
            ),
        ]
    both = on_both_sides(groups[SIDES[0]], groups[SIDES[1]])
    numbers = number_stats(survey.numbers)
    lines += [
        "",
        f"3. Организаций и заказчиком, и подрядчиком: {both} "
        f"(организаций-заказчиков {len(groups[SIDES[0]])})",
        "",
        f"4. Номера договоров: значений {numbers['values']}, разных {numbers['distinct']}, "
        f"встречаются в нескольких договорах {numbers['repeated']}",
    ]
    return lines


# --- database --------------------------------------------------------------------------------


def load_documents(conn: Any) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT document_id, field, value_normalized FROM field_value"
        " WHERE result = 'found' AND field = ANY(%s) ORDER BY document_id, field",
        (list(FIELDS),),
    ).fetchall()
    by_doc: dict[str, dict[str, str]] = {}
    for doc_id, name, value in rows:
        if value:
            by_doc.setdefault(doc_id, {})[name] = str(value)
    return [by_doc[d] for d in sorted(by_doc)]


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    argparse.ArgumentParser(
        description="Как стороны и номера повторяются в договорах (фича 10): только числа и доли."
    ).parse_args(argv)

    from docreader import db
    from docreader.config import load_settings
    from docreader.errors import EnvironmentProblem, UserError

    try:
        settings = load_settings()
        conn = db.connect(settings)
        db.ensure_schema_current(conn)
        docs = load_documents(conn)
    except (EnvironmentProblem, UserError) as exc:
        print(f"\nОстановлено: {exc}", file=sys.stderr)
        return 1
    lines = [
        f"Опрос для ответов по таблице (фича 10) — только числа и доли (версия {VERSION})",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        "",
        *summary_lines(survey_documents(docs)),
    ]
    text = "\n".join(lines) + "\n"
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"survey-table-answers-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
