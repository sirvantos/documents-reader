"""The reranker client and its guards (feature 08, contracts/reranker.md; task T005).

Only the HTTP transport is fake (`tests/fakes/reranker.py`); the real `httpx2` client
runs. Critical part (CLAUDE.md «Model routing»): the reranker never starts on this
server (DOCREADER_FORBID_MODELS), is reached only on this machine (principle I), and no
query or document text reaches an error message. Written by the main session; the
implementer must not edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

import httpx2
import pytest

from docreader import reranker
from docreader.config import RerankerSettings
from docreader.errors import EnvironmentProblem, ModelUnavailable
from tests.fakes.reranker import (
    FAIL_KINDS,
    FAKE_RERANKER_ID,
    DownReranker,
    FailingReranker,
    TableReranker,
)

QUERY = "ЗАПРОС-5531 срок оплаты"
DOCS = ["ДОКУМЕНТ-1 оплата в течение 30 дней", "ДОКУМЕНТ-2 гарантийный срок", "ДОКУМЕНТ-3"]


def client(fake, **overrides) -> reranker.Reranker:
    return reranker.load_reranker(RerankerSettings(**overrides), fake.transport)


def _no_client(*args, **kwargs):
    raise AssertionError("the HTTP client must not be created")


# --- guards ----------------------------------------------------------------------------


def test_forbid_without_transport_stops_before_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reranker.httpx2, "Client", _no_client)
    with pytest.raises(EnvironmentProblem, match="DOCREADER_FORBID_MODELS"):
        reranker.load_reranker(RerankerSettings())


def test_forbid_message(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(EnvironmentProblem) as exc:
        reranker.load_reranker(RerankerSettings())
    assert str(exc.value) == "На этой машине реранкер не запускается (DOCREADER_FORBID_MODELS)"


@pytest.mark.parametrize(
    "url", ["http://192.168.1.5:8082/v1", "http://example.com/v1", "https://a.b/v1"]
)
def test_non_local_address_refused_even_with_transport(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    monkeypatch.setattr(reranker.httpx2, "Client", _no_client)
    with pytest.raises(EnvironmentProblem, match="принцип I"):
        reranker.load_reranker(RerankerSettings(base_url=url), TableReranker().transport)


def test_fake_transport_accepted_under_forbid() -> None:
    fake = TableReranker()
    assert client(fake).check().served_model == FAKE_RERANKER_ID


def test_client_ignores_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}
    real = httpx2.Client

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(reranker.httpx2, "Client", spy)
    client(TableReranker())
    assert seen.get("trust_env") is False


# --- answers ---------------------------------------------------------------------------


def test_scores_in_document_order() -> None:
    fake = TableReranker({"гарантийный": 2.5, "30 дней": 7.0}, default=-1.0)
    # the fake answers sorted by score; the client must restore the document order
    assert client(fake).score(QUERY, DOCS) == [7.0, 2.5, -1.0]


def test_request_body() -> None:
    fake = TableReranker()
    client(fake, model="m-1").score(QUERY, DOCS)
    assert fake.requests == [{"model": "m-1", "query": QUERY, "documents": DOCS}]


def test_request_path_is_rerank_under_base_url() -> None:
    paths: list[str] = []
    fake = TableReranker()
    inner = fake.transport

    def handler(request: httpx2.Request) -> httpx2.Response:
        paths.append(request.url.path)
        return inner.handle_request(request)

    transport = httpx2.MockTransport(handler)
    reranker.load_reranker(RerankerSettings(base_url="http://127.0.0.1:8082/v1"), transport).score(
        QUERY, DOCS
    )
    assert paths == ["/v1/rerank"]


def test_empty_documents_no_request() -> None:
    fake = TableReranker()
    assert client(fake).score(QUERY, []) == []
    assert fake.requests == []


def test_check_probe_and_served_model() -> None:
    fake = TableReranker(served_model="bge-reranker-v2-m3-q8")
    info = client(fake).check()
    assert info.served_model == "bge-reranker-v2-m3-q8"
    assert fake.requests == [
        {"model": "bge-reranker-v2-m3", "query": "проверка", "documents": ["проверка"]}
    ]


def test_check_without_model_in_answer_uses_settings() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"results": [{"index": 0, "relevance_score": 1.0}]})

    r = reranker.load_reranker(RerankerSettings(model="mine"), httpx2.MockTransport(handler))
    assert r.check().served_model == "mine"


# --- errors ----------------------------------------------------------------------------


def test_down_is_model_unavailable() -> None:
    with pytest.raises(ModelUnavailable) as exc:
        client(DownReranker()).score(QUERY, DOCS)
    assert str(exc.value) == (
        "Реранкер недоступен по адресу http://127.0.0.1:8082/v1 — запустите его "
        "или выполните поиск с --no-rerank"
    )


def test_timeout_is_model_unavailable() -> None:
    with pytest.raises(ModelUnavailable, match=r"реранкер не ответил \(тайм-аут 60 с\)"):
        client(FailingReranker("timeout")).score(QUERY, DOCS)


def test_connect_is_model_unavailable() -> None:
    with pytest.raises(ModelUnavailable, match="Реранкер недоступен"):
        client(FailingReranker("connect")).score(QUERY, DOCS)


def test_http_500_is_request_error() -> None:
    with pytest.raises(reranker.RerankRequestError, match="HTTP 500"):
        client(FailingReranker("http_500")).score(QUERY, DOCS)


def test_not_json_is_request_error() -> None:
    with pytest.raises(reranker.RerankRequestError, match="ответ реранкера не по форме"):
        client(FailingReranker("not_json")).score(QUERY, DOCS)


def test_wrong_count_is_request_error() -> None:
    with pytest.raises(reranker.RerankRequestError, match="2 оценок на 3 отрывков"):
        client(FailingReranker("wrong_count")).score(QUERY, DOCS)


def test_bad_index_is_request_error() -> None:
    with pytest.raises(reranker.RerankRequestError, match="не по форме"):
        client(FailingReranker("bad_index")).score(QUERY, DOCS)


@pytest.mark.parametrize(
    "answer",
    [
        {"results": [{"index": 0, "relevance_score": 1.0}, {"index": 0, "relevance_score": 2.0}]},
        {"results": [{"index": 0, "relevance_score": "x"}, {"index": 1, "relevance_score": 1}]},
        {"results": [{"index": 0, "relevance_score": True}, {"index": 1, "relevance_score": 1}]},
        {"results": [{"index": 0}, {"index": 1, "relevance_score": 1.0}]},
        {"results": [{"index": "0", "relevance_score": 1}, {"index": 1, "relevance_score": 1}]},
        {"results": "nope"},
        {"data": []},
        [1, 2],
    ],
)
def test_answers_not_in_form(answer) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=answer)

    r = reranker.load_reranker(RerankerSettings(), httpx2.MockTransport(handler))
    with pytest.raises(reranker.RerankRequestError, match="не по форме"):
        r.score(QUERY, DOCS[:2])


@pytest.mark.parametrize("value", [b"NaN", b"Infinity"])
def test_non_finite_score(value: bytes) -> None:
    body = b'{"results": [{"index": 0, "relevance_score": ' + value + b'}]}'

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=body)

    r = reranker.load_reranker(RerankerSettings(), httpx2.MockTransport(handler))
    with pytest.raises(reranker.RerankRequestError, match="оценка не число"):
        r.score(QUERY, DOCS[:1])


@pytest.mark.parametrize("kind", FAIL_KINDS)
def test_no_message_holds_query_or_document_text(kind: str) -> None:
    with pytest.raises((reranker.RerankRequestError, ModelUnavailable)) as exc:
        client(FailingReranker(kind)).score(QUERY, DOCS)
    message = str(exc.value)
    assert "ЗАПРОС-5531" not in message and "ДОКУМЕНТ" not in message
    assert exc.value.__cause__ is None or "ЗАПРОС" not in str(exc.value.__cause__)


# --- rerank_input ----------------------------------------------------------------------


def test_rerank_input_uncut() -> None:
    q, doc, cut = reranker.rerank_input("срок", "D-0001 · пункт 2.2", "Текст пункта.", 1000)
    assert (q, doc, cut) == ("срок", "D-0001 · пункт 2.2\nТекст пункта.", False)


def test_rerank_input_cuts_long_query_to_quarter() -> None:
    q, doc, cut = reranker.rerank_input("я" * 300, "метка", "текст", 1000)
    assert q == "я" * 250 and cut is True
    assert len(q) + len(doc) <= 1000


def test_rerank_input_cuts_document_to_fit() -> None:
    q, doc, cut = reranker.rerank_input("срок", "метка", "т" * 2000, 100)
    assert doc == ("метка\n" + "т" * 2000)[: 100 - 4]
    assert len(q) + len(doc) == 100
    assert cut is False  # the flag tells about the query only
