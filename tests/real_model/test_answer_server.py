"""Level 3: the real language model on the synthetic answer contracts (feature 09; T018).

Only on the analyst's Mac, with the model server running (quickstart Б1):

    uv run --env-file .env pytest -m real_model tests/real_model/test_answer_server.py

Excluded by default (`addopts = -m 'not real_model'`); the fixture `_forbid_models` does
not set DOCREADER_FORBID_MODELS for this group. The synthetic contracts of
`make_answer_contracts` go through the pipeline in a test database with the search fakes
(`TopicEmbedder`, `TableReranker`); only the language model is real, at `[extraction]
base_url` of $DOCREADER_DATA_DIR/settings.toml (read before the `cli` fixture points the
variable at a temporary folder), otherwise the defaults. Connections to anything but this
machine fail the test (`_no_network`, principle I). It checks the connection and the form
of the answer, not its quality.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from docreader import answer, llm, textnorm
from docreader.config import ExtractionSettings, load_settings
from docreader.errors import ModelUnavailable
from tests.fakes.reranker import TableReranker
from tests.integration.answer_fixtures import ANSWER_SCORES, index_answer_contracts

pytestmark = pytest.mark.real_model


@pytest.fixture(autouse=True)
def real_extraction() -> ExtractionSettings:
    """`[extraction]` of the analyst's data folder; autouse, so it runs before `cli`."""
    if os.environ.get("DOCREADER_DATA_DIR"):
        return load_settings().extraction
    return ExtractionSettings()


@pytest.fixture
def indexed(cli, tmp_path, use_embedder, use_reranker) -> None:
    index_answer_contracts(cli, tmp_path, use_embedder)
    use_reranker(TableReranker(ANSWER_SCORES))


def _ask(db, real_extraction: ExtractionSettings, question: str) -> answer.Answer:
    settings = dataclasses.replace(load_settings(), extraction=real_extraction)
    return answer.ask(db, settings, question, document_id="D-0001")


def test_answer_in_the_text_has_every_quote_found(
    db, indexed, real_extraction: ExtractionSettings
) -> None:
    result = _ask(db, real_extraction, "Какой срок оплаты?")
    assert result.outcome == answer.AnswerOutcome.ANSWERED
    shown = {p.clause_id: p for p in result.shown}
    for claim in result.claims:
        if not claim.confirmed:  # confirmed_elsewhere too: clause_id is the actual place
            continue
        passage = shown[claim.clause_id]
        text = db.execute(
            "SELECT text FROM document_text WHERE document_id = %s", (passage.document_id,)
        ).fetchone()[0]
        start, end = db.execute(
            "SELECT start, end_ FROM passage WHERE document_id = %s AND clause_key = %s",
            (passage.document_id, passage.clause_key),
        ).fetchone()
        assert textnorm.locate(text[start:end], claim.quote), claim.quote


def test_question_without_an_answer_is_not_found(
    db, indexed, real_extraction: ExtractionSettings
) -> None:
    result = _ask(db, real_extraction, "Предусмотрен ли аванс?")
    assert result.outcome == answer.AnswerOutcome.NOT_FOUND


def test_closed_port_is_model_unavailable(real_extraction: ExtractionSettings) -> None:
    settings = dataclasses.replace(real_extraction, base_url="http://127.0.0.1:1/v1")
    with pytest.raises(ModelUnavailable):
        llm.load_client(settings).check()
