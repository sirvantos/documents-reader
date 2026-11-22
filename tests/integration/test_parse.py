"""Integration tests for `docreader parse` (feature 04; tasks T008, T013).

Everything goes through `add`, `read` and `parse`; the expected structure comes from the
synthetic contract `make_structured_contract` (tests/synthetic/make_pdfs.py).
"""

from __future__ import annotations

import json

import pytest

from docreader import structure
from tests.integration.test_read import add_files, set_stage, stage
from tests.synthetic import make_pdfs as mk

EXPECTED_KEYS = [
    "преамбула",
    "1", "1.1", "1.2", "1.2.1", "1.2.1.1", "1.2.2",
    "2", "2.1", *(f"2.1.{i}" for i in range(1, 13)), "2.2",
    "3",
    "4", "4.1", "4.2",
    "5.1", "5.2", "5.4",
    "6", "6.1", "6.2",
    "реквизиты",
]
EXPECTED_REASON = (
    "пропуск: после 5.2 идёт 5.4 (стр. 4); повтор: 6 (стр. 4); "
    "не прочитана страница внутри основного текста: стр. 3"
)
NOTHING = "Нечего разбирать: все документы разобраны (заново: docreader parse --all)"


def rows(db, doc_id: str) -> list[dict]:
    cur = db.execute(
        "SELECT key, ordinal, kind, number_printed, number, depth, parent_key, title,"
        " section_number, section_title, start, end_, first_page, last_page,"
        " source_text_sha256, run_id FROM clause WHERE document_id = %s ORDER BY ordinal",
        (doc_id,),
    )
    names = [c.name for c in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def by_key(db, doc_id: str) -> dict[str, dict]:
    return {r["key"]: r for r in rows(db, doc_id)}


def text_of(db, doc_id: str) -> tuple[str, str]:
    return db.execute(
        "SELECT text, text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()


def parse_json(cli, *args) -> dict:
    result = cli("parse", *args, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def structured(cli, tmp_path) -> str:
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_structured_contract])
    assert cli("read").exit_code == 0
    return doc


# --- US1: clauses (T008) ------------------------------------------------------------------


def test_parse_stores_every_record_of_the_structured_contract(cli, db, structured):
    result = cli("parse")
    assert result.exit_code == 0, result.stderr

    records = by_key(db, structured)
    assert [r["key"] for r in rows(db, structured)] == EXPECTED_KEYS
    assert not {"2.3", "2.4", "2.5", "7", "1.5"} & records.keys()  # table rows, tail, amount
    parents = {k: r["parent_key"] for k, r in records.items()}
    assert parents["1.2.1.1"] == "1.2.1"
    assert parents["1.2.2"] == "1.2"
    assert parents["2.1.12"] == "2.1"
    assert parents["5.1"] is None and parents["5.4"] is None  # heading «5.» is missing
    assert parents["6.2"] == "6"

    section = records["2"]
    assert (section["kind"], section["depth"], section["number"], section["title"]) == (
        "section", 1, [2], "Цена договора",
    )
    clause = records["2.2"]
    assert (clause["number_printed"], clause["depth"], clause["section_title"]) == (
        "2.2", 2, "Цена договора",
    )
    assert records["5.1"]["section_number"] is None
    assert records["6.2"]["number_printed"] == "6.2"

    # pages: 1.2.2 continues on page 2, section 3 ends before the unread page 3
    assert (records["1.2.2"]["first_page"], records["1.2.2"]["last_page"]) == (1, 2)
    assert (records["2.2"]["first_page"], records["3"]["last_page"]) == (2, 2)
    assert records["4"]["first_page"] == 4

    text, sha = text_of(db, structured)
    own = {k: text[r["start"] : r["end_"]] for k, r in records.items()}
    assert "а) разметку участка;" in own["1.2.2"] and "1) завоз материалов." in own["1.2.2"]
    assert "Работы второго этапа сдаются по акту." in own["1.2.2"]
    assert "01.03.2025 Заказчик вносит аванс." in own["2.1.12"]
    assert "2.5 млн рублей" in own["2.1.12"] and "1.5 тонны" in own["2.1.12"]
    for cell, _ in mk.STRUCTURED_CONTRACT_TABLE:
        assert cell in own["2.2"]  # the table stays inside clause 2.2
    assert own["6.1"].count("6. Ответственность сторон") == 1  # the repeated heading
    assert {r["source_text_sha256"] for r in records.values()} == {sha}

    assert stage(db, structured, "structure")[:2] == ("needs_review", EXPECTED_REASON)


def test_parse_run_row(cli, db, structured):
    data = parse_json(cli)
    run = db.execute(
        "SELECT stage, settings, finished_at FROM run WHERE id = %s", (data["run_id"],)
    ).fetchone()
    assert run[0] == "structure"
    assert run[1]["structure"] == {
        "max_gap": 5,
        "requisites_pattern": r"реквизит|подписи\s+сторон|адреса\s+сторон|юридические\s+адреса",
    }
    assert run[2] is not None
    assert {r["run_id"] for r in rows(db, structured)} == {data["run_id"]}


def test_parse_json_shape(cli, db, structured):
    data = parse_json(cli)
    assert set(data) == {"run_id", "documents", "skipped", "totals", "interrupted"}
    (doc,) = data["documents"]
    assert doc == {
        "document_id": structured,
        "state": "needs_review",
        "reason": EXPECTED_REASON,
        "sections": 5,  # 1, 2, 3, 4, 6
        "clauses": len(EXPECTED_KEYS) - 2 - 5,
        "first_page": 1,
        "last_page": 5,
        "has_tail": True,
    }
    assert data["skipped"] == []
    assert data["totals"] == {"parsed": 1, "needs_review": 1, "failed": 0, "skipped": 0}
    assert data["interrupted"] is False


def test_parse_text_output(cli, structured):
    result = cli("parse")
    assert result.exit_code == 0, result.stderr
    assert f"{structured}  требует просмотра" in result.stdout
    assert "Итого: разобрано 1, требует просмотра 1, ошибок 0, пропущено 0" in result.stdout


def test_nothing_to_parse(cli, structured):
    assert cli("parse").exit_code == 0
    again = cli("parse")
    assert again.exit_code == 0
    assert NOTHING in again.stdout


def test_reparse_replaces_rows_with_the_same_ids(cli, db, structured):
    first = parse_json(cli)
    before = rows(db, structured)
    second = parse_json(cli, structured)
    after = rows(db, structured)
    assert [r["key"] for r in after] == [r["key"] for r in before]  # SC-004
    assert [(r["start"], r["end_"]) for r in after] == [(r["start"], r["end_"]) for r in before]
    assert {r["run_id"] for r in after} == {second["run_id"]} != {first["run_id"]}
    third = parse_json(cli, "--all")
    assert {r["run_id"] for r in rows(db, structured)} == {third["run_id"]}


def test_all_with_ids_is_a_user_error(cli, structured):
    result = cli("parse", "--all", structured)
    assert result.exit_code == 1
    assert "--all" in result.stderr


def test_unknown_document_is_a_user_error(cli, structured):
    result = cli("parse", "D-0099")
    assert result.exit_code == 1
    assert "D-0099" in result.stderr


def test_not_read_document_is_skipped(cli, db, tmp_path, structured):
    (other,) = add_files(cli, tmp_path / "more", [lambda p: mk.make_contract_ru(p, pages=1)])
    data = parse_json(cli, structured, other)
    assert [d["document_id"] for d in data["documents"]] == [structured]
    assert data["skipped"] == [
        {"document_id": other, "reason": f"не прочитан — выполните docreader read {other}"}
    ]
    assert data["totals"]["skipped"] == 1
    assert stage(db, other, "structure")[:2] == ("pending", None)
    text = cli("parse", other)
    assert f"{other}  пропущен" in text.stdout


def test_document_without_read_pages_is_not_parsed_by_default(cli, db, tmp_path, structured):
    (blank,) = add_files(cli, tmp_path / "blank", [mk.make_blank_page])
    assert cli("read").exit_code == 0
    data = parse_json(cli)
    assert [d["document_id"] for d in data["documents"]] == [structured]
    assert rows(db, blank) == []


def test_failure_of_one_document_does_not_stop_the_others(cli, db, tmp_path, monkeypatch):
    first, second = add_files(
        cli, tmp_path / "in", [mk.make_structured_contract, lambda p: mk.make_contract_ru(p)]
    )
    assert cli("read").exit_code == 0
    original = structure.parse_lines
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("сбой разбора")
        return original(*args, **kwargs)

    monkeypatch.setattr(structure, "parse_lines", flaky)
    data = parse_json(cli)
    states = {d["document_id"]: d["state"] for d in data["documents"]}
    assert states == {first: "failed", second: "needs_review"}
    state, reason, _ = stage(db, first, "structure")
    assert state == "failed" and "RuntimeError" in reason and "сбой разбора" in reason
    assert rows(db, first) == []
    assert rows(db, second) != []


def test_failed_document_is_parsed_again_by_default(cli, db, structured):
    set_stage(db, structured, "structure", "failed", "сбой")
    data = parse_json(cli)
    assert [d["document_id"] for d in data["documents"]] == [structured]


# --- US2: preamble, tail, coverage (T013) ----------------------------------------------


def test_preamble_and_tail(cli, db, structured):
    assert cli("parse").exit_code == 0
    records = by_key(db, structured)
    text, _ = text_of(db, structured)
    preamble, tail = records["преамбула"], records["реквизиты"]
    assert (preamble["kind"], preamble["first_page"], preamble["last_page"]) == (
        "preamble", 1, 1,
    )
    assert text[preamble["start"] : preamble["end_"]].startswith("Договор подряда № 7/2026")
    assert (tail["kind"], tail["first_page"], tail["last_page"]) == ("tail", 4, 5)
    own = text[tail["start"] : tail["end_"]]
    assert own.startswith("7. Адреса и реквизиты сторон")
    assert "Приложение № 1" in own and "1.1. Земляные работы." in own


def test_records_cover_the_whole_text(cli, db, structured):
    assert cli("parse").exit_code == 0
    text, _ = text_of(db, structured)
    position = 0
    for r in rows(db, structured):
        assert r["start"] == position
        position = r["end_"]
    assert position == len(text)  # SC-003


def test_contract_without_requisites_needs_review(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [lambda p: mk.make_contract_ru(p, pages=3)])
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    assert stage(db, doc, "structure")[:2] == ("needs_review", "раздел реквизитов не найден")
    assert "реквизиты" not in by_key(db, doc)


def make_unnumbered(path):
    """One page of Russian text without any numbered line."""

    def draw(c):
        mk._ru_page(c, ("Стороны договорились о следующем.", "Работы выполняются в срок."))
        c.showPage()

    return mk._write(path, mk._pdf(draw))


def test_text_without_numbering_is_one_preamble(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [make_unnumbered])
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    assert [r["key"] for r in rows(db, doc)] == ["преамбула"]
    assert stage(db, doc, "structure")[:2] == ("needs_review", "нумерация не найдена")
