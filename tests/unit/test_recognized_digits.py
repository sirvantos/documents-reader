"""OCR confusions fixed in recognised line text (analyst's measurement, record 21).

`textnorm.fix_recognized(text) -> str`: a lone «|» that stands for the digit «1» —
touching a digit, or right before a three-digit group — becomes «1». A line with more
than one «|» is left as is: there the bars are most likely table rules.
"""

from __future__ import annotations

import pytest

from docreader.textnorm import fix_recognized


@pytest.mark.parametrize(
    ("raw", "fixed"),
    [
        (
            "Цена работ составляет — | 047 208 (Один миллион",
            "Цена работ составляет — 1 047 208 (Один миллион",
        ),
        ("в размере |2 000 рублей", "в размере 12 000 рублей"),
        ("всего 4|5 рублей", "всего 415 рублей"),
    ],
)
def test_a_lone_bar_by_digits_is_the_digit_one(raw: str, fixed: str) -> None:
    assert fix_recognized(raw) == fixed


@pytest.mark.parametrize(
    "raw",
    [
        "| Наименование | 100 000 |",  # table rules
        "Сторона | Подрядчик",  # not by digits
        "код | 12 34",  # a two-digit group is not a thousands group
        "текст без черты 1 025",
    ],
)
def test_other_bars_stay(raw: str) -> None:
    assert fix_recognized(raw) == raw
