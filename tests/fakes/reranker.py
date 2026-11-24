"""Fake rerankers: HTTP transports for `reranker.load_reranker` (feature 08, research R-8).

Only the transport is replaced, so the real `httpx2` client of `docreader/reranker.py`
runs in tests and no socket is opened (specs/007-hybrid-search/contracts/reranker.md).

- `TableReranker` — the score of a document is the value of the first key of a table
  (a substring, case-insensitive) found in it, else `default`.
- `FailingReranker` — answers every request wrongly in one way.
- `DownReranker` — the server is not running.
"""

from __future__ import annotations

import json
from typing import Any

import httpx2

FAKE_RERANKER_ID = "fake-reranker"
FAIL_KINDS = ("http_500", "wrong_count", "bad_index", "not_json", "timeout", "connect")


class TableReranker:
    """Answers `POST …/rerank` with scores from `scores`.

    `.requests` — the request bodies (`{"model", "query", "documents"}`), in order. The
    results are returned sorted by score, highest first, as `llama-server` does: the
    client must put them back in document order by `index`.
    """

    def __init__(
        self,
        scores: dict[str, float] | None = None,
        default: float = 0.0,
        served_model: str = FAKE_RERANKER_ID,
    ) -> None:
        self.scores = {k.lower(): v for k, v in (scores or {}).items()}
        self.default = default
        self.served_model = served_model
        self.requests: list[dict[str, Any]] = []
        self.transport = httpx2.MockTransport(self._handle)

    def score_of(self, document: str) -> float:
        text = document.lower()
        for marker, value in self.scores.items():
            if marker in text:
                return value
        return self.default

    def _answer(self, documents: list[str]) -> dict[str, Any]:
        results = [
            {"index": i, "relevance_score": self.score_of(d)} for i, d in enumerate(documents)
        ]
        results.sort(key=lambda r: -r["relevance_score"])
        return {"model": self.served_model, "object": "list", "results": results}

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if not request.url.path.endswith("/rerank"):
            return httpx2.Response(404, json={"error": "not found"})
        body = json.loads(request.content)
        self.requests.append(body)
        return self._respond(request, list(body["documents"]))

    def _respond(self, request: httpx2.Request, documents: list[str]) -> httpx2.Response:
        return httpx2.Response(200, json=self._answer(documents))


class FailingReranker(TableReranker):
    """Every request fails in the way `kind` names.

    `http_500` — HTTP 500; `wrong_count` — one score fewer; `bad_index` — an index out of
    range; `not_json` — a body that is not JSON; `timeout` — `httpx2.ReadTimeout`;
    `connect` — `httpx2.ConnectError`.
    """

    def __init__(self, kind: str) -> None:
        if kind not in FAIL_KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        super().__init__()
        self.kind = kind

    def _respond(self, request: httpx2.Request, documents: list[str]) -> httpx2.Response:
        if self.kind == "http_500":
            return httpx2.Response(500, json={"error": {"message": "server error"}})
        if self.kind == "timeout":
            raise httpx2.ReadTimeout("timed out", request=request)
        if self.kind == "connect":
            raise httpx2.ConnectError("connection refused", request=request)
        if self.kind == "not_json":
            return httpx2.Response(200, content=b"<html>oops</html>")
        answer = self._answer(documents)
        if self.kind == "wrong_count":
            answer["results"] = answer["results"][:-1]
        else:  # bad_index
            answer["results"][-1]["index"] = len(documents) + 5
        return httpx2.Response(200, json=answer)


class DownReranker:
    """The reranker server is not running: every request fails to connect."""

    def __init__(self) -> None:
        self.requests = 0
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests += 1
        raise httpx2.ConnectError("connection refused", request=request)
