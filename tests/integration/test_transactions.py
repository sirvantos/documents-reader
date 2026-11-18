"""Transaction convention (tech-context «Правила кода», task T063).

The connection is in autocommit mode and every atomic write is an explicit
`with conn.transaction()`: a failure or Ctrl-C inside it leaves the previous result.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docreader import db as dbmod
from docreader.config import load_settings
from tests.synthetic import make_pdfs as mk


def _add_and_read(cli, folder: Path) -> str:
    folder.mkdir()
    mk.make_contract_ru(folder / "c.pdf")
    added = cli("add", folder, "--json")
    assert added.exit_code == 0, added.stderr
    (entry,) = json.loads(added.stdout)["files"]
    read = cli("read", entry["document_id"])
    assert read.exit_code == 0, read.stderr
    return entry["document_id"]


def _reading_result(db, doc_id: str) -> tuple:
    text = db.execute(
        "SELECT text_sha256, run_id FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()
    counts = db.execute(
        "SELECT (SELECT count(*) FROM page_text WHERE document_id = %(d)s),"
        " (SELECT count(*) FROM text_span WHERE document_id = %(d)s)",
        {"d": doc_id},
    ).fetchone()
    return text, counts


def _reading_state(db, doc_id: str) -> tuple:
    return db.execute(
        "SELECT state, reason FROM stage_status WHERE document_id = %s AND stage = 'reading'",
        (doc_id,),
    ).fetchone()


def test_connect_gives_an_autocommit_connection(cli_env, database_url):
    cli_env(database_url)
    conn = dbmod.connect(load_settings())
    try:
        assert conn.autocommit is True
    finally:
        conn.close()


def _break_the_write(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    """Fail inside the write transaction, after the old rows are deleted."""

    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr("docreader.reading.Jsonb", boom)


def test_interrupted_read_keeps_the_previous_result(cli, db, tmp_path, monkeypatch):
    doc_id = _add_and_read(cli, tmp_path / "in")
    before = _reading_result(db, doc_id)

    _break_the_write(monkeypatch, KeyboardInterrupt())
    result = cli("read", doc_id)

    assert result.exit_code == 130
    assert _reading_result(db, doc_id) == before
    assert _reading_state(db, doc_id) == ("done", None)
    # the run row is written outside the document transaction and is finished
    (finished,) = db.execute(
        "SELECT finished_at IS NOT NULL FROM run WHERE stage = 'reading' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert finished


def test_failed_write_keeps_the_previous_result_and_marks_failed(cli, db, tmp_path, monkeypatch):
    doc_id = _add_and_read(cli, tmp_path / "in")
    before = _reading_result(db, doc_id)

    _break_the_write(monkeypatch, RuntimeError("synthetic failure"))
    result = cli("read", doc_id, "--json")

    assert result.exit_code == 0, result.stderr
    assert _reading_result(db, doc_id) == before
    state, reason = _reading_state(db, doc_id)
    assert state == "failed"
    assert reason == "ошибка чтения: RuntimeError: synthetic failure"
