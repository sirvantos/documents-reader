"""How the six prototype fields are written, for the rules of feature 06. Counts only.

Run from the repository root after extraction (`docreader extract`); no model runs:

    uv run --env-file .env python scripts/survey_rule_checks.py

It reads the feature 05 values, the clean text and the page lines of every contract with
fields and counts, never printing a value, a quote, a name or a file name:

1. Results of extraction per field (found / not_found / rejected / failed).
2. Amounts in words: is there a number in words in brackets with the amount, does it parse,
   does it equal the rubles of the amount, does it also spell the kopecks.
3. VAT: which rates are written in the quotes of the two amounts, whether the amount with
   VAT equals the amount without VAT increased by that rate (or 20% when none is written),
   exactly, within a kopeck, within a rouble, or not at all; «не облагается» in the text.
4. End date: by year bucket and relative to today.
5. Short names of the two parties: equal or not.
6. Contract number in page headers/footers and on the signature sheet («Номер договора»):
   present, equal to the extracted number, equal in its main part only, or different.

Unlike `survey_fields.py` (feature 05, where the fields stand in the text before
extraction), this survey checks the extracted values against the candidate rules.
The summary is saved to `$DOCREADER_DATA_DIR/reports/survey-rule-checks-….txt` and may be
sent to the agent.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

VERSION = 1
FIELDS = (
    "contract_number", "customer_name_short", "contractor_name_short",
    "amount_without_vat", "amount_with_vat", "contract_end_date",
)
AMOUNTS = ("amount_without_vat", "amount_with_vat")
DEFAULT_RATE = Decimal(20)

# --- Russian cardinal numbers in words ---------------------------------------------------

_UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "одно": 1, "два": 2, "две": 2, "три": 3, "четыре": 4,
    "пять": 5, "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14,
    "пятнадцать": 15, "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18,
    "девятнадцать": 19, "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50,
    "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80, "девяносто": 90, "сто": 100,
    "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500, "шестьсот": 600,
    "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}
_SCALES = (("миллиард", 10**9), ("миллион", 10**6), ("тысяч", 10**3))
_IGNORED = re.compile(r"^и$")
_KOPECKS = re.compile(r"коп", re.IGNORECASE)
_WORD = re.compile(r"[а-яё]+", re.IGNORECASE)


def words_to_int(text: str) -> int | None:
    """«Четыре миллиона семьсот две тысячи» → 4702000; None when a word is not a number.

    Reading stops at the rouble or kopeck word: a number after it spells the kopecks.
    """
    total = group = 0
    seen = False
    for raw in _WORD.findall(text.lower().replace("ё", "е")):
        if raw.startswith(("коп", "руб")):
            break
        if raw in _UNITS:
            group += _UNITS[raw]
            seen = True
            continue
        scale = next((v for stem, v in _SCALES if raw.startswith(stem)), None)
        if scale is not None:
            total += (group or 1) * scale
            group = 0
            seen = True
            continue
        if _IGNORED.match(raw):
            continue
        return None
    return total + group if seen else None


_BRACKETS = re.compile(r"\(([^()]{3,300})\)")
_BRACKETS_NEXT = re.compile(r"^\W{0,3}?\(([^()]{3,300})\)")


def words_of_amount(value_text: str, after: str) -> str | None:
    """The bracketed words that spell the amount: inside the value text, or right after it."""
    for m in (_BRACKETS.search(value_text), _BRACKETS_NEXT.search(after)):
        if m and _WORD.search(m.group(1)) and not re.search(r"\d", m.group(1)):
            return m.group(1)
    return None


def amount_words_class(value_text: str, after: str, normalized: str) -> tuple[str, bool]:
    """(class, spells kopecks): no_words / unparsed / equal / differs."""
    words = words_of_amount(value_text, after)
    if words is None:
        return "no_words", False
    number = words_to_int(words)
    kopecks = bool(_KOPECKS.search(words))
    if number is None:
        return "unparsed", kopecks
    try:
        roubles = int(Decimal(normalized))
    except (InvalidOperation, ValueError):
        return "unparsed", kopecks
    return ("equal" if number == roubles else "differs"), kopecks


# --- VAT --------------------------------------------------------------------------------

_RATE = re.compile(r"НДС\W{0,3}(\d{1,2}(?:[.,]\d+)?)\s*%", re.IGNORECASE)
_EXEMPT = re.compile(r"не\s+облага", re.IGNORECASE)


def rates_in(text: str) -> list[Decimal]:
    return [Decimal(m.group(1).replace(",", ".")) for m in _RATE.finditer(text)]


def vat_class(without: Decimal, with_vat: Decimal, rate: Decimal) -> str:
    """exact / kopeck / rouble / other: how close `with_vat` is to `without` × (1 + rate)."""
    expected = (without * (1 + rate / 100)).quantize(Decimal("0.01"))
    gap = abs(expected - with_vat)
    if gap == 0:
        return "exact"
    if gap <= Decimal("0.01"):
        return "kopeck"
    if gap <= Decimal("1.00"):
        return "rouble"
    return "other"


def ratio_bucket(without: Decimal, with_vat: Decimal) -> str:
    if without <= 0:
        return "нет"
    ratio = with_vat / without
    for label, target in (("1.20", Decimal("1.2")), ("1.18", Decimal("1.18")),
                          ("1.10", Decimal("1.1")), ("1.00", Decimal(1))):
        if abs(ratio - target) < Decimal("0.0005"):
            return label
    return "другое"


# --- dates and numbers ----------------------------------------------------------------------


def year_bucket(value: str) -> str:
    try:
        year = int(value[:4])
    except ValueError:
        return "не читается"
    if year < 2015:
        return "до 2015"
    if year <= 2022:
        return "2015–2022"
    if year <= 2030:
        return str(year)
    if year <= 2040:
        return "2031–2040"
    return "после 2040"


def relative_bucket(value: str, today: date) -> str:
    try:
        end = date.fromisoformat(value)
    except ValueError:
        return "не читается"
    years = (end - today).days / 365.25
    if years < -5:
        return "раньше чем 5 лет назад"
    if years < 0:
        return "в прошлом, до 5 лет"
    if years <= 5:
        return "в будущем, до 5 лет"
    if years <= 15:
        return "в будущем, 5–15 лет"
    return "в будущем, больше 15 лет"


_NUMBER_LINE = re.compile(r"№|договор", re.IGNORECASE)
_SIGN_SHEET = re.compile(r"номер\s+договора", re.IGNORECASE)


def _compact(text: str) -> str:
    from docreader.textnorm import compare_form

    return compare_form(text)[0].replace(" ", "").casefold()


def number_match(lines: Iterable[str], number: str) -> str:
    """none / full / core / differs: the extracted number among these lines."""
    candidates = [line for line in lines if _NUMBER_LINE.search(line)]
    if not candidates:
        return "none"
    full = _compact(number)
    parts = number.split()
    core = _compact(parts[0]) if parts else full
    texts = [_compact(line) for line in candidates]
    if any(full in t for t in texts):
        return "full"
    if core and any(core in t for t in texts):
        return "core"
    return "differs"


# --- collecting ------------------------------------------------------------------------------


def _counters(names: Sequence[str]) -> dict[str, Counter[str]]:
    return {n: Counter() for n in names}


@dataclass
class Survey:
    results: dict[str, Counter[str]] = field(default_factory=lambda: _counters(FIELDS))
    words: dict[str, Counter[str]] = field(default_factory=lambda: _counters(AMOUNTS))
    kopecks_in_words: Counter[str] = field(default_factory=Counter)
    rates: Counter[str] = field(default_factory=Counter)
    vat: Counter[str] = field(default_factory=Counter)
    ratio: Counter[str] = field(default_factory=Counter)
    exempt: int = 0
    one_amount: int = 0
    end_year: Counter[str] = field(default_factory=Counter)
    end_relative: Counter[str] = field(default_factory=Counter)
    names: Counter[str] = field(default_factory=Counter)
    furniture: Counter[str] = field(default_factory=Counter)
    signature: Counter[str] = field(default_factory=Counter)
    documents: int = 0


@dataclass(frozen=True)
class Doc:
    """One contract: its field rows, clean text and page lines split by role."""

    fields: dict[str, dict[str, Any]]
    text: str
    furniture_lines: list[str]
    body_lines: list[str]


def add(survey: Survey, doc: Doc, today: date) -> None:
    from docreader import catalog, values

    survey.documents += 1
    found: dict[str, dict[str, Any]] = {}
    for name in FIELDS:
        row = doc.fields.get(name)
        result = row["result"] if row else "нет строки"
        survey.results[name][result] += 1
        if row and result == "found":
            found[name] = row
    for name in AMOUNTS:
        row = found.get(name)
        if row is None:
            continue
        end = row.get("value_end")
        after = doc.text[end : end + 320] if isinstance(end, int) else ""
        cls, kopecks = amount_words_class(row["value_text"], after, row["value_normalized"])
        survey.words[name][cls] += 1
        if kopecks:
            survey.kopecks_in_words[name] += 1
    if _EXEMPT.search(doc.text):
        survey.exempt += 1
    if all(n in found for n in AMOUNTS):
        quotes = " ".join(found[n]["quote"] or "" for n in AMOUNTS)
        stated = rates_in(quotes)
        label = (", ".join(sorted({f"{r}%" for r in stated})) if stated
                 else "ставка не написана")
        survey.rates[label] += 1
        rate = stated[0] if stated else DEFAULT_RATE
        without = Decimal(found["amount_without_vat"]["value_normalized"])
        with_vat = Decimal(found["amount_with_vat"]["value_normalized"])
        survey.vat[vat_class(without, with_vat, rate)] += 1
        survey.ratio[ratio_bucket(without, with_vat)] += 1
    elif any(n in found for n in AMOUNTS):
        survey.one_amount += 1
    if "contract_end_date" in found:
        value = found["contract_end_date"]["value_normalized"]
        survey.end_year[year_bucket(value)] += 1
        survey.end_relative[relative_bucket(value, today)] += 1
    if "customer_name_short" in found and "contractor_name_short" in found:
        same = values.same_value(
            catalog.field("customer_name_short"),
            found["customer_name_short"]["value_normalized"],
            found["contractor_name_short"]["value_normalized"],
        )
        survey.names["одинаковые" if same else "разные"] += 1
    if "contract_number" in found:
        number = found["contract_number"]["value_text"]
        survey.furniture[number_match(doc.furniture_lines, number)] += 1
        sheet = [line for line in doc.body_lines if _SIGN_SHEET.search(line)]
        survey.signature[number_match(sheet, number) if sheet else "none"] += 1


# --- report ----------------------------------------------------------------------------------

_LABELS = {
    "no_words": "прописи нет", "unparsed": "пропись не читается", "equal": "равна рублям",
    "differs": "не равна", "exact": "точно", "kopeck": "расходится на копейку",
    "rouble": "расходится до рубля", "other": "не согласуется", "none": "номера нет",
    "full": "совпадает целиком", "core": "совпадает основная часть",
}


def _counts(counter: Counter[str]) -> str:
    total = sum(counter.values())
    if not total:
        return "—"
    parts = [
        f"{_LABELS.get(key, key)} {n} ({100 * n / total:.0f}%)"
        for key, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return ", ".join(parts)


def summary_lines(survey: Survey) -> list[str]:
    lines = [f"Договоров с полями: {survey.documents}", "", "1. Результаты извлечения:"]
    for name in FIELDS:
        lines.append(f"  {name}: {_counts(survey.results[name])}")
    lines += ["", "2. Сумма прописью (у найденных сумм):"]
    for name in AMOUNTS:
        lines.append(f"  {name}: {_counts(survey.words[name])}; "
                     f"с копейками прописью {survey.kopecks_in_words[name]}")
    lines += [
        "", "3. НДС (договоры с обеими суммами):",
        f"  ставка в цитатах: {_counts(survey.rates)}",
        f"  сумма с НДС = без НДС × (1 + ставка): {_counts(survey.vat)}",
        f"  отношение сумм: {_counts(survey.ratio)}",
        f"  найдена одна сумма из двух: {survey.one_amount}; "
        f"«не облагается» в тексте: {survey.exempt}",
        "", "4. Дата окончания:",
        f"  по годам: {_counts(survey.end_year)}",
        f"  от сегодня: {_counts(survey.end_relative)}",
        "", f"5. Краткие наименования сторон: {_counts(survey.names)}",
        "", "6. Номер договора:",
        f"  в колонтитулах: {_counts(survey.furniture)}",
        f"  на листе подписи («Номер договора»): {_counts(survey.signature)}",
    ]
    return lines


def survey_documents(docs: Sequence[Doc], today: date) -> Survey:
    survey = Survey()
    for doc in docs:
        add(survey, doc, today)
    return survey


# --- database --------------------------------------------------------------------------------


def _value_end(text: str, row: dict[str, Any]) -> int | None:
    """Where the value text ends in the clean text, searched inside its quote."""
    start, end, value = row.get("quote_start"), row.get("quote_end"), row.get("value_text")
    if not isinstance(start, int) or not isinstance(end, int) or not value:
        return None
    from docreader.textnorm import locate

    spans = locate(text[start:end], value)
    return start + spans[0][1] if spans else None


def load_documents(conn: Any) -> list[Doc]:
    rows = conn.execute(
        "SELECT document_id, field, result, value_text, value_normalized, quote,"
        " quote_start, quote_end FROM field_value ORDER BY document_id, field"
    ).fetchall()
    by_doc: dict[str, dict[str, dict[str, Any]]] = {}
    for doc_id, name, result, value_text, normalized, quote, q_start, q_end in rows:
        by_doc.setdefault(doc_id, {})[name] = {
            "result": result, "value_text": value_text, "value_normalized": normalized,
            "quote": quote, "quote_start": q_start, "quote_end": q_end,
        }
    docs = []
    for doc_id in sorted(by_doc):
        text_row = conn.execute(
            "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
        ).fetchone()
        text = text_row[0] if text_row else ""
        furniture: list[str] = []
        body: list[str] = []
        for (lines,) in conn.execute(
            "SELECT lines FROM page_text WHERE document_id = %s ORDER BY page_number", (doc_id,)
        ).fetchall():
            for line in lines:
                target = furniture if line.get("role") in ("header", "footer") else body
                target.append(str(line.get("text", "")))
        fields = by_doc[doc_id]
        for row in fields.values():
            row["value_end"] = _value_end(text, row)
        docs.append(Doc(fields, text, furniture, body))
    return docs


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    argparse.ArgumentParser(
        description="Как записаны шесть полей (фича 06): только числа и доли."
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
        f"Опрос для правил фичи 06 — только числа и доли (версия {VERSION})",
        f"Дата: {datetime.now().isoformat(timespec='minutes')}",
        "",
        *summary_lines(survey_documents(docs, date.today())),
    ]
    text = "\n".join(lines) + "\n"
    reports = settings.data_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    target = reports / f"survey-rule-checks-{datetime.now():%Y%m%d-%H%M%S}.txt"
    target.write_text(text, encoding="utf-8")
    print("\n" + text + f"\nСохранено: {target}\nЭтот текст можно отправить агенту.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
