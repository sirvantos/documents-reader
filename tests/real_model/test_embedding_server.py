"""Level 3: the real search model server on synthetic strings (feature 07; task T022).

Only on the analyst's Mac, with `llama-server --embedding` running (quickstart Б0–Б1):

    uv run pytest -m real_model tests/real_model/test_embedding_server.py

Excluded by default (`addopts = -m 'not real_model'`); the fixture `_forbid_models` does
not set DOCREADER_FORBID_MODELS for this group. `[embedding]` comes from
$DOCREADER_DATA_DIR/settings.toml when the variable is set, otherwise the defaults. Only
synthetic strings are sent; connections to anything but this machine fail the test
(`_no_network`, principle I).
"""

from __future__ import annotations

import math
import os
import socket
from dataclasses import replace

import pytest

from docreader import embedding
from docreader.config import EmbeddingSettings, load_settings
from docreader.errors import ModelUnavailable

pytestmark = pytest.mark.real_model

BGE_M3_DIMS = 1024


def _settings() -> EmbeddingSettings:
    if os.environ.get("DOCREADER_DATA_DIR"):
        return load_settings().embedding
    return EmbeddingSettings()


def _free_local_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _requisites_like(chars: int) -> str:
    """Digit-heavy synthetic text like a requisites section (research R-6, analyze G2)."""
    unit = ("ИНН 0000000000 КПП 000000000 р/с 00000000000000000000 БИК 000000000 "
            "к/с 00000000000000000000 ОГРН 0000000000000 ")
    return (unit * (chars // len(unit) + 1))[:chars]


def test_check_reports_bge_m3_dims() -> None:
    info = embedding.load_embedder(_settings()).check()
    assert info.dims == BGE_M3_DIMS
    assert info.served_model


def test_same_text_same_vector_of_length_one() -> None:
    client = embedding.load_embedder(_settings())
    a, b = client.embed(["Подрядчик уплачивает неустойку.", "Подрядчик уплачивает неустойку."])
    assert a == pytest.approx(b, abs=1e-6)
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0, rel_tol=1e-6)


def test_batch_keeps_input_order() -> None:
    client = embedding.load_embedder(_settings())
    texts = [f"Синтетический пункт номер {i} о сроке выполнения работ." for i in range(16)]
    vectors = client.embed(texts)
    assert len(vectors) == 16
    singles = [client.embed([t])[0] for t in (texts[0], texts[15])]
    assert vectors[0] == pytest.approx(singles[0], abs=1e-4)
    assert vectors[15] == pytest.approx(singles[1], abs=1e-4)


def test_max_chars_of_digit_heavy_text_is_accepted() -> None:
    s = _settings()
    client = embedding.load_embedder(s)
    (vector,) = client.embed([_requisites_like(s.max_chars)])
    assert len(vector) == BGE_M3_DIMS


def test_closed_port_is_model_unavailable() -> None:
    port = _free_local_port()
    client = embedding.load_embedder(replace(_settings(), base_url=f"http://127.0.0.1:{port}/v1"))
    with pytest.raises(ModelUnavailable):
        client.check()
