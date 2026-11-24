"""How long are the passages the minimal feature 07 would cut? Numbers only, for the Mac.

Run from the repository root after parsing (`docreader parse`); no model runs:

    uv run --env-file .env python scripts/survey_passages.py

It reads the cleaned text and the parse records (feature 04) of every parsed document
(stage `structure` in `done` or `needs_review`) and counts, to answer the open questions
of `specs/006-passages-and-indexes/spec.md` before clarify:

1. Passages: records by kind; one passage per record with own text besides a section's
   heading line (sections with only the heading give none); records without a section;
   very short passages.
2. Length of the own text per passage kind (preamble, section, clause, subclause, tail).
3. Over the search model's limit: passages whose label and text together exceed 512,
   2048 and 8192 tokens (512 — FRIDA, 8192 — BGE-M3), by a conservative estimate of one
   token per three characters (no tokenizer, no model); their share of passages and of
   passage text, documents that have them.
4. Tail: the requisites section (up to the first «Приложение» line, as shown to the
   model in feature 05) and the appendices after it; appendix lines; the tail's share
   of the document text.

Only counts, shares, ranges and document ids are printed and saved (to
`$DOCREADER_DATA_DIR/reports/survey-passages-….txt`): no text, no titles, no names,
no numbers from documents. The summary may be sent to the agent.
"""

from __future__ import annotations

import argparse
import math
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from docreader.extraction_text import APPENDIX_LINE  # one rule for survey and work

VERSION = 1
CHARS_PER_TOKEN = 3  # conservative for Russian text: real tokenizers give fewer tokens
LIMITS = (512, 2048, 8192)
SHORT_CHARS = 30
KINDS = ("preamble", "section", "clause", "subclause", "tail")
KIND_NAMES = {
    "preamble": "преамбула",
    "section": "раздел с текстом",
    "clause": "пункт",
    "subclause": "подпункт",
    "tail": "хвост",
}


# --- pure helpers (tested in tests/unit/test_survey_passages.py) -----------------------------


@dataclass(frozen=True)
class Record:
    kind: str  # preamble, section, clause, tail (feature 04)
    depth: int  # 0 preamble and tail, 1 section, 2 clause, 3+ subclause
    start: int
    end: int
    section_number: int | None = None
    section_title: str | None = None


@dataclass(frozen=True)
class Passage:
    kind: str  # one of KINDS
    chars: int  # own text, stripped
    label_chars: int


@dataclass
class DocPassages:
    doc_id: str
    total: int = 0
    records: int = 0
    heading_only_sections: int = 0
    sections_with_body: int = 0
    no_section: int = 0
    short: int = 0
    tail_requisites: int = 0
    tail_appendices: int = 0
    appendix_lines: int = 0
    passages: list[Passage] = field(default_factory=list)


def own_body(own_text: str, kind: str) -> str:
    """The text a passage would hold: a section loses its heading line."""
    if kind == "section":
        _, _, rest = own_text.partition("\n")
        return rest.strip()
    return own_text.strip()


def tokens_estimate(chars: int) -> int:
    return math.ceil(chars / CHARS_PER_TOKEN)


def passage_kind(record: Record) -> str:
    if record.kind == "clause":
        return "clause" if record.depth <= 2 else "subclause"
    return record.kind


def label_length(doc_id: str, record: Record) -> int:
    """Length of a label «D-0001 · раздел 5 «…» · пункт 5.2» without building its text."""
    sep = len(" · ")
    if record.kind in ("preamble", "tail"):
        return len(doc_id) + sep + len("реквизиты")
    section = 0
    if record.section_number is not None:
        title = record.section_title or ""
        section = sep + len(f"раздел {record.section_number} «»") + len(title)
    number = 2 * max(record.depth, 1)  # «5.2.1» — about two characters per level
    return len(doc_id) + section + sep + len("пункт ") + number


def survey_document(doc_id: str, text: str, records: Sequence[Record]) -> DocPassages:
    d = DocPassages(doc_id, total=len(text), records=len(records))
    for r in records:
        body = own_body(text[r.start : r.end], r.kind)
        if r.kind == "section":
            if body:
                d.sections_with_body += 1
            else:
                d.heading_only_sections += 1
        if r.kind == "tail":
            tail = text[r.start : r.end]
            lines = list(APPENDIX_LINE.finditer(tail))
            d.tail_requisites = lines[0].start() if lines else len(tail)
            d.tail_appendices = len(tail) - d.tail_requisites
            d.appendix_lines = len(lines)
        if not body:
            continue
        if r.kind in ("section", "clause") and r.section_number is None:
            d.no_section += 1
        if len(body) < SHORT_CHARS:
            d.short += 1
        d.passages.append(Passage(passage_kind(r), len(body), label_length(doc_id, r)))
    return d


def _over(p: Passage, limit: int) -> bool:
    return tokens_estimate(p.chars + p.label_chars) > limit


def over_limit(docs: Sequence[DocPassages], limit: int) -> tuple[int, float, float, list[str]]:
    """Passages over `limit` estimated tokens (label and text): count, share of passages,
    share of passage text, ids of documents that have them."""
    passages = [p for d in docs for p in d.passages]
    over = [p for p in passages if _over(p, limit)]
    total_chars = sum(p.chars for p in passages)
    ids = [d.doc_id for d in docs if any(_over(p, limit) for p in d.passages)]
    return (
        len(over),
        len(over) / len(passages) if passages else 0.0,
        sum(p.chars for p in over) / total_chars if total_chars else 0.0,
        ids,
    )


def _percent(share: float) -> str:
    return f"{share * 100:.1f}%"


def _quantile(values: Sequence[int], q: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _spread(values: Sequence[int]) -> str:
    if not values:
        return "—"
    return (
        f"мин {min(values)}, медиана {int(statistics.median(values))}, "
        f"90% {_quantile(values, 0.9)}, 99% {_quantile(values, 0.99)}, макс {max(values)}"
    )


def _ids(ids: Iterable[str], limit: int = 12) -> str:
    items = list(ids)
    more = f" и ещё {len(items) - limit}" if len(items) > limit else ""
    return (", ".join(items[:limit]) + more) if items else "—"


def _kinds(counts: Counter[str]) -> str:
    return ", ".join(f"{KIND_NAMES[k]}: {counts[k]}" for k in KINDS if counts[k]) or "—"


def summary_lines(docs: Sequence[DocPassages]) -> list[str]:
    n = len(docs)
    lines = [f"Документов: {n}"]
    if not docs:
        return lines
    passages = [p for d in docs for p in d.passages]
    lines += [
        "",
        "1. Отрывки (одна запись разбора с собственным текстом — один отрывок)",
        f"  записей разбора: {sum(d.records for d in docs)}",
        f"  отрывков: {len(passages)}; на документ: {_spread([len(d.passages) for d in docs])}",
        "  по видам: " + _kinds(Counter(p.kind for p in passages)),
        f"  разделов только с заголовком (без отрывка): "
        f"{sum(d.heading_only_sections for d in docs)}",
        f"  разделов с текстом после заголовка: {sum(d.sections_with_body for d in docs)}",
        f"  отрывков основного текста без распознанного раздела: "
        f"{sum(d.no_section for d in docs)}",
        f"  очень коротких (меньше {SHORT_CHARS} знаков): {sum(d.short for d in docs)}",
        "",
        "2. Длина собственного текста отрывка, знаков",
        *(
            f"  {KIND_NAMES[k]}: {_spread([p.chars for p in passages if p.kind == k])}"
            for k in KINDS
        ),
        f"  метка (оценка): {_spread([p.label_chars for p in passages])}",
        "",
        f"3. Длиннее предела модели (метка и текст; оценка: 1 токен на {CHARS_PER_TOKEN} знака,"
        " с запасом)",
    ]
    for limit in LIMITS:
        count, share, text_share, ids = over_limit(docs, limit)
        lines.append(
            f"  > {limit} токенов: отрывков {count} ({_percent(share)} отрывков, "
            f"{_percent(text_share)} текста отрывков), документов {len(ids)}: {_ids(ids)}"
        )
        if count:
            over_kinds = Counter(p.kind for p in passages if _over(p, limit))
            lines.append("    по видам: " + _kinds(over_kinds))
    with_tail = [d for d in docs if d.tail_requisites or d.tail_appendices]
    tails = [d.tail_requisites + d.tail_appendices for d in with_tail]
    shares = [round(100 * t / d.total) for t, d in zip(tails, with_tail, strict=True) if d.total]
    lines += [
        "",
        "4. Хвост (раздел реквизитов и приложения)",
        f"  документов с хвостом: {len(with_tail)} из {n}",
        f"  хвост целиком, знаков: {_spread(tails)}",
        f"  раздел реквизитов (до первой строки «Приложение»): "
        f"{_spread([d.tail_requisites for d in with_tail])}",
        f"  приложения: {_spread([d.tail_appendices for d in with_tail])}",
        f"  документов с приложениями в хвосте: "
        f"{sum(1 for d in with_tail if d.tail_appendices)} из {len(with_tail)}",
        f"  строк «Приложение» в хвосте: {_spread([d.appendix_lines for d in with_tail])}",
        f"  доля хвоста в тексте документа, %: {_spread(shares)}",
        *(
            f"  реквизиты без приложений > {limit} токенов: документов "
            f"{sum(1 for d in with_tail if tokens_estimate(d.tail_requisites) > limit)}"
            for limit in LIMITS
        ),
    ]
    return lines


def load_documents(conn: Any) -> list[DocPassages]:
    """Survey every parsed document."""
    doc_ids = [
        row[0]
        for row in conn.execute(
            "SELECT document_id FROM stage_status WHERE stage = 'structure'"
            " AND state IN ('done', 'needs_review') ORDER BY document_id"
        ).fetchall()
    ]
    docs = []
    for doc_id in doc_ids:
        (text,) = conn.execute(
            "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
        ).fetchone()
        records = [
            Record(kind, depth, start, end, section_number, section_title)
            for kind, depth, start, end, section_number, section_title in conn.execute(
                "SELECT kind, depth, start, end_, section_number, section_title FROM clause"
                " WHERE document_id = %s ORDER BY ordinal",
                (doc_id,),
            ).fetchall()
        ]
        docs.append(survey_document(doc_id, text, records))
    return docs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обзор отрывков (фича 07): только цифры.")
    parser.parse_args(argv)

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
        f"Обзор отрывков, фича 07 — только цифры (версия {VERSION})",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        "",
        *summary_lines(docs),
    ]
    text = "\n".join(lines) + "\n"
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"survey-passages-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
