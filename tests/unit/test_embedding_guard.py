"""The search model client and its guards (feature 07, contracts/embedding.md; task T007).

Only the HTTP transport is fake (`tests/fakes/embedding.py`); the real `openai` client
runs. Critical part (CLAUDE.md «Model routing»): the model never starts on this server
(DOCREADER_FORBID_MODELS), is reached only on this machine (principle I), and no input
text reaches an error message. Written by the main session; the implementer must not
edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

import math

import pytest

from docreader import embedding
from docreader.config import EmbeddingSettings
from docreader.errors import EnvironmentProblem, ModelUnavailable
from tests.fakes.embedding import (
    FAKE_EMBEDDER_ID,
    DownEmbedder,
    FailingEmbedder,
    HashEmbedder,
    hash_vector,
    unit,
)

MARKER = "МАРКЕР-4471 текст отрывка"


def settings(**overrides) -> EmbeddingSettings:
    return EmbeddingSettings(**overrides)


def embedder(fake, **overrides) -> embedding.Embedder:
    return embedding.load_embedder(settings(**overrides), fake.transport)


def _no_client(*args, **kwargs):
    raise AssertionError("the openai client must not be created")


# --- guards ----------------------------------------------------------------------------


def test_forbidden_without_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embedding.openai, "OpenAI", _no_client)
    with pytest.raises(EnvironmentProblem) as exc:
        embedding.load_embedder(settings())
    assert str(exc.value) == (
        "На этой машине модель поиска не запускается (DOCREADER_FORBID_MODELS)"
    )


@pytest.mark.parametrize(
    "url", ["http://10.0.0.5:8081/v1", "https://api.example.com/v1", "http://u@127.0.0.1/v1"]
)
def test_non_local_address_rejected(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setattr(embedding.openai, "OpenAI", _no_client)
    with pytest.raises(EnvironmentProblem, match=r"\[embedding\] base_url"):
        embedding.load_embedder(settings(base_url=url), HashEmbedder().transport)


def test_openai_environment_variables_change_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    fake = HashEmbedder()
    assert embedder(fake).embed(["a"])  # answered by the fake: the address is the setting
    assert fake.requests == 1


def test_sdk_retries_are_off() -> None:
    fake = DownEmbedder()
    with pytest.raises(ModelUnavailable):
        embedder(fake).check()
    assert fake.requests == 1


# --- check -----------------------------------------------------------------------------


def test_check_reports_model_and_dims() -> None:
    fake = HashEmbedder(dims=8, served_model="bge-m3-Q8_0.gguf")
    info = embedder(fake).check()
    assert info == embedding.EmbedderInfo(served_model="bge-m3-Q8_0.gguf", dims=8)


def test_check_on_a_stopped_server() -> None:
    with pytest.raises(ModelUnavailable) as exc:
        embedder(DownEmbedder()).check()
    assert str(exc.value) == (
        "Модель поиска недоступна по адресу http://127.0.0.1:8081/v1 — "
        "запустите сервер модели поиска"
    )


# --- embed -----------------------------------------------------------------------------


def test_embed_returns_unit_vectors_in_input_order() -> None:
    fake = HashEmbedder(dims=8, reverse=True)
    texts = [f"текст {i}" for i in range(5)]
    vectors = embedder(fake).embed(texts)
    assert len(vectors) == 5
    for text, vector in zip(texts, vectors, strict=True):
        assert vector == pytest.approx(unit(hash_vector(text, 8)))
        assert math.isclose(math.sqrt(sum(x * x for x in vector)), 1.0, rel_tol=1e-9)


def test_embed_sends_batches_of_batch_size() -> None:
    fake = HashEmbedder()
    texts = [f"t{i}" for i in range(7)]
    embedder(fake, batch_size=3).embed(texts)
    assert fake.requests == 3
    assert [len(b["input"]) for b in fake.bodies] == [3, 3, 1]
    assert fake.inputs == texts
    assert {b["model"] for b in fake.bodies} == {"bge-m3"}
    assert {b.get("encoding_format") for b in fake.bodies} == {"float"}


def test_embed_of_nothing_sends_nothing() -> None:
    fake = HashEmbedder()
    assert embedder(fake).embed([]) == []
    assert fake.requests == 0


def test_dims_follow_the_server() -> None:
    client = embedder(HashEmbedder(dims=4))
    assert client.check().dims == 4
    assert len(client.embed(["a"])[0]) == 4


def test_dims_must_match_check() -> None:
    # a server whose vectors change length after check() answers not in form
    changing = HashEmbedder(dims=8)
    client = embedder(changing)
    client.check()
    changing.dims = 6
    with pytest.raises(embedding.EmbeddingRequestError):
        client.embed(["b"])


@pytest.mark.parametrize("kind", ["wrong_count", "mixed_dims", "http_500"])
def test_bad_answers_are_request_errors(kind: str) -> None:
    fake = FailingEmbedder(MARKER, kind)
    with pytest.raises(embedding.EmbeddingRequestError) as exc:
        embedder(fake).embed(["обычный", MARKER])
    assert MARKER not in str(exc.value)
    assert "МАРКЕР" not in repr(exc.value)


@pytest.mark.parametrize("kind", ["connect", "timeout"])
def test_lost_server_is_unavailable(kind: str) -> None:
    fake = FailingEmbedder(MARKER, kind)
    with pytest.raises(ModelUnavailable) as exc:
        embedder(fake).embed([MARKER])
    assert MARKER not in str(exc.value)
    if kind == "timeout":
        assert str(exc.value) == "модель поиска не ответила (тайм-аут 120 с)"


def test_text_longer_than_max_chars_is_refused_before_any_request() -> None:
    fake = HashEmbedder()
    with pytest.raises(ValueError) as exc:
        embedder(fake, max_chars=10).embed(["короткий", "x" * 11])
    assert fake.requests == 0
    assert "x" * 11 not in str(exc.value)
    assert embedder(fake, max_chars=10).embed(["y" * 10])  # exactly max_chars is fine


def test_model_unavailable_is_shared_with_the_language_model() -> None:
    from docreader import llm

    assert llm.ModelUnavailable is ModelUnavailable
    assert issubclass(ModelUnavailable, EnvironmentProblem)


def test_fake_id_default() -> None:
    assert embedder(HashEmbedder()).check().served_model == FAKE_EMBEDDER_ID
