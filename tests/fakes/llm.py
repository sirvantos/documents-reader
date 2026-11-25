"""Fake language models: HTTP transports for the `openai` client (feature 05, research R-2).

Only the transport is replaced, so the real `openai` client and Instructor run in tests
(answer parsing, retries) and no socket is opened. `llm.load_client(settings, transport)`
takes them (contracts/model.md).

- `ScriptedModel` — answers written in the test (level 1).
- `RecordedModel` — answers recorded from the real model on synthetic contracts by
  `python -m tests.synthetic.record_extraction` (feature 05) or
  `python -m tests.synthetic.record_answers` (feature 09) (level 2). Never edited by hand.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx2

REPO_ROOT = Path(__file__).resolve().parents[2]
RECORDINGS_DIR = REPO_ROOT / "tests" / "recordings" / "05-field-extraction"
RERECORD = "uv run python -m tests.synthetic.record_extraction"
FAKE_MODEL_ID = "fake-model"
# Fields of a chat request that decide the answer (contracts/model.md); `openai` sends the
# keys of `extra_body` at the top level of the body, so the rest is gathered back into it.
_BODY_KEYS = ("messages", "model", "temperature", "seed", "max_tokens")


class StaleRecording(AssertionError):
    """A recording does not match the code: re-record it on the analyst's Mac."""

    def __init__(self, variant: str, detail: str, rerecord: str = RERECORD) -> None:
        super().__init__(
            f"запись {variant} устарела: перезапишите ответы на ноутбуке — {rerecord} ({detail})"
        )


def request_sha256(body: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON of the request fields that decide the answer."""
    extra = {k: v for k, v in body.items() if k not in _BODY_KEYS and k != "extra_body"}
    extra.update(body.get("extra_body") or {})
    canonical: dict[str, Any] = {k: body.get(k) for k in _BODY_KEYS}
    canonical["extra_body"] = extra
    text = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def completion_body(content: str, model: str = FAKE_MODEL_ID) -> dict[str, Any]:
    """An OpenAI chat completion response carrying `content`."""
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": content},
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _models_body(model_id: str) -> dict[str, Any]:
    return {"object": "list", "data": [{"id": model_id, "object": "model", "owned_by": "local"}]}


class ScriptedModel:
    """Answers written in the test, in order.

    `answers` items: a string — the content of the next chat answer; an `httpx` exception
    (`httpx2.ConnectError(...)`, `httpx2.ReadTimeout(...)`) — raised instead of answering;
    an `httpx2.Response` — returned as is (for example an HTTP 400 of the server).
    `models_error` makes `GET /models` raise it (model server down before the run).
    """

    def __init__(
        self,
        *answers: str | Exception | httpx2.Response,
        models_error: Exception | None = None,
    ) -> None:
        self._answers = list(answers)
        self._models_error = models_error
        self.requests: list[dict[str, Any]] = []
        self.urls: list[str] = []
        self.transport = httpx2.MockTransport(self._handle)

    def add(self, *answers: str | Exception | httpx2.Response) -> None:
        self._answers.extend(answers)

    @property
    def remaining(self) -> int:
        return len(self._answers)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.urls.append(str(request.url))
        if request.method == "GET" and request.url.path.endswith("/models"):
            if self._models_error is not None:
                raise self._models_error
            return httpx2.Response(200, json=_models_body(FAKE_MODEL_ID))
        if request.method == "POST" and request.url.path.endswith("/chat/completions"):
            self.requests.append(json.loads(request.content))
            if not self._answers:
                # a 500, not an exception: openai would turn an exception into a connection
                # error and hide that the test gave too few answers
                return httpx2.Response(500, json={"error": "ScriptedModel: no answers left"})
            answer = self._answers.pop(0)
            if isinstance(answer, httpx2.Response):
                return answer
            if isinstance(answer, Exception):
                raise answer
            return httpx2.Response(200, json=completion_body(answer))
        return httpx2.Response(404, json={"error": f"unexpected {request.method} {request.url}"})


def load_recording(
    variant: str, recordings_dir: Path = RECORDINGS_DIR, rerecord: str = RERECORD
) -> dict[str, Any]:
    path = recordings_dir / f"{variant}.json"
    if not path.is_file():
        raise StaleRecording(variant, f"нет файла {path.name}", rerecord)
    return json.loads(path.read_text(encoding="utf-8"))


class RecordedModel:
    """Answers recorded from the real model, looked up by the SHA-256 of the request.

    The recording is checked when the fake is made: a different prompt version, prompt
    fingerprint or generator version raises `StaleRecording` at once. A request whose
    fingerprint is not in the recording gets an HTTP 500 (an exception inside the
    transport would be turned into a connection error by `openai`) and is kept in
    `unknown_requests`; `assert_fresh()` raises `StaleRecording` for it after the run.
    """

    def __init__(
        self,
        variant: str,
        *,
        prompt_version: str | None = None,
        prompt_sha256: str | None = None,
        generator_version: int | None = None,
        recordings_dir: Path = RECORDINGS_DIR,
        rerecord: str = RERECORD,
    ) -> None:
        if prompt_version is None or prompt_sha256 is None:
            from docreader import extraction_prompt

            prompt_version = prompt_version or extraction_prompt.PROMPT_VERSION
            prompt_sha256 = prompt_sha256 or extraction_prompt.prompt_sha256()
        if generator_version is None:
            from tests.synthetic.make_pdfs import GENERATOR_VERSION

            generator_version = GENERATOR_VERSION
        self.variant = variant
        self.rerecord = rerecord
        self.recording = load_recording(variant, recordings_dir, rerecord)
        for key, expected in (
            ("prompt_version", prompt_version),
            ("prompt_sha256", prompt_sha256),
            ("generator_version", generator_version),
        ):
            if self.recording.get(key) != expected:
                raise StaleRecording(
                    variant,
                    f"{key}: в записи {self.recording.get(key)!r}, в коде {expected!r}",
                    rerecord,
                )
        self._by_request: dict[str, list[dict[str, Any]]] = {}
        for exchange in sorted(self.recording["exchanges"], key=lambda e: e["attempt"]):
            self._by_request.setdefault(exchange["request_sha256"], []).append(
                exchange["response"]
            )
        self.unknown_requests: list[str] = []
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET" and request.url.path.endswith("/models"):
            return httpx2.Response(200, json=_models_body(self.recording.get("served_model", "")))
        digest = request_sha256(json.loads(request.content))
        answers = self._by_request.get(digest)
        if not answers:
            self.unknown_requests.append(digest)
            return httpx2.Response(500, json={"error": "RecordedModel: request not recorded"})
        return httpx2.Response(200, json=answers.pop(0))

    def assert_fresh(self) -> None:
        if self.unknown_requests:
            raise StaleRecording(
                self.variant,
                f"запросов нет в записи: {len(self.unknown_requests)}",
                self.rerecord,
            )


def write_recording(path: Path, recording: dict[str, Any]) -> None:
    """Write a recording file (the record command, and tests that build one in tmp_path)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recording, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def exchanges_for(body: dict[str, Any], responses: Iterable[dict[str, Any]]) -> list[dict]:
    """Exchanges of one request answered by `responses` in attempt order (test helper)."""
    digest = request_sha256(body)
    return [
        {"request_sha256": digest, "attempt": n, "response": r}
        for n, r in enumerate(responses, start=1)
    ]
