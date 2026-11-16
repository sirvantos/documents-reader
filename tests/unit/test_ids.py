import pytest

from docreader.errors import UserError
from docreader.ids import format_document_id, parse_document_id


@pytest.mark.parametrize(
    ("seq", "expected"),
    [(1, "D-0001"), (42, "D-0042"), (9999, "D-9999"), (10000, "D-10000")],
)
def test_format_document_id(seq, expected):
    assert format_document_id(seq) == expected


@pytest.mark.parametrize("seq", [0, -1])
def test_format_document_id_rejects_non_positive(seq):
    with pytest.raises(ValueError):
        format_document_id(seq)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("D-0001", 1), ("d-0001", 1), ("D-1", 1), ("d-1", 1), (" D-0012 ", 12), ("D-10000", 10000)],
)
def test_parse_document_id_accepts(text, expected):
    assert parse_document_id(text) == expected


@pytest.mark.parametrize("text", ["D-", "D-0", "D-0000", "X-1", "D-1a", "", "D--1", "D-+1", "1"])
def test_parse_document_id_rejects(text):
    with pytest.raises(UserError):
        parse_document_id(text)
