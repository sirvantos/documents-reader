"""`--pages` parsing for `docreader recognize`."""

import pytest

from docreader.cli import parse_page_range
from docreader.errors import UserError


@pytest.mark.parametrize(("text", "expected"), [("3", [3]), ("2-3", [2, 3]), ("4-4", [4])])
def test_valid(text: str, expected: list[int]) -> None:
    assert parse_page_range(text) == expected


@pytest.mark.parametrize("text", ["", "a", "0", "3-1", "1-", "-2", "1-2-3", "0-2", "1.5"])
def test_invalid(text: str) -> None:
    with pytest.raises(UserError, match=r"^--pages "):
        parse_page_range(text)
