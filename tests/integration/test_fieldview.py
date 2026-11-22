"""Direct tests of `fieldview.load_fields` (feature 05, T022), without the CLI."""

from __future__ import annotations

import pytest

from docreader.errors import UserError
from docreader.fields import FIELD_NAMES
from docreader.fieldview import load_fields
from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import add_variants, answer, text_sha


@pytest.fixture
def doc(cli, tmp_path, use_model) -> str:
    (a,) = add_variants(cli, tmp_path / "in", "base")
    use_model(ScriptedModel(answer()))
    assert cli("extract", a).exit_code == 0
    return a


def test_loads_six_fields_in_catalog_order(db, doc) -> None:
    view = load_fields(db, 1)
    assert view.document_id == doc
    assert [f.field for f in view.fields] == list(FIELD_NAMES)
    assert view.state
    first = view.fields[0]
    assert first.result == "found"
    assert first.clause_id == f"{doc}/преамбула"
    assert not first.clause_missing
    assert first.pages and first.page is not None


def test_clause_missing_after_parse_rows_removed(db, doc) -> None:
    db.execute("DELETE FROM clause WHERE document_id = %s", (doc,))
    view = load_fields(db, 1)
    found = [f for f in view.fields if f.result == "found"]
    assert found
    assert all(f.clause_id is None and f.clause_missing for f in found)


def test_unknown_document(db, doc) -> None:
    with pytest.raises(UserError, match="D-0099 не найден"):
        load_fields(db, 99)


def test_not_extracted(db, doc) -> None:
    db.execute("DELETE FROM field_value")
    with pytest.raises(UserError, match=f"Поля {doc} не извлекались"):
        load_fields(db, 1)


def test_stale_text(db, doc) -> None:
    assert text_sha(db, doc)
    db.execute(
        "UPDATE document_text SET text_sha256 = repeat('0', 64) WHERE document_id = %s", (doc,)
    )
    with pytest.raises(UserError, match="Поля устарели"):
        load_fields(db, 1)
