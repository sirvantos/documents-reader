"""Clause identifiers D-0001/5.2 (research R-5, task T005)."""

from __future__ import annotations

import pytest

from docreader.errors import UserError
from docreader.ids import clause_key, format_clause_id, parse_clause_id


@pytest.mark.parametrize(
    ("number", "key"), [((5,), "5"), ((5, 2), "5.2"), ((12, 3, 1, 10), "12.3.1.10")]
)
def test_clause_key_from_number(number: tuple[int, ...], key: str) -> None:
    assert clause_key(number) == key


def test_clause_key_rejects_empty_number() -> None:
    with pytest.raises(ValueError):
        clause_key(())


def test_format_clause_id() -> None:
    assert format_clause_id("D-0001", "5.2") == "D-0001/5.2"
    assert format_clause_id("D-0012", "преамбула") == "D-0012/преамбула"


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("D-0001/5", (1, "5")),
        ("D-0001/5.2", (1, "5.2")),
        ("  d-0012/5.2.1.10 ", (12, "5.2.1.10")),
        ("D-0003/преамбула", (3, "преамбула")),
        ("D-0003/реквизиты", (3, "реквизиты")),
    ],
)
def test_parse_clause_id(text: str, parsed: tuple[int, str]) -> None:
    assert parse_clause_id(text) == parsed


@pytest.mark.parametrize(
    "text",
    [
        "D-0001",  # no key
        "D-0001/",
        "D-0001/5.",  # printed form, not a key
        "D-0001/05",  # leading zero
        "D-0001/5..2",
        "D-0001/1234",  # four digits
        "D-0001/П1/2",  # appendices are the next iteration
        "D-0001/хвост",
        "X-0001/5",
        "D-0000/5",
        "5.2",
    ],
)
def test_parse_clause_id_rejects(text: str) -> None:
    with pytest.raises(UserError, match=r"ожидается вид D-0001/5\.2"):
        parse_clause_id(text)
