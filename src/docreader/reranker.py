"""The reranker client: query, passages → scores (feature 08, research R-7; contracts/reranker.md).

The only module that talks to the reranker. It reaches a `llama-server --reranking`
on this machine (BGE Reranker v2-m3 on the Mac) with `POST {base_url}/rerank` through
`httpx2`; the code knows only its address.

Guards (critical, CLAUDE.md «Model routing»), the same as `embedding.py`:

- DOCREADER_FORBID_MODELS set → no real transport (the development server, Docker, the
  test suite); a fake transport from tests/fakes/reranker.py is still accepted;
- the address is checked to be on this machine (principle I), with the same function
  as `[reranker] base_url` in settings.toml;
- proxy environment variables are ignored (`trust_env=False`); there are no retries;
- no error message carries the query or a document (they are contract text).
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass

import httpx2

from docreader.config import RerankerSettings, is_local_model_url
from docreader.errors import EnvironmentProblem, ModelUnavailable
from docreader.guards import FORBID_MODELS_ENV, models_forbidden

__all__ = [
    "ModelUnavailable",
    "RerankRequestError",
    "Reranker",
    "RerankerInfo",
    "load_reranker",
    "rerank_input",
]

_SILENCED_LOGGERS = ("httpx", "httpx2")
_PROBE = "проверка"
_NOT_IN_FORM = "ответ реранкера не по форме"


class RerankRequestError(Exception):
    """The server answered with an HTTP error or not in form; the search stops."""


@dataclass(frozen=True)
class RerankerInfo:
    served_model: str


def rerank_input(query: str, label: str, text: str, max_chars: int) -> tuple[str, str, bool]:
    """The query and the document of one pair, together at most `max_chars` characters.

    The document is `label + "\\n" + text`. A query longer than `max_chars // 4` is cut
    to it (the flag is then True); the document is cut to what is left.
    """
    limit = max_chars // 4
    cut = len(query) > limit
    if cut:
        query = query[:limit]
    document = f"{label}\n{text}"[: max_chars - len(query)]
    return query, document, cut


class Reranker:
    """A connection to the reranker server with the settings of one search."""

    def __init__(self, settings: RerankerSettings, client: httpx2.Client) -> None:
        self.settings = settings
        self._client = client

    def _post(self, query: str, documents: list[str]) -> object:
        body = {"model": self.settings.model, "query": query, "documents": documents}
        try:
            response = self._client.post("rerank", json=body)
        except httpx2.TimeoutException as exc:
            raise ModelUnavailable(
                f"реранкер не ответил (тайм-аут {self.settings.timeout_s} с)"
            ) from exc
        except httpx2.TransportError as exc:
            raise ModelUnavailable(
                f"Реранкер недоступен по адресу {self.settings.base_url} — запустите его "
                "или выполните поиск с --no-rerank"
            ) from exc
        if response.status_code >= 400:
            raise RerankRequestError(
                f"сервер реранкера отклонил запрос: HTTP {response.status_code}"
            )
        try:
            return json.loads(response.content)
        except (ValueError, UnicodeDecodeError):
            raise RerankRequestError(_NOT_IN_FORM) from None

    def _scores(self, answer: object, n: int) -> tuple[str | None, list[float]]:
        if not isinstance(answer, dict) or not isinstance(answer.get("results"), list):
            raise RerankRequestError(_NOT_IN_FORM)
        results = answer["results"]
        if len(results) != n:
            raise RerankRequestError(f"{_NOT_IN_FORM}: {len(results)} оценок на {n} отрывков")
        scores: list[float | None] = [None] * n
        for item in results:
            if not isinstance(item, dict):
                raise RerankRequestError(_NOT_IN_FORM)
            index, score = item.get("index"), item.get("relevance_score")
            if (
                not isinstance(index, int) or isinstance(index, bool)
                or not 0 <= index < n or scores[index] is not None
            ):
                raise RerankRequestError(f"{_NOT_IN_FORM}: неверный номер отрывка")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise RerankRequestError(f"{_NOT_IN_FORM}: оценка не число")
            if not math.isfinite(score):
                raise RerankRequestError(f"{_NOT_IN_FORM}: оценка не число")
            scores[index] = float(score)
        model = answer.get("model")
        return (model if isinstance(model, str) and model else None), [
            s for s in scores if s is not None
        ]

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """Scores of `documents` for `query`, in the order of `documents`.

        Raises RerankRequestError (HTTP error or an answer not in form) or
        ModelUnavailable (no answer). An empty `documents` sends nothing.
        """
        docs = list(documents)
        if not docs:
            return []
        _, scores = self._scores(self._post(query, docs), len(docs))
        return scores

    def check(self) -> RerankerInfo:
        """The model the server serves, from one probe pair."""
        served, _ = self._scores(self._post(_PROBE, [_PROBE]), 1)
        return RerankerInfo(served_model=served or self.settings.model)


def _silence_loggers() -> None:
    for name in _SILENCED_LOGGERS:
        logging.getLogger(name).setLevel(logging.CRITICAL)


def load_reranker(
    settings: RerankerSettings, transport: httpx2.BaseTransport | None = None
) -> Reranker:
    """A client for the reranker server of `settings`, or EnvironmentProblem.

    `transport` replaces the network (tests); without it the real network transport is
    used, which DOCREADER_FORBID_MODELS forbids.
    """
    if not is_local_model_url(settings.base_url):
        raise EnvironmentProblem(
            f"Адрес реранкера {settings.base_url!r} не на этой машине — укажите в "
            "[reranker] base_url адрес localhost, 127.0.0.1 или ::1 (принцип I)"
        )
    if transport is None and models_forbidden():
        raise EnvironmentProblem(f"На этой машине реранкер не запускается ({FORBID_MODELS_ENV})")
    _silence_loggers()
    base = settings.base_url.rstrip("/") + "/"
    client = httpx2.Client(
        base_url=base,
        timeout=float(settings.timeout_s),
        transport=transport,
        trust_env=False,
    )
    return Reranker(settings, client)
