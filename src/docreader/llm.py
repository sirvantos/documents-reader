"""The language model client (feature 05, research R-1; contracts/model.md).

The only module that imports `openai` and `instructor`. The model is reached through an
OpenAI-compatible server on this machine; the code knows only its address.

Guards (critical, CLAUDE.md «Model routing»):

- DOCREADER_FORBID_MODELS set → no real transport (the development server, Docker, the
  test suite); a fake transport from tests/fakes/llm.py is still accepted;
- the address is checked to be on this machine (principle I), with the same function
  as `[extraction] base_url` in settings.toml;
- the address and the key are passed explicitly, so OPENAI_* environment variables are
  not used; openai's own network retries are off (a stopped server stops the command
  at once instead of retrying for minutes);
- the loggers of `instructor` and `openai` are silenced: their messages can carry the
  model's answer and the contract text (FR-015).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, TypeVar

import httpx2
import instructor
import openai
from pydantic import BaseModel

from docreader.config import ExtractionSettings, is_local_model_url
from docreader.errors import EnvironmentProblem
from docreader.guards import FORBID_MODELS_ENV, models_forbidden

__all__ = [
    "AnswerFormError",
    "ModelClient",
    "ModelRequestError",
    "ModelUnavailable",
    "is_local_model_url",
    "load_client",
]

_MODES = {
    "md_json": instructor.Mode.MD_JSON,
    "json": instructor.Mode.JSON,
    "json_schema": instructor.Mode.JSON_SCHEMA,
}
_SILENCED_LOGGERS = (
    "instructor", "instructor.v2", "instructor.v2.retry", "openai", "httpx", "httpx2",
)

M = TypeVar("M", bound=BaseModel)


class ModelUnavailable(EnvironmentProblem):
    """The model server did not answer: not started, gone, or too slow. The run stops."""


class AnswerFormError(Exception):
    """The answer did not fit the schema after all retries; the document fails."""

    def __init__(self, attempts: int) -> None:
        super().__init__(f"ответ модели не по форме после {attempts} попыток")
        self.attempts = attempts


class ModelRequestError(Exception):
    """The server answered with an HTTP error (for example a request too long for its
    window); one document fails, the run goes on (research R-10)."""

    def __init__(self, status: int) -> None:
        super().__init__(f"сервер модели отклонил запрос: HTTP {status}")
        self.status = status


def _silence_loggers() -> None:
    for name in _SILENCED_LOGGERS:
        logger = logging.getLogger(name)
        logger.setLevel(logging.CRITICAL + 1)
        logger.propagate = False


def _causes(exc: BaseException) -> list[BaseException]:
    """`exc` and everything it was raised from, outermost first."""
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


class ModelClient:
    """A connection to the model server with the settings of one `extract` command."""

    def __init__(self, settings: ExtractionSettings, client: openai.OpenAI) -> None:
        self.settings = settings
        self._openai = client
        self._instructor = instructor.from_openai(client, mode=_MODES[settings.mode])

    def _unavailable(self) -> ModelUnavailable:
        return ModelUnavailable(
            f"Модель недоступна по адресу {self.settings.base_url} — запустите сервер модели"
        )

    def _translate(self, exc: BaseException) -> Exception:
        for cause in _causes(exc):
            if isinstance(cause, openai.APITimeoutError):
                return ModelUnavailable(
                    f"модель не ответила (тайм-аут {self.settings.timeout_s} с)"
                )
            if isinstance(cause, openai.APIConnectionError):
                return self._unavailable()
            if isinstance(cause, openai.APIStatusError):
                return ModelRequestError(cause.status_code)
        attempts = getattr(exc, "n_attempts", None)
        return AnswerFormError(int(attempts) if attempts else self.settings.max_retries + 1)

    def check(self) -> str:
        """The id of the model the server serves: `settings.model` if listed, else the first."""
        try:
            ids = [m.id for m in self._openai.models.list()]
        except (openai.APIConnectionError, openai.APIStatusError) as exc:
            raise self._unavailable() from exc
        if self.settings.model in ids:
            return self.settings.model
        return ids[0] if ids else self.settings.model

    def extract(self, messages: Sequence[dict[str, Any]], response_model: type[M]) -> M:
        """The answer to `messages` as `response_model`, retried while it does not fit.

        Raises AnswerFormError (wrong form after retries), ModelRequestError (HTTP error
        answer) or ModelUnavailable (no answer). No message carries the model's text.
        """
        try:
            return self._instructor.chat.completions.create(
                model=self.settings.model,
                response_model=response_model,
                messages=list(messages),  # type: ignore[arg-type]  # plain role/content dicts
                max_retries=self.settings.max_retries,
                temperature=self.settings.temperature,
                seed=self.settings.seed,
                max_tokens=self.settings.max_tokens,
                extra_body=dict(self.settings.extra_body) or None,
            )
        except Exception as exc:  # every failure of the call is translated, nothing leaks
            raise self._translate(exc) from None


def load_client(
    settings: ExtractionSettings, transport: httpx2.BaseTransport | None = None
) -> ModelClient:
    """A client for the model server of `settings`, or EnvironmentProblem.

    `transport` replaces the network (tests); without it the real network transport is
    used, which DOCREADER_FORBID_MODELS forbids.
    """
    if not is_local_model_url(settings.base_url):
        raise EnvironmentProblem(
            f"Адрес модели {settings.base_url!r} не на этой машине — укажите в "
            "[extraction] base_url адрес localhost, 127.0.0.1 или ::1 (принцип I)"
        )
    if transport is None and models_forbidden():
        raise EnvironmentProblem(
            f"На этой машине языковая модель не запускается ({FORBID_MODELS_ENV})"
        )
    _silence_loggers()
    client = openai.OpenAI(
        base_url=settings.base_url,
        api_key="local",
        max_retries=0,
        timeout=float(settings.timeout_s),
        http_client=httpx2.Client(transport=transport) if transport is not None else None,
    )
    return ModelClient(settings, client)
