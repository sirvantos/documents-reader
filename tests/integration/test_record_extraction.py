"""The recording command of feature 05 end to end (task T024, implemented in T025).

`ScriptedModel` stands for the real server; the command writes into `tmp_path`, never into
`tests/recordings/`, and its throwaway database is dropped. The written recording is then
replayed with `RecordedModel` through the real pipeline: the request fingerprints of the
command and of the pipeline must agree. Written by the main session; the implementer must
not edit, weaken, skip or delete these tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from docreader import extraction_prompt
from tests.fakes.llm import RecordedModel, ScriptedModel, request_sha256
from tests.integration.extraction_fixtures import add_variants, answer, field_rows
from tests.synthetic import make_pdfs, record_extraction


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    d = tmp_path / "synthetic"
    (d / "out").mkdir(parents=True)
    return d


def _record(paths, synthetic: Path, recordings: Path, database_url: str, model) -> int:
    return record_extraction.main(
        [*map(str, paths), "--quantization", "4 бита", "--server", "тестовый сервер"],
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


def test_records_one_variant(tmp_path: Path, synthetic: Path, database_url: str, capsys) -> None:
    pdf = make_pdfs.make_extraction_contract(synthetic / "out" / "base.pdf", "base")
    recordings = tmp_path / "recordings"
    model = ScriptedModel(answer())

    assert _record([pdf], synthetic, recordings, database_url, model) == 0

    path = recordings / "base.json"
    assert f"Записано: {path}" in capsys.readouterr().out
    rec = json.loads(path.read_text(encoding="utf-8"))
    assert rec["variant"] == "base"
    assert rec["generator_version"] == make_pdfs.GENERATOR_VERSION
    assert rec["prompt_version"] == extraction_prompt.PROMPT_VERSION
    assert rec["prompt_sha256"] == extraction_prompt.prompt_sha256()
    assert rec["model"] == "qwen3.6-27b-4bit"
    assert rec["served_model"] == "fake-model"
    assert (rec["quantization"], rec["server"]) == ("4 бита", "тестовый сервер")
    assert set(rec["settings"]) >= {"mode", "temperature", "seed", "max_tokens", "extra_body"}
    assert rec["recorded_at"]
    (exchange,) = rec["exchanges"]
    assert exchange["attempt"] == 1
    assert exchange["request_sha256"] == request_sha256(model.requests[0])
    content = exchange["response"]["choices"][0]["message"]["content"]
    assert json.loads(content) == json.loads(answer())
    assert _record_databases(database_url) == []


def test_every_attempt_is_recorded(
    tmp_path: Path, synthetic: Path, database_url: str
) -> None:
    pdf = make_pdfs.make_extraction_contract(synthetic / "out" / "base.pdf", "base")
    recordings = tmp_path / "recordings"
    model = ScriptedModel("не JSON", answer())
    assert _record([pdf], synthetic, recordings, database_url, model) == 0
    rec = json.loads((recordings / "base.json").read_text(encoding="utf-8"))
    assert [e["attempt"] for e in rec["exchanges"]] == [1, 2]
    assert [e["request_sha256"] for e in rec["exchanges"]] == [
        request_sha256(body) for body in model.requests
    ]


def test_two_variants_two_files(tmp_path: Path, synthetic: Path, database_url: str) -> None:
    paths = [
        make_pdfs.make_extraction_contract(synthetic / "out" / f"{v}.pdf", v)
        for v in ("base", "injection")
    ]
    recordings = tmp_path / "recordings"
    assert _record(paths, synthetic, recordings, database_url,
                   ScriptedModel(answer(), answer())) == 0
    assert sorted(p.name for p in recordings.iterdir()) == ["base.json", "injection.json"]


def test_recording_replays_through_the_pipeline(
    tmp_path: Path, synthetic: Path, database_url: str, cli, db, use_model
) -> None:
    pdf = make_pdfs.make_extraction_contract(synthetic / "out" / "base.pdf", "base")
    recordings = tmp_path / "recordings"
    assert _record([pdf], synthetic, recordings, database_url, ScriptedModel(answer())) == 0

    (doc,) = add_variants(cli, tmp_path / "in", "base")
    recorded = use_model(RecordedModel("base", recordings_dir=recordings))
    result = cli("extract")
    assert result.exit_code == 0, result.stderr
    recorded.assert_fresh()
    rows = field_rows(db, doc)
    assert {r["result"] for r in rows.values()} == {"found"}
