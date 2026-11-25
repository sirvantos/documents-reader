"""The recording command of feature 09 end to end (task T017).

`ScriptedModel` stands for the real server; the command writes into `tmp_path`, never into
`tests/recordings/`, and its throwaway database is dropped. A written recording is then
replayed with `RecordedModel` through the real pipeline with the same search fakes: the
request fingerprints of the command and of the pipeline must agree (the base of the level 2
test, T019). Written by the main session; the implementer must not edit, weaken, skip or
delete these tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from docreader import answer, answer_prompt
from docreader.config import load_settings
from tests.fakes.llm import RecordedModel, ScriptedModel, request_sha256
from tests.fakes.reranker import TableReranker
from tests.integration.answer_fixtures import (
    ANSWER_SCORES,
    ANSWER_VARIANTS,
    QUOTE_PARTIES,
    QUOTE_PAYMENT,
    index_answer_contracts,
)
from tests.synthetic import make_pdfs, record_answers


def reply(*claims: dict, kind: str = "answer") -> str:
    return json.dumps({"kind": kind, "claims": list(claims)}, ensure_ascii=False)


PAYMENT = reply({"text": "Оплата — 30 дней.", "clause": "D-0001/2.2", "quote": QUOTE_PAYMENT})
PARTIES = reply(
    {"text": "Подрядчик — ООО «Бета».", "clause": "D-0001/преамбула", "quote": QUOTE_PARTIES}
)
ABSENT = reply(kind="not_found")


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    d = tmp_path / "synthetic"
    (d / "out").mkdir(parents=True)
    return d


def _record(variants, synthetic: Path, recordings: Path, database_url: str, model) -> int:
    return record_answers.main(
        [*variants, "--quantization", "4 бита", "--server", "тестовый сервер"],
        synthetic_dir=synthetic,
        recordings_dir=recordings,
        env={"DOCREADER_TEST_DATABASE_URL": database_url},
        transport_factory=lambda: model.transport,
    )


def _record_databases(database_url: str) -> list[str]:
    with psycopg.connect(database_url) as conn:
        return [
            r[0]
            for r in conn.execute(
                "SELECT datname FROM pg_database WHERE datname LIKE 'docreader_record_%'"
            )
        ]


def test_records_every_variant(tmp_path, synthetic, database_url, capsys) -> None:
    recordings = tmp_path / "recordings"
    model = ScriptedModel(PAYMENT, PARTIES, ABSENT)
    assert _record([], synthetic, recordings, database_url, model) == 0

    out = capsys.readouterr().out
    assert sorted(p.name for p in recordings.iterdir()) == [
        "absent.json", "parties.json", "payment.json"
    ]
    for variant in ANSWER_VARIANTS:
        assert f"Записано: {recordings / f'{variant}.json'}" in out
    rec = json.loads((recordings / "payment.json").read_text(encoding="utf-8"))
    assert rec["variant"] == "payment"
    assert rec["generator_version"] == make_pdfs.ANSWER_GENERATOR_VERSION
    assert rec["prompt_version"] == answer_prompt.PROMPT_VERSION
    assert rec["prompt_sha256"] == answer_prompt.prompt_sha256()
    assert rec["model"] == "qwen3.6-27b-4bit" and rec["served_model"] == "fake-model"
    assert (rec["quantization"], rec["server"]) == ("4 бита", "тестовый сервер")
    assert set(rec["settings"]) >= {"mode", "temperature", "seed", "max_tokens", "extra_body"}
    assert rec["recorded_at"]
    (exchange,) = rec["exchanges"]
    assert exchange["request_sha256"] == request_sha256(model.requests[0])
    assert _record_databases(database_url) == []
    # the contracts are written inside the synthetic dir only
    assert sorted(p.name for p in (synthetic / "out").glob("answer-*.pdf")) == [
        "answer-a.pdf", "answer-b.pdf"
    ]


def test_one_variant_only(tmp_path, synthetic, database_url) -> None:
    recordings = tmp_path / "recordings"
    assert _record(["parties"], synthetic, recordings, database_url,
                   ScriptedModel(PARTIES)) == 0
    assert [p.name for p in recordings.iterdir()] == ["parties.json"]


def test_retry_attempts_are_recorded(tmp_path, synthetic, database_url) -> None:
    recordings = tmp_path / "recordings"
    paraphrase = reply({"text": "Оплата.", "clause": "D-0001/2.2", "quote": "пересказ"})
    model = ScriptedModel(paraphrase, json.dumps({"claims": []}))
    assert _record(["payment"], synthetic, recordings, database_url, model) == 0
    rec = json.loads((recordings / "payment.json").read_text(encoding="utf-8"))
    assert [e["attempt"] for e in rec["exchanges"]] == [1, 2]
    assert [e["request_sha256"] for e in rec["exchanges"]] == [
        request_sha256(body) for body in model.requests
    ]


@pytest.mark.parametrize(("variant", "content"), [("payment", PAYMENT), ("parties", PARTIES)])
def test_recording_replays_through_the_pipeline(
    tmp_path, synthetic, database_url, cli, db, use_model, use_embedder, use_reranker,
    variant, content,
) -> None:
    recordings = tmp_path / "recordings"
    assert _record([variant], synthetic, recordings, database_url, ScriptedModel(content)) == 0

    index_answer_contracts(cli, tmp_path / "pipeline", use_embedder)
    use_reranker(TableReranker(ANSWER_SCORES))
    recorded = use_model(
        RecordedModel(
            variant,
            prompt_version=answer_prompt.PROMPT_VERSION,
            prompt_sha256=answer_prompt.prompt_sha256(),
            generator_version=make_pdfs.ANSWER_GENERATOR_VERSION,
            recordings_dir=recordings,
        )
    )
    v = ANSWER_VARIANTS[variant]
    result = answer.ask(db, load_settings(), v.question, document_id=v.document,
                        passages=v.passages)
    recorded.assert_fresh()
    assert result.outcome == "answered"
    assert all(c.confirmed for c in result.claims)
