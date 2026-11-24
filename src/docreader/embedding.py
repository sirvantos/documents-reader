"""The search model client: texts → vectors (feature 07, research R-1; contracts/embedding.md).

The only module that talks to the search model. It reaches an OpenAI-compatible
`/v1/embeddings` server on this machine (`llama-server` with BGE-M3 on the Mac) through
the `openai` client; the code knows only its address.

Guards (critical, CLAUDE.md «Model routing»), the same as `llm.py`:

- DOCREADER_FORBID_MODELS set → no real transport (the development server, Docker, the
  test suite); a fake transport from tests/fakes/embedding.py is still accepted;
- the address is checked to be on this machine (principle I), with the same function
  as `[embedding] base_url` in settings.toml;
- the address and the key are passed explicitly, so OPENAI_* environment variables are
  not used; openai's own network retries are off;
- no error message carries an input text (it is contract text).
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import httpx2
import openai

from docreader.config import EmbeddingSettings, is_local_model_url
from docreader.errors import EnvironmentProblem, ModelUnavailable
from docreader.guards import FORBID_MODELS_ENV, models_forbidden

__all__ = [
    "Embedder",
    "EmbedderInfo",
    "EmbeddingRequestError",
    "ModelUnavailable",
    "load_embedder",
]

_SILENCED_LOGGERS = ("openai", "httpx", "httpx2")
_PROBE = "проверка"


class EmbeddingRequestError(Exception):
    """The server answered with an HTTP error or not in form; one document fails."""


@dataclass(frozen=True)
class EmbedderInfo:
    served_model: str
    dims: int


class Embedder:
    """A connection to the search model server with the settings of one `index` command."""

    def __init__(self, settings: EmbeddingSettings, client: openai.OpenAI) -> None:
        self.settings = settings
        self._client = client
        self._dims: int | None = None

    def _unavailable(self) -> ModelUnavailable:
        return ModelUnavailable(
            f"Модель поиска недоступна по адресу {self.settings.base_url} — "
            "запустите сервер модели поиска"
        )

    def _request(self, texts: list[str]) -> tuple[str, list[list[float]]]:
        try:
            answer = self._client.embeddings.create(
                model=self.settings.model, input=texts, encoding_format="float"
            )
        except openai.APITimeoutError as exc:
            raise ModelUnavailable(
                f"модель поиска не ответила (тайм-аут {self.settings.timeout_s} с)"
            ) from exc
        except openai.APIConnectionError as exc:
            raise self._unavailable() from exc
        except openai.APIStatusError as exc:
            raise EmbeddingRequestError(
                f"сервер модели поиска отклонил запрос: HTTP {exc.status_code}"
            ) from None
        except Exception:  # a body the client cannot read: not in form, nothing leaks
            raise EmbeddingRequestError("ответ модели поиска не по форме") from None
        items = sorted(answer.data, key=lambda item: item.index)
        if [item.index for item in items] != list(range(len(texts))):
            raise EmbeddingRequestError(
                f"ответ модели поиска не по форме: {len(items)} векторов на {len(texts)} текстов"
            )
        return answer.model, [_unit(list(item.embedding)) for item in items]

    def check(self) -> EmbedderInfo:
        """The model the server serves and its vector length, from one probe vector."""
        served, (vector,) = self._request([_PROBE])
        self._dims = len(vector)
        return EmbedderInfo(served_model=served or self.settings.model, dims=self._dims)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Unit vectors of `texts`, in their order, sent in batches of `batch_size`.

        Raises ValueError (a text longer than `max_chars`: the caller truncates),
        EmbeddingRequestError (an answer not in form) or ModelUnavailable (no answer).
        """
        limit = self.settings.max_chars
        too_long = [i for i, t in enumerate(texts) if len(t) > limit]
        if too_long:
            raise ValueError(
                f"тексты длиннее {limit} знаков (номера {too_long[:5]}) — обрежьте их до вызова"
            )
        vectors: list[list[float]] = []
        size = self.settings.batch_size
        for start in range(0, len(texts), size):
            _, batch = self._request(list(texts[start : start + size]))
            for vector in batch:
                if self._dims is None:
                    self._dims = len(vector)
                if len(vector) != self._dims:
                    raise EmbeddingRequestError(
                        f"ответ модели поиска не по форме: длина вектора {len(vector)}, "
                        f"ожидалось {self._dims}"
                    )
            vectors.extend(batch)
        return vectors


def _unit(vector: list[float]) -> list[float]:
    if not vector or not all(math.isfinite(x) for x in vector):
        raise EmbeddingRequestError("ответ модели поиска не по форме: вектор пуст или не число")
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        raise EmbeddingRequestError("ответ модели поиска не по форме: нулевой вектор")
    return [x / norm for x in vector]


def _silence_loggers() -> None:
    for name in _SILENCED_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


def load_embedder(
    settings: EmbeddingSettings, transport: httpx2.BaseTransport | None = None
) -> Embedder:
    """A client for the search model server of `settings`, or EnvironmentProblem.

    `transport` replaces the network (tests); without it the real network transport is
    used, which DOCREADER_FORBID_MODELS forbids.
    """
    if not is_local_model_url(settings.base_url):
        raise EnvironmentProblem(
            f"Адрес модели поиска {settings.base_url!r} не на этой машине — укажите в "
            "[embedding] base_url адрес localhost, 127.0.0.1 или ::1 (принцип I)"
        )
    if transport is None and models_forbidden():
        raise EnvironmentProblem(
            f"На этой машине модель поиска не запускается ({FORBID_MODELS_ENV})"
        )
    _silence_loggers()
    client = openai.OpenAI(
        base_url=settings.base_url,
        api_key="local",
        max_retries=0,
        timeout=float(settings.timeout_s),
        http_client=httpx2.Client(transport=transport) if transport is not None else None,
    )
    return Embedder(settings, client)
