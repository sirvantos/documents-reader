"""Fake search models: HTTP transports for the `openai` client (feature 07, research R-2).

Only the transport is replaced, so the real `openai` client runs in tests and no socket
is opened. `embedding.load_embedder(settings, transport)` takes them
(specs/006-passages-and-indexes/contracts/embedding.md).

- `HashEmbedder` — a vector from the SHA-256 of each input (deterministic; the order of
  search results does not matter where it is used — tech-context «Векторы в тестах поиска»).
- `FailingEmbedder` — like `HashEmbedder`, but fails on the batch holding `fail_on`.
- `DownEmbedder` — the server is not running.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import httpx2

FAKE_EMBEDDER_ID = "fake-embedder"
FAIL_KINDS = ("http_500", "wrong_count", "mixed_dims", "connect", "timeout")


def hash_vector(text: str, dims: int) -> list[float]:
    """The first `dims` bytes of SHA-256 of `text` (repeated as needed) mapped to [-1, 1]."""
    digest = b""
    counter = 0
    while len(digest) < dims:
        digest += hashlib.sha256(f"{counter}:{text}".encode()).digest()
        counter += 1
    raw = [b / 127.5 - 1.0 for b in digest[:dims]]
    if not any(raw):
        raw[0] = 1.0
    return raw


def unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


class HashEmbedder:
    """Answers `/v1/embeddings` with `hash_vector` of each input.

    `.inputs` — every text received, in order; `.requests` — the number of embedding
    requests; `.bodies` — the request bodies. `reverse=True` returns the items of each
    answer in reverse order (the client must order them by `index`).
    """

    def __init__(
        self, dims: int = 8, served_model: str = FAKE_EMBEDDER_ID, *, reverse: bool = False
    ) -> None:
        self.dims = dims
        self.served_model = served_model
        self.reverse = reverse
        self.inputs: list[str] = []
        self.bodies: list[dict[str, Any]] = []
        self.requests = 0
        self.transport = httpx2.MockTransport(self._handle)

    def _vectors(self, texts: list[str]) -> list[list[float]]:
        return [hash_vector(t, self.dims) for t in texts]

    def _answer(self, texts: list[str]) -> httpx2.Response:
        items = [
            {"object": "embedding", "index": i, "embedding": v}
            for i, v in enumerate(self._vectors(texts))
        ]
        if self.reverse:
            items.reverse()
        body = {
            "object": "list",
            "data": items,
            "model": self.served_model,
            "usage": {"prompt_tokens": len(texts), "total_tokens": len(texts)},
        }
        return httpx2.Response(200, json=body)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        if not request.url.path.endswith("/embeddings"):
            return httpx2.Response(404, json={"error": "not found"})
        body = json.loads(request.content)
        texts = body["input"]
        if isinstance(texts, str):
            texts = [texts]
        self.requests += 1
        self.bodies.append(body)
        self.inputs.extend(texts)
        return self._respond(request, texts)

    def _respond(self, request: httpx2.Request, texts: list[str]) -> httpx2.Response:
        return self._answer(texts)


class FailingEmbedder(HashEmbedder):
    """Fails on the batch that holds a text containing `fail_on`.

    `kind`: `http_500` — HTTP 500; `wrong_count` — one vector fewer; `mixed_dims` — the
    last vector one component shorter; `connect` — `httpx2.ConnectError`; `timeout` —
    `httpx2.ReadTimeout`. Other batches are answered like `HashEmbedder`.
    """

    def __init__(self, fail_on: str, kind: str, dims: int = 8) -> None:
        if kind not in FAIL_KINDS:
            raise ValueError(f"unknown kind {kind!r}")
        super().__init__(dims)
        self.fail_on = fail_on
        self.kind = kind

    def _respond(self, request: httpx2.Request, texts: list[str]) -> httpx2.Response:
        if not any(self.fail_on in t for t in texts):
            return self._answer(texts)
        if self.kind == "http_500":
            return httpx2.Response(500, json={"error": {"message": "server error"}})
        if self.kind == "connect":
            raise httpx2.ConnectError("connection refused", request=request)
        if self.kind == "timeout":
            raise httpx2.ReadTimeout("timed out", request=request)
        answer = json.loads(self._answer(texts).content)
        if self.kind == "wrong_count":
            answer["data"] = answer["data"][:-1]
        else:  # mixed_dims
            answer["data"][-1]["embedding"] = answer["data"][-1]["embedding"][:-1]
        return httpx2.Response(200, json=answer)


class DownEmbedder:
    """The search model server is not running: every request fails to connect."""

    def __init__(self) -> None:
        self.requests = 0
        self.transport = httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests += 1
        raise httpx2.ConnectError("connection refused", request=request)


class TopicEmbedder(HashEmbedder):
    """Vectors by topics, so that texts on one topic are close without common words.

    `topics` maps a topic to its marker substrings; each topic is one axis. The vector of
    a text is 1 on every axis whose marker occurs in the lower-cased text, plus
    `0.01 * hash_vector(text)` (it tells texts without topics apart), normalised.
    `dims` must be at least the number of topics. Same protocol and `.inputs` as
    `HashEmbedder` (feature 08, research R-8).
    """

    def __init__(
        self,
        topics: dict[str, list[str]],
        dims: int = 16,
        served_model: str = FAKE_EMBEDDER_ID,
    ) -> None:
        if dims < len(topics):
            raise ValueError("dims must be at least the number of topics")
        super().__init__(dims, served_model)
        self.topics = [[m.lower() for m in markers] for markers in topics.values()]

    def topic_vector(self, text: str) -> list[float]:
        lowered = text.lower()
        noise = hash_vector(text, self.dims)
        vector = [0.01 * x for x in noise]
        for axis, markers in enumerate(self.topics):
            if any(m in lowered for m in markers):
                vector[axis] += 1.0
        return unit(vector)

    def _vectors(self, texts: list[str]) -> list[list[float]]:
        return [self.topic_vector(t) for t in texts]
