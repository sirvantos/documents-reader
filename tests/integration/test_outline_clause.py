"""Integration tests for `docreader outline` and `docreader clause` (feature 04, task T014).

The loaders of `docreader.clauseview` are tested directly (task T015) and through the CLI
(task T016) on the synthetic contract `make_structured_contract` after `parse`.
"""

from __future__ import annotations

import json

import pytest

from docreader import clauseview
from docreader.errors import UserError
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk

REASON_START = "пропуск: после 5.2 идёт 5.4 (стр. 4)"


def seq_of(doc_id: str) -> int:
    return int(doc_id[2:])


@pytest.fixture
def parsed(cli, db, tmp_path) -> str:
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_structured_contract])
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    # page 2 is marked as recognised to see the mark (no engine runs here)
    db.execute(
        "UPDATE page_text SET source = 'recognized' WHERE document_id = %s AND page_number = 2",
        (doc,),
    )
    return doc


# --- loaders (T015) -----------------------------------------------------------------------


def test_load_outline(db, parsed):
    outline = clauseview.load_outline(db, seq_of(parsed))
    assert (outline.document_id, outline.state) == (parsed, "needs_review")
    assert outline.reason is not None and outline.reason.startswith(REASON_START)
    assert outline.unread_pages == [3]
    ids = [r.id for r in outline.records]
    assert ids[0] == f"{parsed}/преамбула" and ids[-1] == f"{parsed}/реквизиты"
    by_key = {r.key: r for r in outline.records}
    assert by_key["1.2.1.1"].depth == 4 and by_key["1.2.1.1"].parent == "1.2.1"
    assert by_key["2.2"].recognized and by_key["1.2.2"].recognized  # page 2 in their pages
    assert not by_key["1.1"].recognized and not by_key["4"].recognized
    assert by_key["2"].head == "2. Цена договора"
    assert len(by_key["1"].head) <= 60 and "\n" not in by_key["преамбула"].head


def test_load_clause_with_subclauses_and_own(db, parsed):
    view = clauseview.load_clause(db, seq_of(parsed), "1.2", own=False)
    assert [p.id for p in view.records] == [
        f"{parsed}/1.2", f"{parsed}/1.2.1", f"{parsed}/1.2.1.1", f"{parsed}/1.2.2",
    ]
    assert view.records[0].text.startswith("1.2. Работы выполняются в два этапа.")
    assert (view.first_page, view.last_page, view.recognized) == (1, 2, True)
    assert view.section_title == "Предмет договора"
    own = clauseview.load_clause(db, seq_of(parsed), "1.2", own=True)
    assert [p.id for p in own.records] == [f"{parsed}/1.2"]
    assert (own.first_page, own.last_page) == (1, 1)


def test_load_clause_does_not_take_a_longer_number_as_a_child(db, parsed):
    view = clauseview.load_clause(db, seq_of(parsed), "2.1.1", own=False)
    assert [p.id for p in view.records] == [f"{parsed}/2.1.1"]  # not 2.1.10, 2.1.11, 2.1.12


def test_loader_errors(db, cli, tmp_path, parsed):
    with pytest.raises(UserError, match=rf"Пункт {parsed}/5\.9 не найден"):
        clauseview.load_clause(db, seq_of(parsed), "5.9", own=False)
    (other,) = add_files(cli, tmp_path / "more", [lambda p: mk.make_contract_ru(p, pages=1)])
    assert cli("read", other).exit_code == 0
    with pytest.raises(UserError, match=f"Документ {other} не разобран"):
        clauseview.load_outline(db, seq_of(other))
    db.execute(
        "UPDATE document_text SET text_sha256 = repeat('b', 64) WHERE document_id = %s",
        (parsed,),
    )
    with pytest.raises(UserError, match="Разбор устарел"):
        clauseview.load_outline(db, seq_of(parsed))
    with pytest.raises(UserError, match="Разбор устарел"):
        clauseview.load_clause(db, seq_of(parsed), "1.2", own=False)


# --- CLI (T016) ---------------------------------------------------------------------------


def test_outline_text(cli, parsed):
    result = cli("outline", parsed)
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith(f"{parsed} — разбор от")
    assert "требует просмотра" in lines[0] and REASON_START in lines[0]
    by_id = {line.split()[0]: line for line in lines[1:] if line.startswith(parsed)}
    assert f"{parsed}/1.2.1.1" in by_id and f"{parsed}/реквизиты" in by_id
    assert "[распознано]" in by_id[f"{parsed}/2.2"]
    assert "[распознано]" not in by_id[f"{parsed}/1.1"]
    assert "стр. 1–2" in by_id[f"{parsed}/1.2.2"]
    # the unread page stands between section 3 and section 4
    texts = [line.strip() for line in lines]
    i3 = next(i for i, line in enumerate(lines) if line.startswith(f"{parsed}/3 "))
    i4 = next(i for i, line in enumerate(lines) if line.startswith(f"{parsed}/4 "))
    assert any("страница 3 не прочитана" in t for t in texts[i3:i4])
    # deeper records are indented more
    assert by_id[f"{parsed}/1.2.1.1"].index("1.2.1.1.") > by_id[f"{parsed}/1"].index("1.")


def test_outline_json(cli, parsed):
    result = cli("outline", parsed, "--json")
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data) == {"document_id", "state", "reason", "run_id", "records", "unread_pages"}
    assert data["unread_pages"] == [3]
    first = data["records"][0]
    assert set(first) == {
        "id", "key", "kind", "number_printed", "depth", "parent", "title", "section_number",
        "section_title", "start", "end", "first_page", "last_page", "recognized", "head",
    }
    assert first["id"] == f"{parsed}/преамбула" and first["kind"] == "preamble"


def test_clause_text_with_subclauses(cli, parsed):
    result = cli("clause", f"{parsed}/1.2")
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    order = [out.index(s) for s in ("1.2. Работы", "1.2.1. Первый", "1.2.1.1. Подготовка",
                                    "1.2.2. Второй")]
    assert order == sorted(order)
    for number in ("1.2.1. Первый", "1.2.1.1. Подготовка", "1.2.2. Второй"):
        assert f"\n{number}" in out  # every record starts on its own line
    assert "Предмет договора" in out  # the section title is in the header


def test_clause_own_text(cli, parsed):
    result = cli("clause", f"{parsed}/1.2", "--own")
    assert result.exit_code == 0, result.stderr
    assert "1.2. Работы выполняются в два этапа." in result.stdout
    assert "1.2.1." not in result.stdout


def test_clause_of_a_section(cli, parsed):
    result = cli("clause", f"{parsed}/6")
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert out.index("6. Ответственность сторон") < out.index("6.1. Стороны") < out.index("6.2")
    assert out.count("6. Ответственность сторон") == 2  # the heading and its repeat in 6.1


@pytest.mark.parametrize(("key", "start"), [("преамбула", "Договор подряда № 7/2026"),
                                             ("реквизиты", "7. Адреса и реквизиты сторон")])
def test_clause_of_preamble_and_tail(cli, parsed, key, start):
    result = cli("clause", f"{parsed}/{key}")
    assert result.exit_code == 0, result.stderr
    assert start in result.stdout


def test_clause_json(cli, parsed):
    result = cli("clause", f"{parsed}/1.2", "--json")
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data) == {"id", "section_title", "first_page", "last_page", "recognized",
                         "records"}
    assert set(data["records"][0]) == {"id", "number_printed", "depth", "start", "end", "text"}
    assert [r["id"] for r in data["records"]][-1] == f"{parsed}/1.2.2"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("clause", "D-0001/5."), "ожидается вид D-0001/5.2"),
        (
            ("clause", "D-0001/5.9"),
            "Пункт D-0001/5.9 не найден — оглавление: docreader outline D-0001",
        ),
        (("clause", "D-0099/1"), "D-0099"),
        (("outline", "D-0099"), "D-0099"),
    ],
)
def test_cli_errors(cli, parsed, args, message):
    assert parsed == "D-0001"
    result = cli(*args)
    assert result.exit_code == 1
    assert message in result.stderr


def test_not_parsed_document(cli, tmp_path, parsed):
    (other,) = add_files(cli, tmp_path / "more", [lambda p: mk.make_contract_ru(p, pages=1)])
    assert cli("read", other).exit_code == 0
    for args in (("outline", other), ("clause", f"{other}/1")):
        result = cli(*args)
        assert result.exit_code == 1
        assert f"Документ {other} не разобран — выполните docreader parse {other}" in result.stderr


def test_stale_parse(cli, db, parsed):
    db.execute(
        "UPDATE document_text SET text_sha256 = repeat('b', 64) WHERE document_id = %s",
        (parsed,),
    )
    for args in (("outline", parsed), ("clause", f"{parsed}/1.2")):
        result = cli(*args)
        assert result.exit_code == 1
        assert (
            f"Разбор устарел: текст изменён — выполните docreader parse {parsed}" in result.stderr
        )
