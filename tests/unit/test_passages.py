"""The cutting rule, the label and the coverage check (feature 07, research R-3, R-4; T009).

Pure functions on a text and a list of parse records; no database, no model. Critical
part (plan.md «Критические части»), written by the main session; the implementer must
not edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

import pytest

from docreader.passages import ClauseRecord, PassageSpan, coverage, cut, label

# A hand-built document: own texts of the records follow one another and cover the text.
PARTS = [
    # (key, kind, depth, section_number, section_title, own text)
    ("преамбула", "preamble", 0, None, None, "ДОГОВОР ПОДРЯДА\nООО «Альфа» и ООО «Бета»:\n"),
    ("1", "section", 1, 1, "Предмет договора", "1. Предмет договора\n"),
    ("1.1", "clause", 2, 1, "Предмет договора", "1.1. Подрядчик выполняет работы.\n"),
    ("1.1.1", "clause", 3, 1, "Предмет договора", "1.1.1. В два этапа.\n"),
    ("2", "section", 1, 2, "Цена", "2. Цена\nЦена определяется сметой.\n\n"),
    ("2.1", "clause", 2, 2, "Цена", "  2.1. Не применяется.  \n"),
    ("5", "section", 1, 5, "", "5.\n"),
    ("5.1", "clause", 2, 5, "", "5.1. Пункт раздела без заголовка.\n"),
    ("7.3", "clause", 2, None, None, "7.3. Пункт без раздела.\n"),
    ("7.4", "clause", 2, None, None, "   \n"),
    ("реквизиты", "tail", 0, None, None,
     "8. Реквизиты сторон\nИНН 0000000000\nПриложение № 1\nСмета\n"),
]


def build() -> tuple[str, list[ClauseRecord], int]:
    text, records = "", []
    for key, kind, depth, number, title, own in PARTS:
        records.append(ClauseRecord(key, kind, depth, len(text), len(text) + len(own),
                                    number, title))
        text += own
    tail_end = text.index("Приложение № 1")
    return text, records, tail_end


def spans_by_key(text: str, spans: list[PassageSpan]) -> dict[str, str]:
    return {s.key: text[s.start:s.end] for s in spans}


# --- cut ---------------------------------------------------------------------------------


def test_one_passage_per_record_with_own_text() -> None:
    text, records, tail_end = build()
    got = spans_by_key(text, cut(text, records, tail_end))
    assert got == {
        "преамбула": "ДОГОВОР ПОДРЯДА\nООО «Альфа» и ООО «Бета»:",
        "1.1": "1.1. Подрядчик выполняет работы.",
        "1.1.1": "1.1.1. В два этапа.",
        "2": "Цена определяется сметой.",
        "2.1": "2.1. Не применяется.",
        "5.1": "5.1. Пункт раздела без заголовка.",
        "7.3": "7.3. Пункт без раздела.",
        "реквизиты": "8. Реквизиты сторон\nИНН 0000000000",
    }


def test_heading_only_section_gives_no_passage() -> None:
    text, records, tail_end = build()
    keys = [s.key for s in cut(text, records, tail_end)]
    assert "1" not in keys and "5" not in keys


def test_section_passage_starts_after_the_heading_line() -> None:
    text, records, tail_end = build()
    (span,) = [s for s in cut(text, records, tail_end) if s.key == "2"]
    assert text[span.start:span.end] == "Цена определяется сметой."
    assert span.start > records[4].start


def test_tail_stops_at_tail_end_or_runs_to_its_end() -> None:
    text, records, tail_end = build()
    (span,) = [s for s in cut(text, records, tail_end) if s.key == "реквизиты"]
    assert "Приложение" not in text[span.start:span.end]
    (whole,) = [s for s in cut(text, records, len(text)) if s.key == "реквизиты"]
    assert text[whole.start:whole.end].endswith("Смета")


def test_tail_with_the_appendix_at_its_start_gives_no_passage() -> None:
    text, records, _ = build()
    tail = records[-1]
    assert [s for s in cut(text, records, tail.start) if s.key == "реквизиты"] == []


def test_boundaries_have_no_surrounding_whitespace() -> None:
    text, records, tail_end = build()
    for span in cut(text, records, tail_end):
        piece = text[span.start:span.end]
        assert piece == piece.strip(), span.key
        assert span.end > span.start


def test_blank_record_gives_no_passage() -> None:
    text, records, tail_end = build()
    assert "7.4" not in [s.key for s in cut(text, records, tail_end)]


def test_parts_and_order() -> None:
    text, records, tail_end = build()
    spans = cut(text, records, tail_end)
    assert [s.part for s in spans] == ["preamble"] + ["main"] * 6 + ["tail"]
    assert [s.start for s in spans] == sorted(s.start for s in spans)


def test_no_records_no_passages() -> None:
    assert cut("", [], 0) == []


# --- label -------------------------------------------------------------------------------


def _record(key: str) -> ClauseRecord:
    _, records, _ = build()
    return next(r for r in records if r.key == key)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("преамбула", "D-0001 · преамбула"),
        ("реквизиты", "D-0001 · реквизиты"),
        ("2", "D-0001 · раздел 2. Цена"),
        ("1.1", "D-0001 · раздел 1. Предмет договора · пункт 1.1"),
        ("1.1.1", "D-0001 · раздел 1. Предмет договора · пункт 1.1.1"),
        ("5.1", "D-0001 · раздел 5 · пункт 5.1"),  # empty section title
        ("7.3", "D-0001 · пункт 7.3"),  # no section
    ],
)
def test_label(key: str, expected: str) -> None:
    assert label("D-0001", _record(key)) == expected


def test_label_uses_the_document_id() -> None:
    assert label("D-0042", _record("2.1")) == "D-0042 · раздел 2. Цена · пункт 2.1"


# --- coverage ----------------------------------------------------------------------------


def test_cut_covers_everything_once() -> None:
    text, records, tail_end = build()
    assert coverage(text, records, tail_end, cut(text, records, tail_end)) == (0, 0)


def test_a_missing_passage_is_uncovered() -> None:
    text, records, tail_end = build()
    spans = [s for s in cut(text, records, tail_end) if s.key != "1.1"]
    uncovered, doubled = coverage(text, records, tail_end, spans)
    assert uncovered == len("1.1.Подрядчиквыполняетработы.")
    assert doubled == 0


def test_an_overlap_is_doubled() -> None:
    text, records, tail_end = build()
    spans = cut(text, records, tail_end)
    first = spans[1]
    spans.append(PassageSpan("x", "main", first.start, first.start + 4))  # «1.1.»
    assert coverage(text, records, tail_end, spans) == (0, 4)


def test_heading_lines_and_appendices_are_not_expected() -> None:
    text, records, tail_end = build()
    spans = cut(text, records, tail_end)
    # nothing of «1. Предмет договора», «2. Цена» or «Приложение № 1 Смета» is required
    assert coverage(text, records, tail_end, spans) == (0, 0)
    assert coverage(text, records, len(text), spans)[0] == len("Приложение№1Смета")
