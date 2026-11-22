"""Quickstart Б1–Б3 of feature 04 (structure parsing) in one run, on the analyst's Mac.

Run from the repository root, after reading and recognition of the set are done:

    uv run python scripts/quickstart_structure.py            # uses .env
    uv run python scripts/quickstart_structure.py --env-file .env

What it does (specs/004-structure-parsing/quickstart.md, task T020):
  Б1  `docreader migrate`, then `docreader parse --all`, timed (SC-005: ≤ 1 min);
      counts of states and of reason kinds, the reason of every flagged document;
  Б3  the digest of all record ids, a second `parse --all`, the digest again (SC-004);
  Б2  picks 5 documents for the manual check (D-0056, two «готово», two «требует
      просмотра») and writes their outlines to `$DOCREADER_DATA_DIR/reports/structure-b2/`.
      The check itself is manual: compare each outline with its PDF.

Printed and saved (to `$DOCREADER_DATA_DIR/reports/structure-b-summary-….txt`): document
ids, numbers, clause and page numbers, reasons — the output of `parse`, which may be sent
to the agent. The outline files contain contract text: they are never printed and must
not be sent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

LONG_DOCUMENT = "D-0056"  # main text 5–20% by the survey (quickstart Б2)
REVIEW_FILE = "structure-b2"

# Reason kinds of research R-7, by the start of an item.
_KINDS: tuple[tuple[str, str], ...] = (
    ("нумерация не найдена", "нумерация не найдена"),
    ("раздел реквизитов не найден", "раздел реквизитов не найден"),
    ("после начала хвоста идёт раздел", "после начала хвоста идёт раздел"),
    ("пропуск:", "пропуск"),
    ("повтор:", "повтор"),
    ("номер вне порядка:", "номер вне порядка"),
    ("заголовок раздела", "заголовок раздела после его пункта"),
    ("нет заголовка раздела", "нет заголовка раздела"),
    ("не прочитана страница:", "непрочитанная страница"),
)


def docreader(env_file: str, *args: str) -> tuple[float, subprocess.CompletedProcess[str]]:
    """Run `docreader` through uv with the env file; seconds and the finished process."""
    command = ["uv", "run", "--env-file", env_file, "docreader", *args]
    started = time.monotonic()
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    return time.monotonic() - started, result


def read_env(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of an env file (comments and blank lines skipped)."""
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip().removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def reason_kinds(reason: str | None) -> list[str]:
    """Kinds of findings named in a `needs_review` reason (each kind once)."""
    if not reason:
        return []
    kinds: list[str] = []
    for part in reason.split("; "):
        for start, name in _KINDS:
            if part.startswith(start) and name not in kinds:
                kinds.append(name)
                break
        else:
            kinds.append("другое")
    return kinds


def summarize_parse(data: dict, seconds: float) -> list[str]:
    """Б1 lines from `parse --all --json`: time, totals, reason kinds, flagged documents."""
    docs = data.get("documents", [])
    totals = data.get("totals", {})
    states = Counter(d["state"] for d in docs)
    kinds = Counter(k for d in docs for k in reason_kinds(d.get("reason")))
    lines = [
        "Б1. Разбор набора (SC-005: не больше 60 с)",
        f"  время parse --all: {seconds:.1f} с"
        + ("" if seconds <= 60 else "  — БОЛЬШЕ МИНУТЫ"),
        f"  документов: {len(docs)}; готово {states.get('done', 0)}, "
        f"требует просмотра {states.get('needs_review', 0)}, ошибка {states.get('failed', 0)}, "
        f"пропущено {totals.get('skipped', len(data.get('skipped', [])))}",
        f"  с хвостом (реквизиты): {sum(1 for d in docs if d.get('has_tail'))} из {len(docs)}",
        f"  разделов {sum(d.get('sections', 0) for d in docs)}, "
        f"пунктов {sum(d.get('clauses', 0) for d in docs)}",
    ]
    if kinds:
        lines.append("  документов по видам причин:")
        lines += [f"    {name}: {count}" for name, count in kinds.most_common()]
    flagged = [d for d in docs if d["state"] in ("needs_review", "failed")]
    if flagged:
        lines.append("  помеченные документы:")
        lines += [f"    {d['document_id']}  {d['state']}  {d.get('reason') or ''}" for d in flagged]
    return lines


def ids_digest(ids: Iterable[str]) -> str:
    """SHA-256 of record ids, one per line, in the given order (quickstart Б3)."""
    return hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()


def same_results(first: dict, second: dict) -> bool:
    """The two `parse --all --json` runs give each document the same state and reason."""

    def by_doc(data: dict) -> dict[str, tuple[str, str | None]]:
        return {d["document_id"]: (d["state"], d.get("reason")) for d in data["documents"]}

    return by_doc(first) == by_doc(second)


def pick_review(docs: Sequence[dict]) -> list[str]:
    """Б2: D-0056 if parsed, then two «готово» and two «требует просмотра» by id."""
    ok = [d for d in docs if d["state"] in ("done", "needs_review")]
    chosen = [LONG_DOCUMENT] if any(d["document_id"] == LONG_DOCUMENT for d in ok) else []
    for state in ("done", "needs_review"):
        same = sorted(d["document_id"] for d in ok if d["state"] == state)
        chosen += [doc_id for doc_id in same if doc_id not in chosen][:2]
    return chosen


def review_template(chosen: Sequence[str], folder: Path) -> list[str]:
    lines = [
        "Б2. Ручная проверка границ (SC-002: не меньше 95% записей верны)",
        f"  оглавления записаны в {folder} — текст договоров, не присылать",
        "  сверить каждое с PDF и прислать только числа:",
        "    документ | записей проверено | неверный номер | неверная граница | хвост с раздела N",
    ]
    lines += [f"    {doc_id} |   |   |   |" for doc_id in chosen]
    if LONG_DOCUMENT in chosen:
        lines.append(
            f"  для {LONG_DOCUMENT}: совпал ли заголовок реквизитов с концом договора (да/нет)"
        )
    return lines


def _record_ids(env_file: str, doc_ids: Sequence[str]) -> list[str]:
    ids: list[str] = []
    for doc_id in doc_ids:
        _, result = docreader(env_file, "outline", doc_id, "--json")
        if result.returncode == 0:
            ids += [r["id"] for r in json.loads(result.stdout)["records"]]
    return ids


def _parse_all(env_file: str) -> tuple[float, dict]:
    seconds, result = docreader(env_file, "parse", "--all", "--json")
    if result.returncode != 0:
        sys.exit(f"docreader parse --all: код {result.returncode}\n{result.stderr.strip()}")
    return seconds, json.loads(result.stdout)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args(argv)
    env_file = args.env_file
    data_dir = read_env(Path(env_file)).get("DOCREADER_DATA_DIR")
    if not data_dir:
        sys.exit(f"В {env_file} нет DOCREADER_DATA_DIR")
    reports = Path(data_dir).expanduser() / "reports"

    _, migrated = docreader(env_file, "migrate")
    if migrated.returncode != 0:
        sys.exit(f"docreader migrate: код {migrated.returncode}\n{migrated.stderr.strip()}")

    seconds, first = _parse_all(env_file)
    lines = summarize_parse(first, seconds)
    parsed = [d["document_id"] for d in first["documents"] if d["state"] != "failed"]

    before = ids_digest(_record_ids(env_file, parsed))
    _, second = _parse_all(env_file)
    after = ids_digest(_record_ids(env_file, parsed))
    lines += [
        "",
        "Б3. Повторный разбор (SC-004: отпечатки совпадают)",
        f"  до:    {before}",
        f"  после: {after}",
        "  совпали" if before == after else "  НЕ СОВПАЛИ",
    ]
    if same_results(first, second):
        lines.append("  состояния и причины второго разбора те же")
    else:
        lines.append("  ВНИМАНИЕ: состояния или причины второго разбора другие")

    folder = reports / REVIEW_FILE
    folder.mkdir(parents=True, exist_ok=True)
    chosen = pick_review(first["documents"])
    for doc_id in chosen:
        _, result = docreader(env_file, "outline", doc_id)
        (folder / f"outline-{doc_id}.txt").write_text(result.stdout, encoding="utf-8")
    lines += ["", *review_template(chosen, folder)]

    text = "\n".join(lines) + "\n"
    print(text, end="")
    summary = reports / f"structure-b-summary-{datetime.now():%Y%m%d-%H%M%S}.txt"
    summary.write_text(text, encoding="utf-8")
    print(f"\nСводка сохранена: {summary} (её можно прислать агенту)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
