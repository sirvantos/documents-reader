"""Direct tests of `extraction.extract_documents` (task T017), without the CLI."""

from __future__ import annotations

import pytest

from docreader import db as dbmod
from docreader import extraction
from docreader.config import load_settings
from docreader.errors import UserError
from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import add_variants, answer
from tests.integration.test_read import stage


def test_unsupported_answers_need_review(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "missing")
    use_model(ScriptedModel(answer()))
    with dbmod.connect(load_settings()) as conn:
        run = extraction.extract_documents(conn, load_settings(), None)
    assert run.run_id is not None
    assert stage(db, doc, "extraction")[0] == "needs_review"
    assert run.documents[0].document_id == doc and run.documents[0].rejected == 3


def test_all_with_seqs_is_refused(cli, db) -> None:
    with dbmod.connect(load_settings()) as conn, pytest.raises(UserError):
        extraction.extract_documents(conn, load_settings(), [1], all_documents=True)


def test_nothing_chosen_makes_no_run(cli, db) -> None:
    with dbmod.connect(load_settings()) as conn:
        run = extraction.extract_documents(conn, load_settings(), None)
    assert run.run_id is None
    assert db.execute("SELECT count(*) FROM run WHERE stage = 'extraction'").fetchone()[0] == 0
