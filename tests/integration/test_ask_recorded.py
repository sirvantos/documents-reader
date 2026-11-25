"""Level 2: `answer.ask` on the real model's recorded answers (feature 09; task T019).

The recordings in `tests/recordings/09-text-answers/` were made on the analyst's Mac by
`python -m tests.synthetic.record_answers` on the synthetic contracts of
`make_answer_contracts`; the search fakes and passage counts come from `answer_fixtures.py`,
so the request to the model is the one recorded. A missing or stale recording fails with
`StaleRecording` (no skip). A variant the real model gets wrong is a finding: never edit the
recording or loosen the test — change the prompt (`PROMPT_VERSION`) or the variant
(`ANSWER_GENERATOR_VERSION`) and re-record. Written by the main session.
"""

from __future__ import annotations

import pytest

from docreader import answer, answer_prompt
from docreader.config import load_settings
from tests.fakes.llm import RecordedModel, StaleRecording
from tests.fakes.reranker import TableReranker
from tests.integration.answer_fixtures import (
    ANSWER_SCORES,
    ANSWER_VARIANTS,
    index_answer_contracts,
)
from tests.synthetic import make_pdfs
from tests.synthetic.record_answers import RECORDINGS_DIR

RERECORD = "uv run python -m tests.synthetic.record_answers"


def recorded(variant: str, **overrides) -> RecordedModel:
    kwargs = {
        "prompt_version": answer_prompt.PROMPT_VERSION,
        "prompt_sha256": answer_prompt.prompt_sha256(),
        "generator_version": make_pdfs.ANSWER_GENERATOR_VERSION,
        "recordings_dir": RECORDINGS_DIR,
        "rerecord": RERECORD,
        **overrides,
    }
    return RecordedModel(variant, **kwargs)


@pytest.fixture
def indexed(cli, tmp_path, use_embedder, use_reranker) -> None:
    index_answer_contracts(cli, tmp_path, use_embedder)
    use_reranker(TableReranker(ANSWER_SCORES))


def _ask(db, use_model, variant: str) -> answer.Answer:
    model = use_model(recorded(variant))
    v = ANSWER_VARIANTS[variant]
    result = answer.ask(db, load_settings(), v.question, document_id=v.document,
                        passages=v.passages)
    model.assert_fresh()
    return result


def test_payment_is_answered_from_clause_2_2(db, indexed, use_model) -> None:
    result = _ask(db, use_model, "payment")
    assert result.outcome == answer.AnswerOutcome.ANSWERED
    assert "D-0001/2.2" in {c.clause_id for c in result.claims if c.confirmed}


def test_parties_are_answered_from_the_preamble_added_by_rule(db, indexed, use_model) -> None:
    result = _ask(db, use_model, "parties")
    assert result.outcome == answer.AnswerOutcome.ANSWERED
    preamble = [p for p in result.shown if p.clause_id == "D-0001/преамбула"]
    assert preamble and preamble[0].added_by_rule
    assert "D-0001/преамбула" in {c.clause_id for c in result.claims if c.confirmed}


def test_absent_is_not_found(db, indexed, use_model) -> None:
    result = _ask(db, use_model, "absent")
    assert result.outcome == answer.AnswerOutcome.NOT_FOUND
    assert result.claims == []


def test_every_variant_has_a_recording() -> None:
    assert sorted(p.stem for p in RECORDINGS_DIR.glob("*.json")) == sorted(ANSWER_VARIANTS)


def test_missing_recording_names_the_answer_command(tmp_path) -> None:
    with pytest.raises(StaleRecording, match="record_answers"):
        recorded("payment", recordings_dir=tmp_path)


def test_stale_prompt_version_names_the_answer_command() -> None:
    with pytest.raises(StaleRecording, match=r"record_answers.*prompt_version"):
        recorded("payment", prompt_version="0.0")
