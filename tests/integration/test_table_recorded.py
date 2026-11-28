"""Level 2: `table_answer.translate` on the real model's recorded replies (feature 10, T025).

The recordings in `tests/recordings/10-table-answers/` were made on the analyst's Mac by
`python -m tests.synthetic.record_table_answers` on the synthetic questions of
`tests/synthetic/table_questions.toml` (today fixed at 2026-11-28, default settings), so
the requests here are the recorded ones. No database and no contracts (research R-11). A
missing or stale recording fails with `StaleRecording` (no skip). A variant the real model
gets wrong is a finding: never edit the recording or loosen the test — change the prompt
(`PROMPT_VERSION`) or the questions (`QUESTIONS_VERSION`) and re-record. Written by the
main session.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from docreader import llm, table_prompt
from docreader import table_query as tq
from docreader.table_answer import TableOutcome, Translation, translate
from tests.fakes.llm import RecordedModel
from tests.synthetic import record_table_answers as rta

VARIANTS = rta.load_variants(rta.SYNTHETIC_DIR / rta.QUESTIONS_FILE)
NAME_FIELDS = {"customer_name_short", "contractor_name_short", "party"}


def _translate(variant: str) -> Translation:
    model = RecordedModel(
        variant,
        prompt_version=table_prompt.PROMPT_VERSION,
        prompt_sha256=table_prompt.prompt_sha256(),
        generator_version=rta.QUESTIONS_VERSION,
        recordings_dir=rta.RECORDINGS_DIR,
        rerecord=rta.RERECORD,
    )
    client = llm.load_client(rta.model_settings(), model.transport)
    client.check()
    got = translate(client, VARIANTS[variant].question, rta.TODAY)
    model.assert_fresh()
    return got


def _query(expected: dict) -> tq.TableQuery:
    got = tq.validate(table_prompt.TableReply.model_validate({"kind": "query", **expected}),
                      rta.TODAY)
    assert isinstance(got, tq.TableQuery)
    return got


def _same(a: tq.TableQuery, b: tq.TableQuery) -> bool:
    if (a.action, a.field, a.op, a.value_to) != (b.action, b.field, b.op, b.value_to):
        return False
    if a.field in NAME_FIELDS:
        return tq.match_names(str(a.value), str(b.value)) and tq.match_names(
            str(b.value), str(a.value))
    if isinstance(a.value, Decimal) or isinstance(b.value, Decimal):
        return Decimal(str(a.value)) == Decimal(str(b.value))
    return a.value == b.value


def test_every_variant_has_a_recording() -> None:
    assert sorted(p.stem for p in rta.RECORDINGS_DIR.glob("*.json")) == sorted(VARIANTS)


@pytest.mark.parametrize("variant", [v for v in VARIANTS if VARIANTS[v].expected])
def test_query_variants(variant: str) -> None:
    v = VARIANTS[variant]
    got = _translate(variant)
    assert got.outcome is TableOutcome.ANSWERED, (got.outcome, got.reason)
    assert isinstance(got.parsed, tq.TableQuery)
    assert v.expected is not None
    accepted = [_query(v.expected), *(_query(a) for a in v.alternatives)]
    assert any(_same(got.parsed, q) for q in accepted), got.parsed
    if v.expected_other:
        assert got.parsed.other


@pytest.mark.parametrize("variant", [v for v in VARIANTS if VARIANTS[v].expected_outcome])
def test_outcome_variants(variant: str) -> None:
    got = _translate(variant)
    assert got.outcome.value == VARIANTS[variant].expected_outcome, (got.outcome, got.parsed)
    assert got.reason
