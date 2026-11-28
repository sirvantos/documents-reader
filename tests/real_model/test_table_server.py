"""Level 3: the real language model server on the table questions (feature 10; T019).

Only on the analyst's Mac, with the model server running:

    uv run --env-file .env pytest -m real_model tests/real_model/test_table_server.py

Excluded by default (`addopts = -m 'not real_model'`); the fixture `_forbid_models` does
not set DOCREADER_FORBID_MODELS for this group. `[extraction]` comes from
$DOCREADER_DATA_DIR/settings.toml when the variable is set, otherwise the defaults; the
client takes the `[table]` limits as `ask_table` does. Only the synthetic questions of
`tests/synthetic/table_questions.toml` are sent; connections to anything but this machine
fail the test (`_no_network`, principle I). It checks the connection and the form of the
reply (a query that `validate` accepts), not the quality of the translation.
"""

from __future__ import annotations

import dataclasses
import os

import pytest

from docreader import llm
from docreader.config import ExtractionSettings, TableSettings, load_settings
from docreader.table_answer import TableOutcome, translate
from docreader.table_query import TableQuery
from tests.synthetic import record_table_answers

pytestmark = pytest.mark.real_model

VARIANTS = record_table_answers.load_variants(
    record_table_answers.SYNTHETIC_DIR / record_table_answers.QUESTIONS_FILE
)


def _settings() -> ExtractionSettings:
    if os.environ.get("DOCREADER_DATA_DIR"):
        settings = load_settings()
        extraction, table = settings.extraction, settings.table
    else:
        extraction, table = ExtractionSettings(), TableSettings()
    return dataclasses.replace(
        extraction, max_tokens=table.max_tokens, max_retries=table.max_retries
    )


@pytest.fixture
def client() -> llm.ModelClient:
    client = llm.load_client(_settings())
    client.check()
    return client


@pytest.mark.parametrize("name", ["with_vat_list", "customer_count", "end_this_year"])
def test_question_gives_a_valid_query(client: llm.ModelClient, name: str) -> None:
    variant = VARIANTS[name]
    assert variant.expected is not None
    translation = translate(client, variant.question, record_table_answers.TODAY)
    assert translation.outcome == TableOutcome.ANSWERED, translation.reason
    query = translation.parsed
    assert isinstance(query, TableQuery)
    assert query.field == variant.expected["field"]
    assert query.action == variant.expected["action"]
