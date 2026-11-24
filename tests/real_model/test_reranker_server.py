"""Level 3: the real reranker server on synthetic strings (feature 08; task T016).

Only on the analyst's Mac, with `llama-server --reranking` running (quickstart Б0–Б1):

    uv run --env-file .env pytest -m real_model tests/real_model/test_reranker_server.py

Excluded by default (`addopts = -m 'not real_model'`); the fixture `_forbid_models` does
not set DOCREADER_FORBID_MODELS for this group. `[reranker]` comes from
$DOCREADER_DATA_DIR/settings.toml when the variable is set, otherwise the defaults. Only
synthetic strings are sent; connections to anything but this machine fail the test
(`_no_network`, principle I). Checks what research R-7 marks «[проверить]»: the path
`/v1/rerank`, the form of the answer, and that the scores order passages sensibly.
"""

from __future__ import annotations

import os
import socket
from dataclasses import replace

import pytest

from docreader import reranker
from docreader.config import RerankerSettings, load_settings
from docreader.errors import ModelUnavailable

pytestmark = pytest.mark.real_model


def _settings() -> RerankerSettings:
    if os.environ.get("DOCREADER_DATA_DIR"):
        return load_settings().reranker
    return RerankerSettings()


def _free_local_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_check_reports_a_model() -> None:
    info = reranker.load_reranker(_settings()).check()
    assert info.served_model


def test_one_score_per_document_in_document_order() -> None:
    client = reranker.load_reranker(_settings())
    documents = [
        "Гарантийный срок составляет 12 месяцев.",
        "Покупатель оплачивает товар в течение 30 дней с даты поставки.",
        "Приёмка проводится на складе Покупателя.",
    ]
    scores = client.score("срок оплаты товара", documents)
    assert len(scores) == 3
    # the same documents in reverse order give the same scores in reverse order
    again = client.score("срок оплаты товара", list(reversed(documents)))
    assert again == pytest.approx(list(reversed(scores)), rel=1e-3, abs=1e-3)


def test_obvious_pair_is_ordered() -> None:
    client = reranker.load_reranker(_settings())
    payment, warranty = client.score(
        "срок оплаты",
        ["Оплата производится в течение 30 дней.", "Гарантийный срок 12 месяцев."],
    )
    assert payment > warranty


def test_long_document_within_max_chars_is_scored() -> None:
    settings = _settings()
    query, document, _ = reranker.rerank_input(
        "срок оплаты", "D-0001 · пункт 2.2", "Оплата производится в течение 30 дней. " * 400,
        settings.max_chars,
    )
    (score,) = reranker.load_reranker(settings).score(query, [document])
    assert score == score  # a number, not NaN


def test_no_server_is_model_unavailable() -> None:
    settings = replace(_settings(), base_url=f"http://127.0.0.1:{_free_local_port()}/v1")
    with pytest.raises(ModelUnavailable):
        reranker.load_reranker(settings).check()
