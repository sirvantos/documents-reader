"""Normalizing field values and finding a value inside its quote (feature 05, R-6, R-7).

Pure functions; the language model takes no part (FR-004, FR-005). Kinds follow the
field catalog («Виды значений»):

- amount — a number with two decimals: digit groups separated by single spaces, kopecks
  after a comma or point or as «NN коп…» after the word «руб…»; inside a quote only a
  number followed (after an optional parenthesised spelling) by «руб…» is an amount;
- date — `YYYY-MM-DD` from «25 марта 2026 г.», «"25" марта 2026», `25.03.2026`,
  `2026-03-25`;
- identifier — without «№»/«N»/«Nº»/«N°» and outer spaces, in the comparison form of `textnorm`
  (dashes, quotes, Latin look-alikes inside Cyrillic words), inner spaces kept;
- name — the comparison form (quotes `"`, «ё» → «е», spaces), case kept; inside a quote
  the words must follow one another and match by dictionary forms (`pymorphy3`).

Matching runs on `textnorm.compare_form` of the quote, so line breaks, «ё», dashes and
quote marks do not matter, and spans are mapped back to the quote as written.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from functools import cache
from typing import TYPE_CHECKING, Any

from docreader import wordforms
from docreader.fields import Kind
from docreader.textnorm import compare_form

if TYPE_CHECKING:
    from docreader.catalog import CatalogField

_KIND_WORD = {
    Kind.AMOUNT: "сумме",
    Kind.DATE: "дате",
    Kind.IDENTIFIER: "номеру",
    Kind.NAME: "наименованию",
}


class ValueNotNormalized(ValueError):
    """The value cannot be brought to its kind; the reason names the kind."""

    def __init__(self, kind: Kind) -> None:
        super().__init__(f"значение не приводится к {_KIND_WORD[kind]}")
        self.kind = kind


def _folded(text: str) -> tuple[str, list[int]]:
    return compare_form(unicodedata.normalize("NFC", text))


def _span(offsets: list[int], start: int, end: int) -> tuple[int, int]:
    """`[start, end)` in the folded text → the same range in the original text."""
    return offsets[start], offsets[end - 1] + 1


# --- amounts -----------------------------------------------------------------------------

_INTEGER = r"(?P<int>\d{1,3}(?: \d{3})+|\d+)"
_FRACTION = r"(?:[.,](?P<frac>\d{2}))?"
_SPELLED = r"(?: ?\([^)]{0,400}\))?"
_KOPECKS = r"(?: ?(?P<kop>\d{2}) ?коп\w*)?"
# In a quote: a number, its spelling, the word «руб…» and the kopecks (the span ends
# before a trailing point of an abbreviation).
_AMOUNT_IN_TEXT = re.compile(
    rf"(?<![\d.,]){_INTEGER}{_FRACTION} ?{_SPELLED} ?руб\w*(?:\.(?= ?\d{{2}} ?коп))?{_KOPECKS}",
    re.IGNORECASE,
)
_PLAIN_NUMBER = re.compile(rf"{_INTEGER}{_FRACTION}")


def _amount(match: re.Match[str]) -> Decimal | None:
    frac, kop = match.groupdict().get("frac"), match.groupdict().get("kop")
    if frac and kop:
        return None  # «12,50 рублей 50 копеек» — two kopeck parts
    cents = frac or kop or "00"
    return Decimal(f"{match['int'].replace(' ', '')}.{cents}")


def _normalize_amount(value: str) -> str:
    folded, _ = _folded(value)
    plain = _PLAIN_NUMBER.fullmatch(folded)
    match = plain or _AMOUNT_IN_TEXT.fullmatch(folded.rstrip("."))
    amount = _amount(match) if match else None
    if amount is None:
        raise ValueNotNormalized(Kind.AMOUNT)
    return f"{amount:.2f}"


def _amounts_in(quote: str) -> list[tuple[str, tuple[int, int]]]:
    folded, offsets = _folded(quote)
    found = []
    for match in _AMOUNT_IN_TEXT.finditer(folded):
        amount = _amount(match)
        if amount is not None:
            found.append((f"{amount:.2f}", _span(offsets, match.start(), match.end())))
    return found


# --- dates -------------------------------------------------------------------------------

_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
    "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}
_WORD_DATE = re.compile(
    r'(?<!\d)(?:" ?)?(?P<day>\d{1,2})(?: ?")? '
    r"(?P<month>" + "|".join(_MONTHS) + r") (?P<year>\d{4})(?!\d)",
    re.IGNORECASE,
)
_DOT_DATE = re.compile(r"(?<![\d.])(?P<day>\d{2})\.(?P<month>\d{2})\.(?P<year>\d{4})(?![\d])")
_ISO_DATE = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})")


def _date(match: re.Match[str]) -> str | None:
    month: Any = match["month"]
    number = _MONTHS[month.lower()] if not month.isdigit() else int(month)
    try:
        return date(int(match["year"]), number, int(match["day"])).isoformat()
    except ValueError:
        return None


def _dates_in(quote: str) -> list[tuple[str, tuple[int, int]]]:
    folded, offsets = _folded(quote)
    found = []
    for pattern in (_WORD_DATE, _DOT_DATE):
        for match in pattern.finditer(folded):
            value = _date(match)
            if value is not None:
                found.append((value, _span(offsets, match.start(), match.end())))
    return sorted(found, key=lambda item: item[1])


def _normalize_date(value: str) -> str:
    folded, _ = _folded(value)
    iso = _ISO_DATE.fullmatch(folded.strip())
    candidates = [_date(iso)] if iso else [v for v, _ in _dates_in(value)]
    if len(candidates) != 1 or candidates[0] is None:
        raise ValueNotNormalized(Kind.DATE)
    return candidates[0]


# --- identifiers -------------------------------------------------------------------------

_NUMBER_SIGN = re.compile(r"^(?:№|N[º°]|N(?= )) ?")
_ID_CHARS = re.compile(r"[\w\-/.]")


def _normalize_identifier(value: str) -> str:
    folded, _ = _folded(value)
    result = _NUMBER_SIGN.sub("", folded).strip()
    if not result:
        raise ValueNotNormalized(Kind.IDENTIFIER)
    return result


_LETTER_WORD = re.compile(r"[^\W\d_]+(?:-[^\W\d_]+)*")


def contract_number_core(normalized: str) -> str:
    """The contract number without letter codes after a space (analyst's rule, 2026-11-26).

    Trailing space-separated words of letters and hyphens only are not part of the
    number; a word with a digit stays, and the first word always stays.
    """
    words = normalized.split(" ")
    while len(words) > 1 and _LETTER_WORD.fullmatch(words[-1]):
        words.pop()
    return " ".join(words)


def _find_identifier(normalized: str, quote: str) -> tuple[int, int] | None:
    folded, offsets = _folded(quote)
    start = folded.find(normalized)
    while start != -1:
        end = start + len(normalized)
        before = folded[start - 1] if start > 0 else ""
        after = folded[end] if end < len(folded) else ""
        if not (before and _ID_CHARS.match(before)) and not (after and _ID_CHARS.match(after)):
            return _span(offsets, start, end)
        start = folded.find(normalized, start + 1)
    return None


# --- names -------------------------------------------------------------------------------

_WORD = re.compile(r"[^\W_]+")
_CYRILLIC = re.compile(r"[а-яё]", re.IGNORECASE)
_QUOTE_MARKS = '"\''


def _normalize_name(value: str) -> str:
    folded, _ = _folded(value)
    result = folded.strip()
    if not _WORD.search(result):
        raise ValueNotNormalized(Kind.NAME)
    return result


# Legal forms written out in full, as they open a full name, and their abbreviations
# (lower case keys; longer forms first so that «открытое акционерное общество» wins).
_SPELLED_FORMS: dict[str, str] = {
    "открытое акционерное общество": "ОАО",
    "закрытое акционерное общество": "ЗАО",
    "публичное акционерное общество": "ПАО",
    "непубличное акционерное общество": "НАО",
    "акционерное общество": "АО",
    "общество с ограниченной ответственностью": "ООО",
    "общество с дополнительной ответственностью": "ОДО",
    "федеральное государственное унитарное предприятие": "ФГУП",
    "государственное унитарное предприятие": "ГУП",
    "муниципальное унитарное предприятие": "МУП",
}
_SPACES_IN_QUOTES = re.compile(r'"\s*([^"]*?)\s*"')
# Abbreviated legal forms that open a short name.
_SHORT_FORMS = (
    "ОАО", "ЗАО", "ПАО", "НАО", "АО", "ООО", "ОДО", "ФГУП", "ГУП", "МУП",
)
_BRACKETS_AFTER = re.compile(r"\s*\(([^()]{1,300})\)")
_SHORT_IN_BRACKETS = re.compile(
    r"(?<![^\W_])(?:" + "|".join(_SHORT_FORMS) + r")\s+[\"'«„“]"
)


def _spelled_form(normalized: str) -> str | None:
    lower = " ".join(normalized.lower().split())
    return next((form for form in _SPELLED_FORMS if lower.startswith(form + " ")), None)


def spelled_legal_form(normalized: str) -> bool:
    """Whether a normalized name opens with a legal form written out in full."""
    return _spelled_form(normalized) is not None


def canonical_short_name(normalized: str) -> str:
    """A normalized short name with its legal form abbreviated, spaces inside quotes dropped.

    «акционерное общество "Бета"» → `АО "Бета"` (analyst, 2026-11-26): the form is the same
    either way, the name in quotes stays as written. Only a form that opens the name.
    """
    text = " ".join(normalized.split())
    form = _spelled_form(text)
    if form is not None:
        text = _SPELLED_FORMS[form] + text[len(form):]
    return _SPACES_IN_QUOTES.sub(r'"\1"', text)


def short_name_after(text: str, end: int) -> tuple[int, int] | None:
    """`[start, end)` in `text` of a short name in brackets right after position `end`.

    «… «Альфа» (ООО «Альфа»)», «… (далее — ООО «Альфа»)»: the brackets follow the full
    name with only spaces between, and hold an abbreviated legal form and a name in quotes.
    """
    brackets = _BRACKETS_AFTER.match(text, end)
    if brackets is None:
        return None
    inside = brackets.group(1)
    form = _SHORT_IN_BRACKETS.search(inside)
    if form is None:
        return None
    start = brackets.start(1) + form.start()
    return start, brackets.start(1) + len(inside.rstrip())


def _analyzer() -> Any:
    return wordforms.analyzer()  # one analyzer per process, shared with the word index


@cache
def _forms(word: str) -> frozenset[str]:
    """The dictionary forms of `word` (lower case); the word itself for non-Russian words."""
    lower = word.lower()
    if not _CYRILLIC.search(lower):
        return frozenset({lower})
    return frozenset({lower} | {p.normal_form for p in _analyzer().parse(lower)})


def _find_name(normalized: str, quote: str) -> tuple[int, int] | None:
    wanted = [m.group() for m in _WORD.finditer(normalized)]
    folded, offsets = _folded(quote)
    words = list(_WORD.finditer(folded))
    for i in range(len(words) - len(wanted) + 1):
        window = words[i : i + len(wanted)]
        if all(_forms(w.group()) & _forms(v) for w, v in zip(window, wanted, strict=True)):
            start, end = window[0].start(), window[-1].end()
            # keep the quote marks around the last word: «ООО «Альфа»» as written
            if normalized[:1] in _QUOTE_MARKS and start > 0 and folded[start - 1] in _QUOTE_MARKS:
                start -= 1
            closing = folded[end : end + 1]
            if normalized[-1:] in _QUOTE_MARKS and closing and closing in _QUOTE_MARKS:
                end += 1
            return _span(offsets, start, end)
    return None


# --- the two entry points ------------------------------------------------------------------


def normalize(kind: Kind, value: str) -> str:
    """The normalized value of `kind`, or ValueNotNormalized."""
    if kind is Kind.AMOUNT:
        return _normalize_amount(value)
    if kind is Kind.DATE:
        return _normalize_date(value)
    if kind is Kind.IDENTIFIER:
        return _normalize_identifier(value)
    return _normalize_name(value)


def find_in_quote(kind: Kind, normalized: str, quote: str) -> tuple[int, int] | None:
    """`[start, end)` in `quote` of the value whose normalized form is `normalized`."""
    if kind is Kind.AMOUNT:
        return next((span for value, span in _amounts_in(quote) if value == normalized), None)
    if kind is Kind.DATE:
        return next((span for value, span in _dates_in(quote) if value == normalized), None)
    if kind is Kind.IDENTIFIER:
        return _find_identifier(normalized, quote)
    return _find_name(normalized, quote)


# --- every kind of the field catalog (feature 02, research R-4) -----------------------------

_REQUISITE_WORDS = (
    ("_inn", "ИНН"),
    ("_kpp", "КПП"),
    ("_ogrn", "ОГРН"),
    ("_bik", "БИК"),
    ("account", "счёту"),
)
_REQUISITE_LABEL = re.compile(r"^[A-Za-zА-Яа-яЁё :/]+")
_PERCENT = re.compile(r"(?P<num>\d+(?:[.,]\d+)?) ?%?(?: ?\([^)]*\))?")
_WHOLE_NUMBER = re.compile(r"(?P<num>\d+)(?: ?\([^)]*\))?(?: +[^\W\d_]+)*")


def _requisite_word(name: str) -> str:
    for marker, word in _REQUISITE_WORDS:
        if name.endswith(marker) or (marker == "account" and "account" in name):
            return word
    return "реквизиту"


def _normalize_requisite(field: CatalogField, value: str) -> str:
    text = _REQUISITE_LABEL.sub("", value.strip(), count=1).replace(" ", "")
    length = field.requisite_length
    if length is None or not re.fullmatch(rf"\d{{{length}}}", text):
        raise ValueError(f"значение не приводится к {_requisite_word(field.name)} ({length} цифр)")
    return text


def _normalize_percent(value: str) -> str:
    match = _PERCENT.fullmatch(value.strip())
    if match is None:
        raise ValueError("значение не приводится к проценту")
    return format(Decimal(match["num"].replace(",", ".")).normalize(), "f")


def _normalize_number(value: str) -> str:
    match = _WHOLE_NUMBER.fullmatch(value.strip())
    if match is None:
        raise ValueError("значение не приводится к целому числу")
    return str(int(match["num"]))


def _choice_key(text: str) -> str:
    return text.strip().casefold().replace("ё", "е")


def _normalize_choice(field: CatalogField, value: str) -> str:
    wanted = _choice_key(value)
    for variant in field.choices:
        if _choice_key(variant) == wanted:
            return variant
    raise ValueError("значение не из вариантов: " + ", ".join(field.choices))


def normalize_field(field: CatalogField, value: str) -> str:
    """The normalized value of a catalog field of any kind; ValueError when it does not fit."""
    kind = field.kind.value
    if kind in {k.value for k in Kind}:
        return normalize(Kind(kind), value)
    if kind == "requisite":
        return _normalize_requisite(field, value)
    if kind == "percent":
        return _normalize_percent(value)
    if kind == "number":
        return _normalize_number(value)
    if kind == "choice":
        return _normalize_choice(field, value)
    return value.strip()  # free_text, list, records: assessed by hand


def same_value(field: CatalogField, a: str, b: str) -> bool:
    """Whether two normalized values are the same: names ignore case, the rest are equal."""
    if field.kind.value == Kind.NAME.value:
        if field.name.endswith("_name_short"):
            a, b = canonical_short_name(a), canonical_short_name(b)
        return a.casefold() == b.casefold()
    return a == b


# --- values inside a text (feature 02, rules extraction) -------------------------------------


def amounts_in(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Every amount («… руб…») in `text`: normalized value and `[start, end)` in `text`."""
    return _amounts_in(text)


def dates_in(text: str) -> list[tuple[str, tuple[int, int]]]:
    """Every date in `text`: `YYYY-MM-DD` and `[start, end)` in `text`, in text order."""
    return _dates_in(text)
