"""Extraction of the six prototype fields by rules, without a model (feature 02, R-8).

A second, independent source for the review page: where it agrees with feature 05 the
card is «совпало», where it differs the card goes first. Every candidate becomes an
answer of the same shape as the model's and passes `verify.check_field` — the same
program check of the quote and the value (principle III): a rule cannot propose a value
without a verbatim quote. Pure functions over the clean text and its parse records; no
database, no model.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from docreader import values, verify
from docreader.fields import PROTOTYPE_FIELDS, Result, spec
from docreader.verify import FieldResult, TextIndex

RULES_VERSION = "02.3"

_WS = r"\s+"
# «ДОГОВОР ПОДРЯДА № ДП-17/2026», «ДОГОВОР\n№ Р-11/2026»; «протокол № …», «доверенность № …»
# are not taken: the word «договор» must stand before the sign.
_NUMBER = re.compile(r"\bДОГОВОР\b[^\n№]{0,120}?\s*№\s*(?P<num>[^\s,;]+)", re.IGNORECASE)
_PARTY = r"(?P<role>Заказчик|Подрядчик)"
# «(ООО «Альфа»), именуемое в дальнейшем «Заказчик»» / «… (далее — «Подрядчик»)»
_NAME_IN_BRACKETS = re.compile(
    r"\((?P<name>[^()\n]{2,80}?)\)\s*,?\s*(?:именуем\w*\s+в\s+дальнейшем|\(?далее\s*[—–-])"
    r"\s*[«\"]?" + _PARTY,
)
# «и ООО «Бета», именуемое в дальнейшем Подрядчик»
_NAME_PLAIN = re.compile(
    r"(?P<name>\b[А-ЯЁ]{2,4}\s*«[^»\n]{1,60}»)\s*,?\s*"
    r"(?:именуем\w*\s+в\s+дальнейшем|\(?далее\s*[—–-])\s*[«\"]?" + _PARTY,
)
# «Открытое акционерное общество «Гамма», именуемое в дальнейшем «Заказчик»»: the legal
# form spelled out, no short name in brackets (analyst's measurement, record 24)
_NAME_SPELLED = re.compile(
    r"(?<![А-ЯЁа-яё])(?P<name>(?:"
    + "|".join(r"\s+".join(form.split()) for form in values.SPELLED_FORMS)
    + r")\s*«[^»\n]{1,60}»)\s*,?\s*(?:именуем\w*\s+в\s+дальнейшем|\(?далее\s*[—–-])"
    r"\s*[«\"]?" + _PARTY,
    re.IGNORECASE,
)
_PRICE_SECTION = re.compile(r"цен", re.IGNORECASE)
_WITHOUT_VAT = re.compile(r"^\W*без\s+(?:учёта\s+|учета\s+)?НДС", re.IGNORECASE)
_WITH_VAT_AFTER = re.compile(r"^\W*(?:с\s+учётом|с\s+учетом|включая)\s+НДС", re.IGNORECASE)
# the rate may stand between «НДС» and the amount, in brackets or not: «с НДС (20%) — …»;
# a scan may read that dash as «_» (record 26)
_RATE = r"(?:\s*\(?\s*\d+(?:[.,]\d+)?\s*%\s*\)?)"
_WITH_VAT_BEFORE = re.compile(
    r"(?:с\s+учётом|с\s+учетом|включая|\bс)\s+НДС" + _RATE + r"?[\W_]{0,3}$", re.IGNORECASE
)
# the VAT amount itself: «НДС 20% — …», «на НДС (20%) — …», not «с НДС (20%) — …»
_VAT_AMOUNT_BEFORE = re.compile(
    r"(?<!\bс\s)(?<!учётом\s)(?<!учетом\s)(?<!включая\s)НДС" + _RATE + r"\s*[—–_-]?\s*$",
    re.IGNORECASE,
)
_TERM = re.compile(r"срок\s+действия", re.IGNORECASE)
_VALID_UNTIL = re.compile(r"действует\s+(?:до|по)\s+$", re.IGNORECASE)
_CONTEXT = 60


@dataclass
class _Answer:
    """One candidate in the form of the model's answer (verify.FieldAnswerLike)."""

    found: bool
    value: str | None
    quote: str | None
    clause: str | None


def _sentence(text: str, start: int, end: int, lo: int, hi: int) -> tuple[int, int]:
    """The sentence of `text[lo:hi]` around `[start, end)`."""
    left = max(text.rfind(". ", lo, start), text.rfind(";", lo, start))
    s = left + 1 if left >= lo else lo
    right = [i for i in (text.find(". ", end, hi), text.find(";", end, hi)) if i != -1]
    e = min(right) + 1 if right else hi
    while s < e and text[s].isspace():
        s += 1
    while e > s and text[e - 1].isspace():
        e -= 1
    return s, e


def _own_text(index: TextIndex, clause: verify.ClauseRange) -> tuple[int, int]:
    return clause.start, min(clause.end, index.shown_end)


def _number(index: TextIndex) -> list[_Answer]:
    out = []
    for clause in index.clauses:
        if clause.kind != "preamble":
            continue
        lo, hi = _own_text(index, clause)
        for m in _NUMBER.finditer(index.text, lo, hi):
            num = m["num"].rstrip(".")
            if not num:
                continue
            quote = index.text[m.start() : m.start("num") + len(num)]
            out.append(_Answer(True, num, quote, clause.key))
            break  # the title comes first; later «договор №» are references
    return out


def _names(index: TextIndex) -> dict[str, list[_Answer]]:
    found: dict[str, list[_Answer]] = {"customer_name_short": [], "contractor_name_short": []}
    for clause in index.clauses:
        if clause.kind != "preamble":
            continue
        lo, hi = _own_text(index, clause)
        for pattern in (_NAME_IN_BRACKETS, _NAME_PLAIN, _NAME_SPELLED):
            for m in pattern.finditer(index.text, lo, hi):
                field = (
                    "customer_name_short" if m["role"] == "Заказчик" else "contractor_name_short"
                )
                name = m["name"].strip()
                quote = index.text[m.start("name") : m.end("role")]
                found[field].append(_Answer(True, name, quote, clause.key))
    return found


def _amounts(index: TextIndex, sections: Mapping[str, str | None]) -> dict[str, list[_Answer]]:
    found: dict[str, list[_Answer]] = {"amount_without_vat": [], "amount_with_vat": []}
    for clause in index.clauses:
        if clause.kind not in ("clause", "section"):
            continue
        title = sections.get(clause.key) or ""
        if not _PRICE_SECTION.search(title):
            continue
        lo, hi = _own_text(index, clause)
        own = index.text[lo:hi]
        amounts = values.amounts_in(own)
        for i, (_, (a, b)) in enumerate(amounts):
            prev_end = amounts[i - 1][1][1] if i else 0
            next_start = amounts[i + 1][1][0] if i + 1 < len(amounts) else len(own)
            before = own[max(prev_end, a - _CONTEXT) : a]
            after = own[b : min(next_start, b + _CONTEXT)]
            if _VAT_AMOUNT_BEFORE.search(before):
                continue
            if _WITHOUT_VAT.search(after):
                field = "amount_without_vat"
            elif _WITH_VAT_AFTER.search(after) or _WITH_VAT_BEFORE.search(before):
                field = "amount_with_vat"
            else:
                continue
            s, e = _sentence(index.text, lo + a, lo + b, lo, hi)
            found[field].append(
                _Answer(True, own[a:b], index.text[s:e], clause.key)
            )
    return found


def _end_date(index: TextIndex, sections: Mapping[str, str | None]) -> list[_Answer]:
    out = []
    for clause in index.clauses:
        if clause.kind not in ("clause", "section"):
            continue
        lo, hi = _own_text(index, clause)
        own = index.text[lo:hi]
        if not (_TERM.search(own) or _TERM.search(sections.get(clause.key) or "")):
            continue
        for _, (a, b) in values.dates_in(own):
            if not _VALID_UNTIL.search(re.sub(_WS, " ", own[max(0, a - _CONTEXT) : a])):
                continue
            s, e = _sentence(index.text, lo + a, lo + b, lo, hi)
            out.append(_Answer(True, own[a:b], index.text[s:e], clause.key))
    return out


def extract_rules(
    index: TextIndex, sections: Mapping[str, str | None]
) -> dict[str, list[FieldResult]]:
    """Every value the rules find for the six prototype fields, each confirmed by
    `verify.check_field`; distinct normalized values only. `sections` maps a clause key
    to the title of its section (`clause.section_title`)."""
    candidates: dict[str, list[_Answer]] = {
        "contract_number": _number(index),
        **_names(index),
        **_amounts(index, sections),
        "contract_end_date": _end_date(index, sections),
    }
    result: dict[str, list[FieldResult]] = {}
    for field in PROTOTYPE_FIELDS:
        kept: list[FieldResult] = []
        seen: set[str] = set()
        for answer in candidates.get(field.name, []):
            checked = verify.check_field(spec(field.name), answer, index)
            if checked.result is not Result.FOUND or checked.value_normalized is None:
                continue
            key = checked.value_normalized.casefold()
            if key not in seen:
                seen.add(key)
                kept.append(checked)
        result[field.name] = kept
    return result
