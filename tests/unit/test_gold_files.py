"""Parsing gold files: the template (CSV) and the review answers (JSON) (feature 02, T010).

research.md R-2, R-6; contracts/files.md. Pure functions of `docreader.gold`, no database.
"""

from __future__ import annotations

import json

import pytest

from docreader import catalog
from docreader.gold import (
    CellValue,
    GoldFileError,
    GoldPath,
    GoldState,
    LoadKind,
    parse_review_answers,
    parse_template,
    write_template,
)

REGISTRY = {"D-0001", "D-0002", "D-0003"}
BOM = "﻿"


def csv_bytes(lines: list[str], *, bom: bool = True) -> bytes:
    return ((BOM if bom else "") + "\r\n".join(lines) + "\r\n").encode("utf-8")


HEADER = '"document_id";"contract_number";"amount_with_vat";"contract_end_date"'


# --- template: dialect and structure ------------------------------------------------------


@pytest.mark.parametrize("bom", [True, False])
@pytest.mark.parametrize("sep", [";", ","])
def test_template_dialects(sep: str, bom: bool) -> None:
    lines = [
        HEADER.replace(";", sep),
        sep.join(['"#вид"', '"идентификатор"', '"сумма"', '"дата"']),
        sep.join(['"D-0001"', '"ДП-1"', '"1 000 000,00"', '"25.03.2027"']),
    ]
    parsed = parse_template(csv_bytes(lines, bom=bom), REGISTRY)
    assert parsed.kind is LoadKind.TEMPLATE
    assert parsed.errors == []
    assert parsed.values[("D-0001", "amount_with_vat")] == CellValue(
        GoldState.VALUE, ("1 000 000,00",), ("1000000.00",), GoldPath.TEMPLATE
    )
    assert parsed.values[("D-0001", "contract_end_date")].values_normalized == ("2027-03-25",)
    assert parsed.coverage == frozenset(
        ("D-0001", f) for f in ("contract_number", "amount_with_vat", "contract_end_date")
    )


def test_hash_rows_are_skipped() -> None:
    lines = [HEADER, '"#вид";"x";"y";"z"', '"#подсказка";"a";"b";"c"', '"D-0001";"";"";""']
    parsed = parse_template(csv_bytes(lines), REGISTRY)
    assert parsed.errors == []
    assert parsed.values == {}
    assert len(parsed.coverage) == 3


def test_empty_cell_is_unlabeled_but_covered() -> None:
    parsed = parse_template(csv_bytes([HEADER, '"D-0002";"";"";""']), REGISTRY)
    assert parsed.values == {}
    assert ("D-0002", "contract_number") in parsed.coverage


@pytest.mark.parametrize("mark", ["отсутствует", "Отсутствует", " ОТСУТСТВУЕТ "])
def test_absent_mark(mark: str) -> None:
    parsed = parse_template(csv_bytes([HEADER, f'"D-0001";"{mark}";"";""']), REGISTRY)
    assert parsed.values[("D-0001", "contract_number")] == CellValue(
        GoldState.ABSENT, (), (), GoldPath.TEMPLATE
    )


def test_variants() -> None:
    parsed = parse_template(csv_bytes([HEADER, '"D-0001";"ДП-1 || ДП-1/А";"";""']), REGISTRY)
    cell = parsed.values[("D-0001", "contract_number")]
    assert cell.values_text == ("ДП-1", "ДП-1/А")
    assert cell.values_normalized == ("ДП-1", "ДП-1/А")


def test_wrong_kind_names_row_and_column_never_the_value() -> None:
    lines = [HEADER, '"#вид";"";"";""', '"D-0001";"ДП-1";"очень много";""']
    parsed = parse_template(csv_bytes(lines), REGISTRY)
    assert ("D-0001", "amount_with_vat") not in parsed.values
    assert ("D-0001", "amount_with_vat") in parsed.coverage
    assert ("D-0001", "contract_number") in parsed.values
    [error] = parsed.errors
    assert error.where == "строка 3, столбец amount_with_vat"
    assert "сумме" in error.reason
    assert "очень много" not in error.where + error.reason


def test_one_bad_variant_rejects_the_cell() -> None:
    parsed = parse_template(csv_bytes([HEADER, '"D-0001";"";"100 || сто";""']), REGISTRY)
    assert ("D-0001", "amount_with_vat") not in parsed.values
    assert len(parsed.errors) == 1


def test_unknown_column_rejects_the_file() -> None:
    lines = ['"document_id";"contract_number";"bogus_field"', '"D-0001";"";""']
    with pytest.raises(GoldFileError, match="bogus_field"):
        parse_template(csv_bytes(lines), REGISTRY)


def test_no_document_column_rejects_the_file() -> None:
    with pytest.raises(GoldFileError, match="document_id"):
        parse_template(csv_bytes(['"contract_number"', '"ДП-1"']), REGISTRY)


def test_document_not_in_registry_is_skipped() -> None:
    lines = [HEADER, '"D-0009";"ДП-9";"";""', '"D-0001";"ДП-1";"";""']
    parsed = parse_template(csv_bytes(lines), REGISTRY)
    assert [s.where for s in parsed.skipped_rows] == ["строка 2"]
    assert "D-0009" in parsed.skipped_rows[0].reason
    assert all(doc != "D-0009" for doc, _ in parsed.coverage)
    assert ("D-0001", "contract_number") in parsed.values


def test_repeated_document_row_is_skipped() -> None:
    lines = [HEADER, '"D-0001";"ДП-1";"";""', '"D-0001";"ДП-2";"";""']
    parsed = parse_template(csv_bytes(lines), REGISTRY)
    assert parsed.values[("D-0001", "contract_number")].values_text == ("ДП-1",)
    assert [s.where for s in parsed.skipped_rows] == ["строка 3"]


def test_blind_kind() -> None:
    parsed = parse_template(csv_bytes([HEADER, '"D-0001";"ДП-1";"";""']), REGISTRY,
                            kind=LoadKind.BLIND)
    assert parsed.kind is LoadKind.BLIND


def test_not_utf8_rejects_the_file() -> None:
    with pytest.raises(GoldFileError, match="UTF-8"):
        data = (HEADER + '\r\n"D-0001";"ДП-1";"";""').encode("cp1251")
        parse_template(data, REGISTRY)


# --- write_template -----------------------------------------------------------------------


def test_write_template_round_trips_with_all_cells_unlabeled() -> None:
    fields = list(catalog.PROTOTYPE)
    data = write_template(fields, ["D-0001", "D-0002"])
    assert data.startswith(BOM.encode("utf-8"))
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    assert lines[0].split(";")[0] == '"document_id"'
    assert lines[1].startswith('"#вид"') and lines[2].startswith('"#подсказка"')
    assert "отсутствует" in lines[2] and "||" in lines[2]
    parsed = parse_template(data, REGISTRY)
    assert parsed.errors == [] and parsed.values == {}
    assert len(parsed.coverage) == 12


# --- review answers -----------------------------------------------------------------------


def _system(value: str, normalized: str, clause: str) -> dict[str, str]:
    return {"value": value, "normalized": normalized, "clause": clause}


CARDS = [
    {"key": "D-0001/contract_number", "document_id": "D-0001", "field": "contract_number",
     "mark": "agree", "model": _system("ДП-1", "ДП-1", "преамбула"),
     "rules": [_system("ДП-1", "ДП-1", "преамбула")]},
    {"key": "D-0001/amount_with_vat", "document_id": "D-0001", "field": "amount_with_vat",
     "mark": "disagree", "model": _system("1 000 руб.", "1000.00", "2.1"),
     "rules": [_system("1 200 руб.", "1200.00", "2.1"), _system("1 300 руб.", "1300.00", "2.2")]},
    {"key": "D-0001/contract_end_date", "document_id": "D-0001", "field": "contract_end_date",
     "mark": "none", "model": None, "rules": []},
    {"key": "D-0002/customer_name_short", "document_id": "D-0002",
     "field": "customer_name_short", "mark": "model_only",
     "model": _system("ООО «Альфа»", 'ООО "Альфа"', "преамбула"), "rules": []},
    {"key": "D-0002/contractor_name_short", "document_id": "D-0002",
     "field": "contractor_name_short", "mark": "rules_only", "model": None,
     "rules": [_system("ООО «Бета»", 'ООО "Бета"', "преамбула")]},
    {"key": "D-0002/contract_number", "document_id": "D-0002", "field": "contract_number",
     "mark": "agree", "model": _system("ДП-2", "ДП-2", "преамбула"),
     "rules": [_system("ДП-2", "ДП-2", "преамбула")]},
]


def answers(*cards: dict[str, object], fmt: str = "docreader-gold-review/1") -> bytes:
    return json.dumps({"format": fmt, "build": "b1", "cards": list(cards)},
                      ensure_ascii=False).encode("utf-8")


def test_agree_on_an_agree_card() -> None:
    parsed = parse_review_answers(
        answers({"key": "D-0001/contract_number", "answer": "agree"}), CARDS
    )
    assert parsed.kind is LoadKind.REVIEW
    assert parsed.values[("D-0001", "contract_number")] == CellValue(
        GoldState.VALUE, ("ДП-1",), ("ДП-1",), GoldPath.AGREE, "преамбула", "ДП-1"
    )


def test_agree_on_one_source_card_is_confirmed() -> None:
    parsed = parse_review_answers(
        answers(
            {"key": "D-0002/customer_name_short", "answer": "agree"},
            {"key": "D-0002/contractor_name_short", "answer": "agree"},
        ),
        CARDS,
    )
    model = parsed.values[("D-0002", "customer_name_short")]
    assert model.path is GoldPath.CONFIRMED
    assert model.system_normalized == 'ООО "Альфа"'
    rules = parsed.values[("D-0002", "contractor_name_short")]
    assert rules.path is GoldPath.CONFIRMED
    assert rules.values_normalized == ('ООО "Бета"',)
    assert rules.system_normalized is None  # feature 05 gave nothing on that card


@pytest.mark.parametrize(
    ("choice", "normalized"),
    [("model", "1000.00"), ("rules", "1200.00"), ("rules:1", "1200.00"), ("rules:2", "1300.00")],
)
def test_chosen(choice: str, normalized: str) -> None:
    parsed = parse_review_answers(
        answers({"key": "D-0001/amount_with_vat", "answer": "chosen", "choice": choice}), CARDS
    )
    cell = parsed.values[("D-0001", "amount_with_vat")]
    assert cell.path is GoldPath.CHOSEN
    assert cell.values_normalized == (normalized,)
    assert cell.system_normalized == "1000.00"


def test_chosen_takes_the_value_from_the_build_not_from_the_answer() -> None:
    parsed = parse_review_answers(
        answers({"key": "D-0001/amount_with_vat", "answer": "chosen", "choice": "model",
                 "value": "999 руб."}),
        CARDS,
    )
    assert parsed.values[("D-0001", "amount_with_vat")].values_text == ("1 000 руб.",)


def test_typed_with_clause() -> None:
    parsed = parse_review_answers(
        answers({"key": "D-0001/contract_end_date", "answer": "typed",
                 "value": "25 марта 2027 г.", "clause": "D-0001/4.1"}),
        CARDS,
    )
    assert parsed.values[("D-0001", "contract_end_date")] == CellValue(
        GoldState.VALUE, ("25 марта 2027 г.",), ("2027-03-25",), GoldPath.TYPED, "4.1", None
    )


def test_typed_wrong_kind_names_the_card_and_leaves_it_unlabeled() -> None:
    parsed = parse_review_answers(
        answers({"key": "D-0001/contract_end_date", "answer": "typed", "value": "когда-нибудь"}),
        CARDS,
    )
    assert ("D-0001", "contract_end_date") not in parsed.values
    [error] = parsed.errors
    assert error.where == "карточка D-0001/contract_end_date"
    assert "когда-нибудь" not in error.where + error.reason


def test_absent_and_skip() -> None:
    parsed = parse_review_answers(
        answers(
            {"key": "D-0001/contract_end_date", "answer": "absent"},
            {"key": "D-0002/contract_number", "answer": "skip"},
        ),
        CARDS,
    )
    assert parsed.values[("D-0001", "contract_end_date")] == CellValue(
        GoldState.ABSENT, (), (), GoldPath.ABSENT_MARKED, None, None
    )
    assert ("D-0002", "contract_number") not in parsed.values


def test_coverage_is_every_card_of_the_build() -> None:
    parsed = parse_review_answers(answers(), CARDS)
    assert parsed.coverage == frozenset((c["document_id"], c["field"]) for c in CARDS)


def test_unknown_card_key_is_an_error() -> None:
    parsed = parse_review_answers(answers({"key": "D-0009/contract_number", "answer": "agree"}),
                                  CARDS)
    assert [e.where for e in parsed.errors] == ["карточка D-0009/contract_number"]


@pytest.mark.parametrize(
    "bad",
    [
        {"key": "D-0002/contract_number", "answer": "maybe"},
        {"key": "D-0001/amount_with_vat", "answer": "chosen", "choice": "rules:9"},
        {"key": "D-0001/contract_end_date", "answer": "agree"},  # nothing to agree with
    ],
)
def test_invalid_answers_are_errors(bad: dict[str, str]) -> None:
    parsed = parse_review_answers(answers(bad), CARDS)
    assert len(parsed.errors) == 1
    assert parsed.values == {}


def test_wrong_format_rejects_the_file() -> None:
    with pytest.raises(GoldFileError, match="формат"):
        parse_review_answers(answers(fmt="other/1"), CARDS)


def test_not_json_rejects_the_file() -> None:
    with pytest.raises(GoldFileError):
        parse_review_answers(b"not json", CARDS)



def test_hints_ask_for_the_legal_form_and_the_kopecks() -> None:
    # analyst's blind marking, record 32 (SC-006): short names were written without the
    # legal form and amounts without kopecks — the hints did not say either was needed
    import csv
    import io

    fields = list(catalog.PROTOTYPE)
    rows = list(csv.reader(io.StringIO(write_template(fields, []).decode("utf-8-sig")),
                           delimiter=";"))
    hints = dict(zip(rows[0][1:], rows[2][1:], strict=True))
    for name in ("customer_name_short", "contractor_name_short"):
        assert "с формой" in hints[name] and "АО «" in hints[name]
    for name in ("amount_without_vat", "amount_with_vat"):
        assert "с копейками" in hints[name]
