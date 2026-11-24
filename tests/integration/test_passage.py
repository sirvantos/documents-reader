"""Integration tests for `docreader passage` (feature 07; task T019).

After `index` on `make_passage_contract` with `HashEmbedder`. Written by the main session;
the implementer must not edit, weaken, skip or delete these tests (CLAUDE.md «Model
routing»).
"""

from __future__ import annotations

import json

import pytest

from tests.fakes.embedding import HashEmbedder
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk


@pytest.fixture
def doc(cli, tmp_path) -> str:
    (doc_id,) = add_files(cli, tmp_path / "in", [mk.make_passage_contract])
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    return doc_id


@pytest.fixture
def indexed(cli, doc, use_embedder) -> int:
    use_embedder(HashEmbedder())
    result = cli("index", "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)["run_id"]


def test_text_output(cli, db, doc, indexed) -> None:
    result = cli("passage", f"{doc}/3.1")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0].startswith(
        f"{doc}/3.1 — стр. 2, основной текст (индексация: запуск {indexed}, "
    )
    assert lines[1] == f"Метка: {doc} · раздел 3. Ответственность · пункт 3.1"
    assert lines[2] == "В индексе по словам: да"
    assert lines[3] == "В индексе по смыслу: bge-m3, размерность 8"
    assert lines[4] == "Текст:"
    assert "\n".join(lines[5:]) == mk.PASSAGE_TRUTH["3.1"]


def test_json_output(cli, db, doc, indexed) -> None:
    result = cli("passage", f"{doc}/преамбула", "--json")
    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data == {
        "clause_id": f"{doc}/преамбула",
        "document_id": doc,
        "clause_key": "преамбула",
        "part": "preamble",
        "first_page": 1,
        "last_page": 1,
        "label": f"{doc} · преамбула",
        "text": mk.PASSAGE_TRUTH["преамбула"],
        "word_index": True,
        "vectors": [{"model": "bge-m3", "dims": 8, "truncated": False,
                     "input_chars": len(f"{doc} · преамбула") + 1
                     + len(mk.PASSAGE_TRUTH["преамбула"])}],
        "run_id": indexed,
    }


def test_truncated_input_is_shown(cli, db, doc, data_dir, use_embedder) -> None:
    (data_dir / "settings.toml").write_text("[embedding]\nmax_chars = 60\n", "utf-8")
    use_embedder(HashEmbedder())
    assert cli("index").exit_code == 0
    result = cli("passage", f"{doc}/3.1")
    assert "В индексе по смыслу: bge-m3, размерность 8 (вход обрезан до 60 знаков)" in (
        result.stdout
    )


def test_heading_only_record(cli, doc, indexed) -> None:
    result = cli("passage", f"{doc}/1")
    assert result.exit_code == 1
    assert f"Нет отрывка {doc}/1: у записи нет текста, кроме заголовка" in result.stderr


def test_unknown_record(cli, doc, indexed) -> None:
    result = cli("passage", f"{doc}/9.9")
    assert result.exit_code == 1
    assert f"Нет записи {doc}/9.9" in result.stderr


def test_bad_id_form(cli, doc, indexed) -> None:
    result = cli("passage", "пункт 3.1")
    assert result.exit_code == 1
    assert "D-0001/5.2" in result.stderr  # the message shows an example of the form


def test_unknown_document(cli, doc, indexed) -> None:
    result = cli("passage", "D-0099/3.1")
    assert result.exit_code == 1
    assert "D-0099" in result.stderr


def test_not_indexed(cli, doc) -> None:
    result = cli("passage", f"{doc}/3.1")
    assert result.exit_code == 1
    assert f"Отрывков нет: выполните docreader index {doc}" in result.stderr


def test_stale_after_a_second_parse(cli, doc, indexed) -> None:
    assert cli("parse", doc).exit_code == 0
    result = cli("passage", f"{doc}/3.1")
    assert result.exit_code == 1
    assert (
        f"Отрывки устарели: текст или разбор изменились — выполните docreader index {doc}"
        in result.stderr
    )


def test_stale_after_a_text_change(cli, db, doc, indexed) -> None:
    db.execute("UPDATE document_text SET text_sha256 = %s WHERE document_id = %s",
               ("e" * 64, doc))
    result = cli("passage", f"{doc}/3.1")
    assert result.exit_code == 1
    assert "Отрывки устарели" in result.stderr
