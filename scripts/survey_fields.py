"""Where and how are the six prototype fields written? Numbers only, for the Mac (feature 05).

Run from the repository root after parsing (`docreader parse`); no model runs:

    uv run --env-file .env python scripts/survey_fields.py

It reads the cleaned text and the parse records (feature 04) of every parsed document
(stage `structure` in `done` or `needs_review`) and counts, to answer the open questions
of `specs/005-field-extraction/spec.md` before clarify:

1. Size: characters of the preamble, the main text, the requisites section (the tail up
   to the first «Приложение» line) and the appendices; a rough token estimate. Decides
   what the model is shown when the whole text does not fit one request.
2. Parties: the roles «Заказчик»/«Подрядчик» named in the preamble, short names in
   brackets («(ОАО «РЖД»)»), and how many such brackets the preamble has.
3. Contract number: a «Договор № …» line at the start of the preamble — filled, blank
   («№ ____») or missing.
4. Price: sections whose heading names the price; mentions «без НДС» / «с НДС» there,
   sums with «руб» there and in the whole main text.
5. Term: sentences about the term of the contract — an end date in words, in digits,
   «до полного исполнения», or none.

Only counts, shares, ranges and document ids are printed and saved (to
`$DOCREADER_DATA_DIR/reports/survey-fields-….txt`): no text, no names, no numbers from
documents. The summary may be sent to the agent.
"""

from __future__ import annotations

import argparse
import re
import statistics
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

APPENDIX_LINE = re.compile(r"(?m)^\s*приложение(?:\s|$)", re.IGNORECASE)
ROLE = re.compile(r"\b(Заказчик|Подрядчик)")
SHORT_NAME = re.compile(
    r"\(\s*(?:ОАО|ООО|АО|ПАО|ЗАО|НАО|ФГУП|ГУП|МУП|ИП)\s*[«\"“][^»\"”]{1,60}[»\"”]\s*\)"
)
NUMBER_LINE = re.compile(r"(?im)^\s*договор\b[^\n]{0,80}?№\s*(?P<rest>[^\n]{0,40})")
PRICE_HEADING = re.compile(r"цен|стоимост|порядок\s+расч", re.IGNORECASE)
WITHOUT_VAT = re.compile(r"без\s+(?:уч[её]та\s+)?НДС|НДС\s+не\s+облага", re.IGNORECASE)
WITH_VAT = re.compile(r"(?:с\s+уч[её]том|включая|в\s+том\s+числе)\s+НДС|с\s+НДС", re.IGNORECASE)
SUM_RUB = re.compile(r"\d{1,3}(?:[  ]\d{3})+(?:[.,]\d{2})?\s*(?:\([^)\n]{0,200}\)\s*)?руб",
                     re.IGNORECASE)
TERM_SENTENCE = re.compile(
    r"[^.;\n]*(?:действует|срок\s+действия|вступает\s+в\s+силу)[^;]*?(?:\.\s|;|$)",
    re.IGNORECASE,
)
MONTHS = "января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря"
DATE_WORDS = re.compile(
    rf"(?:по|до)\s+[«\"]?\d{{1,2}}[»\"]?\s+(?:{MONTHS})\s+\d{{4}}", re.IGNORECASE
)
DATE_DIGITS = re.compile(r"(?:по|до)\s+\d{1,2}\.\d{1,2}\.\d{2,4}", re.IGNORECASE)
UNTIL_FULFILMENT = re.compile(r"до\s+(?:полного|надлежащего)\s+исполнения", re.IGNORECASE)
END_DATE_FORMS = frozenset({"дата словом", "дата цифрами"})


# --- pure helpers (tested in tests/unit/test_survey_fields.py) --------------------------------


@dataclass(frozen=True)
class Record:
    kind: str  # preamble, section, clause, tail
    start: int
    end: int
    title: str | None = None  # section heading


@dataclass
class DocFields:
    doc_id: str
    total: int = 0
    preamble: int = 0
    main: int = 0
    requisites: int = 0
    appendices: int = 0
    roles: frozenset[str] = frozenset()
    short_names: int = 0
    number: str = "нет"  # заполнен, пустой, нет
    price_sections: int = 0
    without_vat: int = 0
    with_vat: int = 0
    price_sums: int = 0
    main_sums: int = 0
    term: set[str] = field(default_factory=set)


def part_sizes(text: str, records: Sequence[Record]) -> tuple[int, int, int, int]:
    """Characters of the preamble, the main text, the requisites section, the appendices."""
    preamble = sum(r.end - r.start for r in records if r.kind == "preamble")
    main = sum(r.end - r.start for r in records if r.kind in ("section", "clause"))
    tail = next((r for r in records if r.kind == "tail"), None)
    if tail is None:
        return preamble, main, 0, 0
    tail_text = text[tail.start : tail.end]
    m = APPENDIX_LINE.search(tail_text)
    requisites = m.start() if m else len(tail_text)
    return preamble, main, requisites, len(tail_text) - requisites


def number_form(preamble: str) -> str:
    """«Договор № …» at the start: `заполнен`, `пустой` (no digit after «№») or `нет`."""
    m = NUMBER_LINE.search(preamble[:1500])
    if m is None:
        return "нет"
    return "заполнен" if re.match(r"[^\s_]*\d", m.group("rest").strip()) else "пустой"


def term_forms(main: str) -> set[str]:
    """Forms of the contract end date in sentences about the term of the contract."""
    forms: set[str] = set()
    for m in TERM_SENTENCE.finditer(main):
        sentence = m.group(0)
        if not re.search(r"договор", sentence, re.IGNORECASE):
            continue
        if DATE_WORDS.search(sentence):
            forms.add("дата словом")
        if DATE_DIGITS.search(sentence):
            forms.add("дата цифрами")
        if UNTIL_FULFILMENT.search(sentence):
            forms.add("до исполнения обязательств")
    return forms


def survey_document(doc_id: str, text: str, records: Sequence[Record]) -> DocFields:
    d = DocFields(doc_id, total=len(text))
    d.preamble, d.main, d.requisites, d.appendices = part_sizes(text, records)
    preamble = "".join(text[r.start : r.end] for r in records if r.kind == "preamble")
    main_records = [r for r in records if r.kind in ("section", "clause")]
    main = "".join(text[r.start : r.end] for r in main_records)
    d.roles = frozenset(m.group(1) for m in ROLE.finditer(preamble))
    d.short_names = len(SHORT_NAME.findall(preamble))
    d.number = number_form(preamble)
    # a price section: its own record and every record after it up to the next section
    in_price = False
    price_parts: list[str] = []
    for r in main_records:
        if r.kind == "section":
            in_price = bool(r.title and PRICE_HEADING.search(r.title))
            d.price_sections += in_price
        if in_price:
            price_parts.append(text[r.start : r.end])
    price = "".join(price_parts)
    d.without_vat = len(WITHOUT_VAT.findall(price))
    d.with_vat = len(WITH_VAT.findall(price))
    d.price_sums = len(SUM_RUB.findall(price))
    d.main_sums = len(SUM_RUB.findall(main))
    d.term = term_forms(main) or {"нет"}
    return d


# --- summary ------------------------------------------------------------------------------------


_SIZES = (0, 20_000, 50_000, 100_000, 200_000, 400_000)


def size_buckets(values: Iterable[int]) -> str:
    """`0–20 тыс.: 3, 20–50 тыс.: 10` — documents per size range (characters)."""
    counts: Counter[int] = Counter()
    for v in values:
        counts[max(i for i, low in enumerate(_SIZES) if v >= low)] += 1
    parts = []
    for i, low in enumerate(_SIZES):
        if counts[i]:
            high = _SIZES[i + 1] if i + 1 < len(_SIZES) else None
            name = f"{low // 1000}–{high // 1000} тыс." if high else f"≥ {low // 1000} тыс."
            parts.append(f"{name}: {counts[i]}")
    return ", ".join(parts) if parts else "—"


def value_counts(values: Iterable[int], cap: int) -> str:
    """`0: 2, 1: 40, 2 и больше: 3` — documents per value, values ≥ cap together."""
    counts = Counter(min(v, cap) for v in values)
    return ", ".join(
        f"{k if k < cap else f'{cap} и больше'}: {counts[k]}" for k in sorted(counts)
    ) or "—"


def _range(values: Sequence[int]) -> str:
    if not values:
        return "—"
    return f"мин {min(values)}, медиана {int(statistics.median(values))}, макс {max(values)}"


def _ids(docs: Iterable[DocFields], limit: int = 12) -> str:
    ids = [d.doc_id for d in docs]
    more = f" и ещё {len(ids) - limit}" if len(ids) > limit else ""
    return (", ".join(ids[:limit]) + more) if ids else "—"


def summary_lines(docs: Sequence[DocFields]) -> list[str]:
    n = len(docs)
    whole = [d.total for d in docs]
    no_appendix = [d.preamble + d.main + d.requisites for d in docs]
    longest = sorted(docs, key=lambda d: -d.total)
    forms = Counter(f for d in docs for f in d.term)
    return [
        f"Документов: {n}",
        "",
        "1. Размер текста, знаков (токенов примерно втрое меньше — грубая оценка)",
        f"  весь текст: {_range(whole)}",
        f"    по размеру: {size_buckets(whole)}",
        f"  без приложений (преамбула + основной текст + реквизиты): {_range(no_appendix)}",
        f"    по размеру: {size_buckets(no_appendix)}",
        f"  преамбула: {_range([d.preamble for d in docs])}",
        f"  основной текст: {_range([d.main for d in docs])}",
        f"  раздел реквизитов: {_range([d.requisites for d in docs])}",
        f"  приложения: {_range([d.appendices for d in docs])}",
        f"  самые длинные (весь текст): {_ids(longest, 5)}",
        "",
        "2. Стороны в преамбуле",
        f"  названы обе роли (Заказчик и Подрядчик): "
        f"{sum(1 for d in docs if len(d.roles) == 2)} из {n}",
        f"  одна роль или ни одной: {_ids(d for d in docs if len(d.roles) < 2)}",
        "  краткие наименования в скобках «(ООО «…»)»: "
        + value_counts((d.short_names for d in docs), 3),
        "",
        "3. Номер договора в начале преамбулы («Договор № …»)",
        "  " + (", ".join(f"{k}: {v}" for k, v in Counter(d.number for d in docs).most_common())
                or "—"),
        f"  пустой или нет: {_ids(d for d in docs if d.number != 'заполнен')}",
        "",
        "4. Цена",
        f"  разделов о цене по заголовку: {value_counts((d.price_sections for d in docs), 2)}",
        f"  без раздела о цене: {_ids(d for d in docs if d.price_sections == 0)}",
        f"  упоминаний «без НДС» в разделе о цене: {_range([d.without_vat for d in docs])}",
        f"  упоминаний «с НДС» в разделе о цене: {_range([d.with_vat for d in docs])}",
        f"  раздел о цене без «с НДС»: "
        f"{_ids(d for d in docs if d.price_sections and not d.with_vat)}",
        f"  сумм в рублях в разделе о цене: {_range([d.price_sums for d in docs])}",
        f"  сумм в рублях во всём основном тексте: {_range([d.main_sums for d in docs])}",
        "",
        "5. Срок действия договора (фразы «действует», «срок действия», «вступает в силу»)",
        *(f"  {name}: {count}" for name, count in forms.most_common()),
        f"  без даты окончания: {_ids(d for d in docs if not d.term & END_DATE_FORMS)}",
    ]


def load_documents(conn: Any) -> list[DocFields]:
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
            Record(kind, start, end, title)
            for kind, start, end, title in conn.execute(
                "SELECT kind, start, end_, title FROM clause WHERE document_id = %s"
                " ORDER BY ordinal",
                (doc_id,),
            ).fetchall()
        ]
        docs.append(survey_document(doc_id, text, records))
    return docs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Обзор полей прототипа (фича 05): только цифры.")
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
        "Обзор полей прототипа, фича 05 — только цифры (версия 1)",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        "",
        *summary_lines(docs),
    ]
    text = "\n".join(lines) + "\n"
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"survey-fields-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
