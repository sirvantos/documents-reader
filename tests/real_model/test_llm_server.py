"""Level 3: the real language model server on a synthetic contract (feature 05; T027).

Only on the analyst's Mac, with the model server running (quickstart Б1):

    uv run pytest -m real_model tests/real_model/test_llm_server.py

Excluded by default (`addopts = -m 'not real_model'`); the fixture `_forbid_models` does
not set DOCREADER_FORBID_MODELS for this group. `[extraction]` comes from
$DOCREADER_DATA_DIR/settings.toml when the variable is set, otherwise the defaults. Only
the synthetic contract `base` of `make_extraction_contract` is sent; connections to
anything but this machine fail the test (`_no_network`, principle I).
"""

from __future__ import annotations

import os
import socket
from dataclasses import replace
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from docreader import llm
from docreader.config import ExtractionSettings, load_settings
from docreader.extraction_prompt import ExtractionAnswer, build_messages
from docreader.fields import FIELD_NAMES
from tests.synthetic.make_pdfs import make_extraction_contract

pytestmark = pytest.mark.real_model


def _settings() -> ExtractionSettings:
    if os.environ.get("DOCREADER_DATA_DIR"):
        return load_settings().extraction
    return ExtractionSettings()


def _base_text(tmp_path: Path) -> str:
    pdf = pdfium.PdfDocument(str(make_extraction_contract(tmp_path / "base.pdf")))
    try:
        pages = [page.get_textpage().get_text_range() for page in pdf]
    finally:
        pdf.close()
    return "\n".join(pages[:2])  # without the appendix page, as the stage shows it


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def test_server_answers_models() -> None:
    served = llm.load_client(_settings()).check()
    assert isinstance(served, str) and served


def test_answer_on_a_synthetic_contract_fits_the_schema(tmp_path: Path) -> None:
    client = llm.load_client(_settings())
    answer = client.extract(build_messages(_base_text(tmp_path)), ExtractionAnswer)
    assert isinstance(answer, ExtractionAnswer)
    for name in FIELD_NAMES:
        assert isinstance(getattr(answer, name).found, bool)
    assert isinstance(answer.other_party.found, bool)


def test_short_timeout_is_model_unavailable(tmp_path: Path) -> None:
    client = llm.load_client(replace(_settings(), timeout_s=10, max_retries=0))
    # a long text cannot be read in 10 s; the call must stop with a clear error
    long_text = _base_text(tmp_path) * 40
    with pytest.raises(llm.ModelUnavailable, match="тайм-аут 10 с"):
        client.extract(build_messages(long_text), ExtractionAnswer)


def test_closed_port_is_model_unavailable() -> None:
    port = _free_local_port()
    client = llm.load_client(replace(_settings(), base_url=f"http://127.0.0.1:{port}/v1"))
    with pytest.raises(llm.ModelUnavailable, match="Модель недоступна по адресу"):
        client.check()
