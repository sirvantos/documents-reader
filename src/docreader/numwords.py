"""Russian cardinal numbers in words, for the amount-in-words rule of feature 06.

`words_to_int` reads a number spelled in words; `words_of_amount` finds the bracketed words
that spell an amount next to its figures (specs/010-rule-checks/research.md, R-3).
"""

from __future__ import annotations

import re

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
    """The bracketed words that spell the amount: inside the value text, or right after it.

    Digits may follow the rouble or kopeck word («… тысяч руб. 00 коп.»), never precede it.
    """
    for m in (_BRACKETS.search(value_text), _BRACKETS_NEXT.search(after)):
        if m is None or not _WORD.search(m.group(1)):
            continue
        number_part = _CURRENCY.split(m.group(1), maxsplit=1)[0]
        if not re.search(r"\d", number_part):
            return m.group(1)
    return None


_CURRENCY = re.compile(r"(?i)\b(?:руб|коп)")
