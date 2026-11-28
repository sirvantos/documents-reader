"""The recording command of feature 10 records only synthetic questions (task T018).

Principle I, guard in code (tech-context «Модели в автотестах»): the questions file must
lie inside tests/synthetic/ (checked before the model is touched); the model address only
on this machine; no real model on a machine with DOCREADER_FORBID_MODELS. No database and
no contracts: each variant goes through `table_answer.translate` with today fixed at
2026-11-28 (research R-11). Written by the main session; not to be edited by the
implementer.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from docreader import llm, table_prompt
from docreader.table_prompt import ACTIONS, FIELD_OPS
from tests.fakes.llm import RecordedModel, ScriptedModel
from tests.integration.table_fixtures import reply
from tests.synthetic import make_pdfs, record_table_answers

REFUSED = "записываются только синтетические файлы из tests/synthetic/"
QUESTIONS = Path(make_pdfs.__file__).resolve().parent / "table_questions.toml"


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    d = tmp_path / "synthetic"
    d.mkdir()
    (d / "table_questions.toml").write_text(
        '[[variant]]\nname = "one"\nquestion = "Сколько договоров?"\n'
        'expected = {action = "count", field = "amount_with_vat", op = "gt", value = "0"}\n',
        encoding="utf-8",
    )
    return d


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"load_client": 0, "record": 0}

    def count(name):
        def spy(*args, **kwargs):
            calls[name] += 1
            raise AssertionError(f"{name} must not be called")

        return spy

    monkeypatch.setattr(llm, "load_client", count("load_client"))
    monkeypatch.setattr(record_table_answers, "record", count("record"))
    return calls


def test_defaults() -> None:
    assert record_table_answers.SYNTHETIC_DIR == QUESTIONS.parent
    assert record_table_answers.RECORDINGS_DIR.parts[-2:] == ("recordings", "10-table-answers")
    assert record_table_answers.TODAY.isoformat() == "2026-11-28"


def test_questions_outside_synthetic_refused(tmp_path, synthetic, spies, capsys) -> None:
    elsewhere = tmp_path / "questions.toml"
    elsewhere.write_text((synthetic / "table_questions.toml").read_text(), encoding="utf-8")
    code = record_table_answers.main(["--questions", str(elsewhere)], synthetic_dir=synthetic,
                                     env={})
    assert code == 1
    assert REFUSED in capsys.readouterr().err
    assert spies == {"load_client": 0, "record": 0}


def test_questions_escaping_with_dots_refused(synthetic, spies, capsys) -> None:
    path = synthetic / ".." / "table_questions.toml"
    code = record_table_answers.main(["--questions", str(path)], synthetic_dir=synthetic, env={})
    assert code == 1
    assert REFUSED in capsys.readouterr().err


def test_symlink_out_of_synthetic_refused(tmp_path, synthetic, spies, capsys) -> None:
    target = tmp_path / "real.toml"
    target.write_text((synthetic / "table_questions.toml").read_text(), encoding="utf-8")
    link = synthetic / "link.toml"
    link.symlink_to(target)
    code = record_table_answers.main(["--questions", str(link)], synthetic_dir=synthetic, env={})
    assert code == 1
    assert REFUSED in capsys.readouterr().err


def test_non_loopback_model_address_refused(synthetic, spies, capsys) -> None:
    code = record_table_answers.main(
        [], synthetic_dir=synthetic, env={"DOCREADER_RECORD_BASE_URL": "http://10.0.0.5:8080/v1"}
    )
    assert code == 2
    assert "принцип I" in capsys.readouterr().err
    assert spies["record"] == 0


def test_forbidden_machine_without_a_transport_refused(synthetic, spies, capsys) -> None:
    code = record_table_answers.main([], synthetic_dir=synthetic,
                                     env={"DOCREADER_FORBID_MODELS": "1"})
    assert code == 2
    assert "DOCREADER_FORBID_MODELS" in capsys.readouterr().err
    assert spies["record"] == 0


def test_no_test_database_needed(synthetic, tmp_path, capsys) -> None:
    model = ScriptedModel(reply(action="count", field="amount_with_vat", op="gt", value="0"))
    code = record_table_answers.main(
        [], synthetic_dir=synthetic, recordings_dir=tmp_path / "rec", env={},
        transport_factory=lambda: model.transport,
    )
    assert code == 0, capsys.readouterr().err
    assert (tmp_path / "rec" / "one.json").is_file()


def test_unknown_variant_refused(synthetic, spies) -> None:
    with pytest.raises(SystemExit):
        record_table_answers.main(["nonsense"], synthetic_dir=synthetic, env={})
    assert spies["record"] == 0


def test_recording_written_and_replayable(synthetic, tmp_path) -> None:
    model = ScriptedModel(reply(action="list", field="price", op="gt", value="0"),
                          reply(action="count", field="amount_with_vat", op="gt", value="0"))
    code = record_table_answers.main(
        ["one", "--quantization", "4 бита", "--server", "mlx_lm.server 0.32.2"],
        synthetic_dir=synthetic, recordings_dir=tmp_path / "rec", env={},
        transport_factory=lambda: model.transport,
    )
    assert code == 0
    assert len(model.requests) == 2  # the retry is recorded too
    assert "2026-11-28" in model.requests[0]["messages"][0]["content"]
    data = json.loads((tmp_path / "rec" / "one.json").read_text(encoding="utf-8"))
    assert data["variant"] == "one"
    assert data["prompt_version"] == table_prompt.PROMPT_VERSION
    assert data["prompt_sha256"] == table_prompt.prompt_sha256()
    assert data["generator_version"] == record_table_answers.QUESTIONS_VERSION
    assert data["today"] == "2026-11-28"
    assert (data["quantization"], data["server"]) == ("4 бита", "mlx_lm.server 0.32.2")
    assert len(data["exchanges"]) == 2
    replay = RecordedModel(
        "one", prompt_version=table_prompt.PROMPT_VERSION,
        prompt_sha256=table_prompt.prompt_sha256(),
        generator_version=record_table_answers.QUESTIONS_VERSION,
        recordings_dir=tmp_path / "rec",
    )
    assert replay.recording["exchanges"] == data["exchanges"]


# --- the synthetic questions (contracts/model.md «Записи уровня 2») -------------------


def _variants() -> list[dict]:
    return tomllib.loads(QUESTIONS.read_text(encoding="utf-8"))["variant"]


def test_questions_file_is_well_formed() -> None:
    variants = _variants()
    names = [v["name"] for v in variants]
    assert len(names) == len(set(names)) and len(names) >= 12
    for v in variants:
        assert v["question"].strip(), v["name"]
        assert ("expected" in v) != ("expected_outcome" in v), v["name"]
        if "expected" in v:
            e = v["expected"]
            assert e["action"] in ACTIONS and e["field"] in FIELD_OPS, v["name"]
            assert e["op"] in FIELD_OPS[e["field"]], v["name"]
        else:
            assert v["expected_outcome"] in {"refused", "clarify", "unsupported"}, v["name"]


def test_questions_cover_the_contract() -> None:
    variants = _variants()
    queries = [v["expected"] for v in variants if "expected" in v]
    assert {q["field"] for q in queries} == set(FIELD_OPS)  # six fields and party
    assert {q["action"] for q in queries} == set(ACTIONS)
    assert {v["expected_outcome"] for v in variants if "expected_outcome" in v} == {
        "refused", "clarify", "unsupported"}
    assert any(q["value"] in table_prompt.PERIODS for q in queries)  # a period
    assert any(v.get("expected_other") for v in variants)  # two requests in one question
    assert any("конца квартала" in v["question"] for v in variants)  # a single date


def test_every_expected_query_is_valid() -> None:
    from docreader import table_query
    from docreader.table_prompt import TableReply

    for v in record_table_answers.load_variants(QUESTIONS).values():
        for expected in ([v.expected] if v.expected else []) + list(v.alternatives):
            got = table_query.validate(TableReply.model_validate({"kind": "query", **expected}),
                                       record_table_answers.TODAY)
            assert isinstance(got, table_query.TableQuery), (v.name, got)
