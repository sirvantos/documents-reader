"""The language model client and its guards (feature 05, contracts/model.md; task T007).

Only the HTTP transport is fake (`tests/fakes/llm.py`); the real `openai` client and
Instructor run. Critical part (CLAUDE.md «Model routing»): the model never starts on
this server (DOCREADER_FORBID_MODELS), is reached only on this machine (principle I),
and no model text reaches the logs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx2
import pytest
from pydantic import BaseModel

from docreader import llm
from docreader.config import ExtractionSettings
from docreader.errors import EnvironmentProblem
from tests.fakes.llm import (
    FAKE_MODEL_ID,
    RecordedModel,
    ScriptedModel,
    StaleRecording,
    completion_body,
    exchanges_for,
    request_sha256,
    write_recording,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "docreader"
MESSAGES = [{"role": "user", "content": "текст договора"}]


class Probe(BaseModel):
    """A minimal response model; the real schema comes from extraction_prompt (T015)."""

    x: int


def settings(**overrides) -> ExtractionSettings:
    return ExtractionSettings(**overrides)


def _no_client(*args, **kwargs):
    raise AssertionError("the openai client must not be created")


# --- DOCREADER_FORBID_MODELS (set by the autouse fixture in every test here) -------------


def test_forbidden_without_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm.openai, "OpenAI", _no_client)
    with pytest.raises(EnvironmentProblem) as exc:
        llm.load_client(settings())
    assert str(exc.value) == (
        "На этой машине языковая модель не запускается (DOCREADER_FORBID_MODELS)"
    )


def test_fake_transport_allowed_while_forbidden() -> None:
    model = ScriptedModel('{"x": 1}')
    client = llm.load_client(settings(), transport=model.transport)
    assert client.extract(MESSAGES, Probe).model_dump() == {"x": 1}


def test_real_transport_allowed_when_not_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCREADER_FORBID_MODELS")
    client = llm.load_client(settings())  # no request is sent here
    assert isinstance(client, llm.ModelClient)


# --- only this machine (principle I) ----------------------------------------------------


@pytest.mark.parametrize("url", ["http://10.0.0.5:8080/v1", "https://api.openai.com/v1"])
@pytest.mark.parametrize("with_transport", [False, True])
def test_non_local_url_refused(
    monkeypatch: pytest.MonkeyPatch, url: str, with_transport: bool
) -> None:
    monkeypatch.delenv("DOCREADER_FORBID_MODELS")
    monkeypatch.setattr(llm.openai, "OpenAI", _no_client)
    transport = ScriptedModel().transport if with_transport else None
    with pytest.raises(EnvironmentProblem, match=r"\[extraction\] base_url"):
        llm.load_client(settings(base_url=url), transport=transport)


def test_load_client_uses_the_config_check() -> None:
    from docreader import config

    assert llm.is_local_model_url is config.is_local_model_url


def test_openai_environment_does_not_change_the_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://10.9.9.9:1/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-looking")
    model = ScriptedModel('{"x": 1}')
    llm.load_client(settings(), transport=model.transport).extract(MESSAGES, Probe)
    assert model.urls == ["http://127.0.0.1:8080/v1/chat/completions"]


# --- check(): the server before the first document ----------------------------------------


def test_check_returns_served_id() -> None:
    model = ScriptedModel()
    assert llm.load_client(settings(), transport=model.transport).check() == FAKE_MODEL_ID


def test_check_when_server_is_down() -> None:
    model = ScriptedModel(models_error=httpx2.ConnectError("refused"))
    client = llm.load_client(settings(), transport=model.transport)
    with pytest.raises(llm.ModelUnavailable) as exc:
        client.check()
    assert isinstance(exc.value, EnvironmentProblem)
    assert str(exc.value) == (
        "Модель недоступна по адресу http://127.0.0.1:8080/v1 — запустите сервер модели"
    )


# --- extract(): parameters, retries, errors ----------------------------------------------


def test_request_parameters_come_from_settings() -> None:
    model = ScriptedModel('{"x": 1}')
    s = settings(
        model="m-27b", temperature=0.0, seed=7, max_tokens=512,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    llm.load_client(s, transport=model.transport).extract(MESSAGES, Probe)
    (body,) = model.requests
    assert body["model"] == "m-27b"
    assert (body["temperature"], body["seed"], body["max_tokens"]) == (0.0, 7, 512)
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    # md_json appends its JSON instruction to the last user message; ours comes first
    assert body["messages"][-1]["role"] == "user"
    assert body["messages"][-1]["content"].startswith(MESSAGES[-1]["content"])


def test_answer_in_a_code_block_is_parsed() -> None:
    model = ScriptedModel('```json\n{"x": 3}\n```')
    assert llm.load_client(settings(), transport=model.transport).extract(MESSAGES, Probe).x == 3


def test_one_retry_after_a_bad_answer() -> None:
    model = ScriptedModel("не JSON", '{"x": 2}')
    client = llm.load_client(settings(), transport=model.transport)
    assert client.extract(MESSAGES, Probe).model_dump() == {"x": 2}
    assert len(model.requests) == 2


def test_answer_not_in_form_after_retries() -> None:
    model = ScriptedModel("плохо", "плохо", "плохо", '{"x": 9}')
    client = llm.load_client(settings(max_retries=2), transport=model.transport)
    with pytest.raises(llm.AnswerFormError) as exc:
        client.extract(MESSAGES, Probe)
    assert exc.value.attempts == 3
    assert len(model.requests) == 3
    assert model.remaining == 1


def test_no_retries_setting() -> None:
    model = ScriptedModel("плохо", '{"x": 9}')
    client = llm.load_client(settings(max_retries=0), transport=model.transport)
    with pytest.raises(llm.AnswerFormError) as exc:
        client.extract(MESSAGES, Probe)
    assert exc.value.attempts == 1


def test_connection_lost_during_extract() -> None:
    model = ScriptedModel(httpx2.ConnectError("reset"))
    client = llm.load_client(settings(), transport=model.transport)
    with pytest.raises(llm.ModelUnavailable, match="Модель недоступна по адресу"):
        client.extract(MESSAGES, Probe)
    assert len(model.requests) == 1  # openai's own network retries are off


def test_timeout_during_extract() -> None:
    model = ScriptedModel(httpx2.ReadTimeout("slow"))
    client = llm.load_client(settings(), transport=model.transport)
    with pytest.raises(llm.ModelUnavailable) as exc:
        client.extract(MESSAGES, Probe)
    assert str(exc.value) == "модель не ответила (тайм-аут 1800 с)"
    assert len(model.requests) == 1


def test_server_refuses_the_request() -> None:
    """An HTTP error answer (for example a request longer than the server's window) fails
    one document, it does not stop the run (research R-10)."""
    model = ScriptedModel(httpx2.Response(400, json={"error": "context length exceeded"}))
    client = llm.load_client(settings(), transport=model.transport)
    with pytest.raises(llm.ModelRequestError) as exc:
        client.extract(MESSAGES, Probe)
    assert not isinstance(exc.value, EnvironmentProblem)
    assert exc.value.status == 400
    assert str(exc.value) == "сервер модели отклонил запрос: HTTP 400"
    assert len(model.requests) == 1


def test_no_model_text_in_logs(caplog: pytest.LogCaptureFixture, capsys) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "СЕКРЕТНЫЙ-ТЕКСТ-7731"
    model = ScriptedModel(marker, marker, marker)
    client = llm.load_client(settings(), transport=model.transport)
    with pytest.raises(llm.AnswerFormError) as exc:
        client.extract([{"role": "user", "content": marker}], Probe)
    out, err = capsys.readouterr()
    assert marker not in caplog.text
    assert marker not in out + err
    assert marker not in str(exc.value)


def test_only_llm_imports_openai_and_instructor() -> None:
    pattern = re.compile(r"^\s*(import|from)\s+(openai|instructor)\b", re.MULTILINE)
    offenders = [
        p.name for p in SRC.glob("*.py") if p.name != "llm.py" and pattern.search(p.read_text())
    ]
    assert offenders == []


# --- RecordedModel ------------------------------------------------------------------------

META = {"prompt_version": "05.1", "prompt_sha256": "a" * 64, "generator_version": 1}


def _first_request(s: ExtractionSettings) -> dict:
    """The body the client sends for MESSAGES, captured with a scripted model."""
    model = ScriptedModel('{"x": 0}')
    llm.load_client(s, transport=model.transport).extract(MESSAGES, Probe)
    return model.requests[0]


def _write(tmp_path: Path, body: dict, content: str = '{"x": 5}') -> Path:
    write_recording(
        tmp_path / "base.json",
        {
            "variant": "base",
            **META,
            "model": "qwen",
            "served_model": "qwen-served",
            "exchanges": exchanges_for(body, [completion_body(content)]),
        },
    )
    return tmp_path


def test_recorded_answer_replayed(tmp_path: Path) -> None:
    s = settings()
    recorded = RecordedModel("base", recordings_dir=_write(tmp_path, _first_request(s)), **META)
    client = llm.load_client(s, transport=recorded.transport)
    assert client.check() == "qwen-served"
    assert client.extract(MESSAGES, Probe).model_dump() == {"x": 5}
    recorded.assert_fresh()


@pytest.mark.parametrize(
    "expected",
    [{"prompt_version": "05.2"}, {"prompt_sha256": "b" * 64}, {"generator_version": 2}],
)
def test_stale_recording_refused_at_once(tmp_path: Path, expected: dict) -> None:
    folder = _write(tmp_path, {"messages": []})
    with pytest.raises(StaleRecording) as exc:
        RecordedModel("base", recordings_dir=folder, **{**META, **expected})
    message = str(exc.value)
    assert message.startswith("запись base устарела: перезапишите ответы на ноутбуке — ")
    assert "uv run python -m tests.synthetic.record_extraction" in message


def test_missing_recording_is_stale(tmp_path: Path) -> None:
    with pytest.raises(StaleRecording, match=r"нет файла base\.json"):
        RecordedModel("base", recordings_dir=tmp_path, **META)


def test_unknown_request_is_reported_by_assert_fresh(tmp_path: Path) -> None:
    folder = _write(tmp_path, {"messages": [{"role": "user", "content": "другое"}]})
    recorded = RecordedModel("base", recordings_dir=folder, **META)
    client = llm.load_client(settings(), transport=recorded.transport)
    with pytest.raises(llm.ModelRequestError):
        client.extract(MESSAGES, Probe)
    with pytest.raises(StaleRecording, match="запросов нет в записи: 1"):
        recorded.assert_fresh()


def test_request_sha256_ignores_other_keys_and_folds_extra_body() -> None:
    body = {"messages": [{"role": "user", "content": "a"}], "model": "m", "temperature": 0,
            "seed": 0, "max_tokens": 10, "chat_template_kwargs": {"enable_thinking": False}}
    folded = {k: v for k, v in body.items() if k != "chat_template_kwargs"}
    folded["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    assert request_sha256(body) == request_sha256(folded)
    assert request_sha256({**body, "seed": 1}) != request_sha256(body)
    assert re.fullmatch(r"[0-9a-f]{64}", request_sha256(body))
