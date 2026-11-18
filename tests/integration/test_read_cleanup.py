"""Integration tests for text cleanup and `text --find` (task T034, feature 03, US3).

Everything goes through the CLI and the database; no internal functions are called.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.synthetic import make_pdfs as mk

HEADER = "Договор подряда № 123/45-У"


# --- helpers ------------------------------------------------------------------------


def add_one(cli, tmp_path: Path, make) -> str:
    folder = tmp_path / "in"
    folder.mkdir(parents=True, exist_ok=True)
    make(folder / "f0.pdf")
    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    (entry,) = json.loads(result.stdout)["files"]
    return entry["document_id"]


def read_doc(cli, tmp_path: Path, make) -> str:
    doc_id = add_one(cli, tmp_path, make)
    result = cli("read", doc_id)
    assert result.exit_code == 0, result.stderr
    return doc_id


def clean_text(db, doc_id: str) -> str:
    return db.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]


def stored_lines(db, doc_id: str) -> dict[int, list[dict]]:
    return {
        page: lines
        for page, lines in db.execute(
            "SELECT page_number, lines FROM page_text WHERE document_id = %s "
            "ORDER BY page_number",
            (doc_id,),
        )
    }


def find(cli, doc_id: str, phrase: str) -> dict:
    result = cli("text", doc_id, "--find", phrase, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


# --- US3-1: running headers and page numbers ----------------------------------------


def test_headers_and_page_numbers_are_removed_from_text_but_kept_in_lines(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, lambda p: mk.make_headers_ru(p, pages=5))

    body_text, headers, numbers = mk.headers_ru_expected(5)
    text = clean_text(db, doc)
    assert text == body_text
    assert HEADER not in text
    pages = stored_lines(db, doc)
    assert sorted(pages) == [1, 2, 3, 4, 5]
    for page, header_text in headers:
        roles = {ln["role"]: ln["text"] for ln in pages[page] if ln["role"] != "body"}
        assert roles.get("header") == header_text, f"page {page}"
    for page, number_text in numbers:
        roles = {ln["role"]: ln["text"] for ln in pages[page] if ln["role"] != "body"}
        assert roles.get("page_number") == number_text, f"page {page}"


def test_two_page_document_keeps_headers_in_text(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, lambda p: mk.make_headers_ru(p, pages=2))

    text = clean_text(db, doc)
    assert text.count(HEADER) == 2
    for lines in stored_lines(db, doc).values():
        assert all(ln["role"] == "body" for ln in lines)


# --- US3-5: search in removed elements ----------------------------------------------


def test_find_in_header_returns_match_on_each_page(cli, tmp_path):
    doc = read_doc(cli, tmp_path, lambda p: mk.make_headers_ru(p, pages=5))

    data = find(cli, doc, "№ 123/45-У")

    assert data["id"] == doc
    matches = data["matches"]
    assert [m["page"] for m in matches] == [1, 2, 3, 4, 5]
    for m in matches:
        assert m["role"] == "header"
        assert len(m["bbox"]) == 4
        assert m["end"] - m["start"] == len("№ 123/45-У")


def test_find_normalizes_nbsp_and_non_breaking_hyphen(cli, tmp_path):
    doc = read_doc(cli, tmp_path, lambda p: mk.make_headers_ru(p, pages=5))

    data = find(cli, doc, "№ 123/45‑У")

    assert data["phrase"] == "№ 123/45-У"
    assert [m["page"] for m in data["matches"]] == [1, 2, 3, 4, 5]


def test_find_without_match_prints_not_found_with_exit_zero(cli, tmp_path):
    doc = read_doc(cli, tmp_path, lambda p: mk.make_headers_ru(p, pages=5))

    result = cli("text", doc, "--find", "несуществующая фраза")

    assert result.exit_code == 0, result.stderr
    assert "Не найдено" in result.stdout
    assert find(cli, doc, "несуществующая фраза")["matches"] == []


# --- US3-2: hyphenation -------------------------------------------------------------


def test_hyphen_joins_and_exceptions(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_hyphens_ru)

    text = clean_text(db, doc)
    assert text == mk.HYPHENS_RU_TEXT
    assert "монтажные работы на объекте" in text
    assert "строительно-монтажные" in text
    assert "123/45-У" in text
    assert "раздел-\nПриложение" in text
    assert "пункт-\n2 настоящего" in text


# --- US3-3: phrase position ---------------------------------------------------------


def test_find_gives_page_line_and_exact_offsets(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, lambda p: mk.make_headers_ru(p, pages=5))
    text = clean_text(db, doc)
    pages = stored_lines(db, doc)
    phrases = {
        2: "Оплата производится в течение 10 рабочих дней",
        4: "Гарантийный срок на выполненные работы",
        5: "Споры разрешаются в арбитражном суде",
    }

    for page, phrase in phrases.items():
        (match,) = find(cli, doc, phrase)["matches"]
        assert text[match["start"] : match["end"]] == phrase
        assert match["page"] == page
        assert match["role"] == "body"
        line = next(ln for ln in pages[page] if ln["i"] == match["line"])
        assert phrase in line["text"]
        assert match["bbox"] == line["bbox"]


# --- US3-4: sentence across a page break --------------------------------------------


def test_sentence_across_page_break_is_kept_as_written(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_page_break_sentence_ru)

    assert clean_text(db, doc) == mk.PAGE_BREAK_SENTENCE_TEXT


# --- fake bold ----------------------------------------------------------------------


def test_fake_bold_lines_are_stored_without_doubled_letters(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, mk.make_fake_bold_ru)

    ((lines,),) = [(v,) for v in stored_lines(db, doc).values()]
    assert [ln["text"] for ln in lines] == list(mk.FAKE_BOLD_RU_LINES)


# --- run settings -------------------------------------------------------------------


def test_run_settings_contain_dictionary_version(cli, db, tmp_path):
    doc = read_doc(cli, tmp_path, lambda p: mk.make_headers_ru(p, pages=2))

    (version,) = db.execute(
        "SELECT r.settings->'reading'->>'dictionary' FROM document_text t "
        "JOIN run r ON r.id = t.run_id WHERE t.document_id = %s",
        (doc,),
    ).fetchone()
    assert version
