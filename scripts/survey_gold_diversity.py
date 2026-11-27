"""Which contracts would add variety to the gold set? Ids and group numbers only (feature 02).

Run from the repository root after extraction (`docreader extract`); no model runs:

    uv run --env-file .env python scripts/survey_gold_diversity.py [--pick 12]

It reads the feature 05 values of every contract with fields and groups the contracts by
four traits, each an abstract key computed here and never printed:

1. Contractor: the short name (legal form abbreviated, case ignored) — a hash.
2. Contract number shape: letters → «А», digits → «9», runs collapsed («9.9-9/А»).
3. Field results: which of the six fields were found and which were not.
4. Size: the number of pages, in buckets (1–5, 6–10, 11–20, 21+).

Groups are numbered by size (1 is the largest) and printed with their counts and ids,
the contracts already in the gold set marked with «*». Then `--pick N` proposes N
contracts outside the gold set, chosen one by one to bring in a group the gold set and
the earlier picks do not have yet, the smallest groups first.

Only counts, group numbers and document ids are printed and saved (to
`$DOCREADER_DATA_DIR/reports/survey-gold-diversity-….txt`): no names, no numbers, no
text. The summary may be sent to the agent.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

FIELDS = (
    "contract_number", "customer_name_short", "contractor_name_short",
    "amount_without_vat", "amount_with_vat", "contract_end_date",
)
NO_VALUE = "—"


# --- traits (pure; tested in tests/unit/test_survey_gold_diversity.py) ----------------------


def number_shape(value: str | None) -> str:
    """`08.0352-1369/ОКЭ` → `9.9-9/А`: letters and digits as one sign per run."""
    if not value:
        return NO_VALUE
    shape = re.sub(r"[^\W\d_]+", "А", value)
    shape = re.sub(r"\d+", "9", shape)
    return re.sub(r"\s+", " ", shape).strip()


def name_key(value: str | None) -> str:
    """A hash of a short name with its legal form abbreviated, case and spaces ignored."""
    if not value:
        return NO_VALUE
    from docreader.values import canonical_short_name

    canonical = canonical_short_name(value).casefold()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def results_key(results: dict[str, str]) -> str:
    """`found`/`not_found`/… of the six fields, in catalog order; a missing field is «—»."""
    return " ".join(results.get(f, NO_VALUE) for f in FIELDS)


def pages_bucket(pages: int) -> str:
    for top, label in ((5, "1–5"), (10, "6–10"), (20, "11–20")):
        if pages <= top:
            return label
    return "21+"


@dataclass(frozen=True)
class Doc:
    id: str
    contractor: str
    number: str
    results: str
    pages: str
    in_gold: bool


TRAITS: dict[str, Callable[[Doc], str]] = {
    "исполнитель": lambda d: d.contractor,
    "форма номера": lambda d: d.number,
    "результаты полей": lambda d: d.results,
    "страниц": lambda d: d.pages,
}


def make_doc(
    doc_id: str, values: dict[str, tuple[str, str | None]], pages: int, in_gold: bool
) -> Doc:
    """`values`: field → (result, normalized value) of feature 05."""
    def value(name: str) -> str | None:
        result, normalized = values.get(name, (NO_VALUE, None))
        return normalized if result == "found" else None

    return Doc(
        id=doc_id,
        contractor=name_key(value("contractor_name_short")),
        number=number_shape(value("contract_number")),
        results=results_key({f: r for f, (r, _) in values.items()}),
        pages=pages_bucket(pages),
        in_gold=in_gold,
    )


def groups(docs: Sequence[Doc], trait: Callable[[Doc], str]) -> list[list[Doc]]:
    """Contracts grouped by one trait, the largest group first, ties by the first id."""
    by_key: dict[str, list[Doc]] = defaultdict(list)
    for d in sorted(docs, key=lambda d: d.id):
        by_key[trait(d)].append(d)
    return sorted(by_key.values(), key=lambda g: (-len(g), g[0].id))


def pick(docs: Sequence[Doc], n: int) -> list[Doc]:
    """Up to `n` contracts outside the gold set, each bringing in the most new groups.

    A group is new when no gold contract and no earlier pick is in it. Ties go to the
    contract whose groups are smallest (rarer layouts first), then to the lower id. When
    nothing new is left, the remaining picks still prefer the smallest groups.
    """
    sizes = {name: {} for name in TRAITS}  # type: dict[str, dict[str, int]]
    for name, trait in TRAITS.items():
        for g in groups(docs, trait):
            sizes[name][trait(g[0])] = len(g)
    covered = {name: {trait(d) for d in docs if d.in_gold} for name, trait in TRAITS.items()}
    left = sorted((d for d in docs if not d.in_gold), key=lambda d: d.id)
    chosen: list[Doc] = []
    while left and len(chosen) < n:
        def score(d: Doc) -> tuple[int, int, str]:
            new = sum(trait(d) not in covered[name] for name, trait in TRAITS.items())
            rarity = sum(sizes[name][trait(d)] for name, trait in TRAITS.items())
            return (-new, rarity, d.id)

        best = min(left, key=score)
        chosen.append(best)
        left.remove(best)
        for name, trait in TRAITS.items():
            covered[name].add(trait(best))
    return chosen


def _ids(docs: Iterable[Doc], limit: int = 15) -> str:
    items = [d.id + ("*" if d.in_gold else "") for d in docs]
    more = f" … ещё {len(items) - limit}" if len(items) > limit else ""
    return " ".join(items[:limit]) + more


def summary_lines(docs: Sequence[Doc], n: int) -> list[str]:
    gold = [d for d in docs if d.in_gold]
    lines = [
        f"Договоров с полями: {len(docs)}; в эталоне: {len(gold)} (отмечены «*»)",
        "",
    ]
    for name, trait in TRAITS.items():
        found = groups(docs, trait)
        in_gold = sum(any(d.in_gold for d in g) for g in found)
        lines.append(f"{name}: групп {len(found)}, из них в эталоне {in_gold}")
        for number, g in enumerate(found, 1):
            mark = "" if any(d.in_gold for d in g) else "  ← нет в эталоне"
            lines.append(f"  группа {number}: {len(g)} — {_ids(g)}{mark}")
        lines.append("")
    chosen = pick(docs, n)
    lines.append(f"Предлагаю добавить в эталон ({len(chosen)}):")
    lines.append("  " + (" ".join(d.id for d in chosen) or "нечего добавить"))
    return lines


# --- database ------------------------------------------------------------------------------


def load_documents(conn: Any) -> list[Doc]:
    rows = conn.execute(
        "SELECT f.document_id, f.field, f.result, f.value_normalized, d.page_count"
        " FROM field_value f JOIN document d ON d.id = f.document_id"
    ).fetchall()
    gold = {r[0] for r in conn.execute("SELECT DISTINCT document_id FROM gold_field")}
    values: dict[str, dict[str, tuple[str, str | None]]] = defaultdict(dict)
    pages: dict[str, int] = {}
    for doc_id, field, result, normalized, page_count in rows:
        values[doc_id][field] = (result, normalized)
        pages[doc_id] = page_count
    return [make_doc(i, values[i], pages[i], i in gold) for i in sorted(values)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Разнообразие эталона (фича 09): только номера групп и id."
    )
    parser.add_argument("--pick", type=int, default=12, metavar="N",
                        help="сколько договоров предложить (по умолчанию 12)")
    args = parser.parse_args(argv)

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
        "Разнообразие эталона, фича 09 — только номера групп и id (версия 1)",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        "",
        *summary_lines(docs, args.pick),
    ]
    text = "\n".join(lines) + "\n"
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"survey-gold-diversity-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
