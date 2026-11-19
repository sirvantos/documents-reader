"""Level 3: the real recognition engine on synthetic scans (research R-13; task T038).

Only on the analyst's Mac: `uv run pytest -m real_model tests/real_model/`. Excluded by
default (`addopts = -m 'not real_model'`); on the development server the engine is not
installed and DOCREADER_FORBID_MODELS forbids it. The engine comes from `[recognition]`
in $DOCREADER_DATA_DIR/settings.toml; only synthetic files from `make_scans` are used.
Any network connection during loading or recognition fails the test (principle I).
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pypdfium2 as pdfium
import pytest

from docreader import ocr_engines
from docreader.config import load_settings
from docreader.errors import EnvironmentProblem
from docreader.ocr import render_page
from docreader.recognition_eval import char_accuracy
from tests.synthetic import make_scans

pytestmark = pytest.mark.real_model


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    """Every connection attempt is recorded and refused."""
    attempts: list[object] = []

    def trap(*args: object, **kwargs: object) -> None:
        attempts.append(args[1:] if len(args) > 1 else args)
        raise OSError("network access is forbidden while recognising (principle I)")

    monkeypatch.setattr(socket.socket, "connect", trap)
    monkeypatch.setattr(socket.socket, "connect_ex", trap)
    monkeypatch.setattr(socket, "create_connection", trap)
    yield attempts
    assert attempts == [], f"the engine tried to connect: {attempts}"


@pytest.fixture(scope="module")
def settings():
    loaded = load_settings()
    assert loaded.recognition.engine, "set [recognition] engine in settings.toml (quickstart Б1)"
    return loaded


def _clean_page(tmp_path: Path, dpi: int):
    pdf_path = make_scans.make_scan_clean(tmp_path / "clean.pdf", pages=1)
    truth = json.loads(pdf_path.with_suffix(".truth.json").read_text(encoding="utf-8"))
    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[0]
        try:
            image = render_page(page, dpi)
        finally:
            page.close()
    finally:
        pdf.close()
    return image, truth["pages"][0]["lines"]


def test_engine_loads_and_reads_a_clean_synthetic_page(settings, tmp_path, no_network) -> None:
    engine = ocr_engines.load_engine(settings.recognition, settings.data_dir)
    assert engine.name == settings.recognition.engine
    assert engine.version.strip()
    image, truth_lines = _clean_page(tmp_path, settings.recognition.dpi)

    output = engine.recognize(image)

    assert output.lines, "no lines on a clean synthetic page"
    width, height = image.size
    for line in output.lines:
        left, top, right, bottom = line.box
        assert 0 <= left < right <= width + 1 and 0 <= top < bottom <= height + 1
        assert 0.0 <= line.confidence <= 1.0
    got = "\n".join(line.text for line in output.lines)
    expected = "\n".join(line["text"] for line in truth_lines)
    assert char_accuracy(expected, got) >= 0.95


def test_missing_model_files_give_an_environment_problem(settings, tmp_path, no_network) -> None:
    if settings.recognition.engine != "tesseract":
        pytest.skip("only tesseract reads its language data from model_dir")
    empty = tmp_path / "no-models"
    empty.mkdir()
    with pytest.raises(EnvironmentProblem):
        ocr_engines.load_engine(
            replace(settings.recognition, model_dir=str(empty)), settings.data_dir
        )
