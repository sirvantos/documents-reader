"""Native engine results → EngineLine, without importing any engine (research R-3, T031).

The adapters themselves run only on the analyst's Mac (quickstart Б1, level 3 tests);
here only their pure conversion helpers are checked on hand-made records.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

from docreader import ocr_engines
from docreader.config import RecognitionSettings
from docreader.ocr import EngineLine
from docreader.ocr_engines import tesseract_lines, vision_lines


def test_queue_one_engines_are_registered() -> None:
    assert {"tesseract", "apple_vision"} <= set(ocr_engines.ENGINES)


def test_tesseract_lines_rescale_confidence_and_keep_boxes() -> None:
    items = [
        ("1.1. Подрядчик обязуется\n", 91.5, (100, 200, 900, 240)),
        ("ИНН 7701234567\n", 64.0, (100, 260, 500, 300)),
    ]
    assert tesseract_lines(items) == (
        EngineLine("1.1. Подрядчик обязуется", (100, 200, 900, 240), pytest.approx(0.915)),
        EngineLine("ИНН 7701234567", (100, 260, 500, 300), 0.64),
    )


def test_tesseract_lines_skip_empty_text_and_clamp_confidence() -> None:
    items = [
        ("  \n", 95.0, (0, 0, 1, 1)),
        ("текст", 120.0, (0, 0, 5, 5)),
        ("шум", -1.0, (0, 0, 5, 5)),
    ]
    lines = tesseract_lines(items)
    assert [ln.text for ln in lines] == ["текст", "шум"]
    assert [ln.confidence for ln in lines] == [1.0, 0.0]


def test_text_is_not_corrected() -> None:
    (line,) = tesseract_lines([("Подрядчнк  обязуется", 50.0, (0, 0, 9, 9))])
    assert line.text == "Подрядчнк  обязуется"


def test_vision_boxes_are_flipped_to_a_top_left_origin() -> None:
    # Vision: normalised (x, y, w, h), origin bottom-left
    items = [("Договор подряда", 0.98, (0.1, 0.8, 0.5, 0.05))]
    (line,) = vision_lines(items, size=(1000, 2000))
    assert line.text == "Договор подряда"
    assert line.confidence == pytest.approx(0.98)
    assert line.box == pytest.approx((100.0, 300.0, 600.0, 400.0))


def test_vision_lines_skip_empty_text() -> None:
    assert vision_lines([(" ", 1.0, (0, 0, 1, 1))], size=(10, 10)) == ()


# --- _Tesseract start-up against a stand-in for tesserocr's real signatures --------------


class _FakeTesserocr(types.ModuleType):
    """Mirrors tesserocr 2.13: `path` defaults to a built-in path; an explicit None is a
    TypeError (its `_b()` helper), as in `get_languages(path=_DEFAULT_PATH)`."""

    def __init__(self, default_path: Path) -> None:
        super().__init__("tesserocr")
        self.default_path = str(default_path) + os.sep
        self.languages_calls: list[tuple[object, ...]] = []
        self.api_kwargs: dict[str, object] = {}
        fake = self

        class PyTessBaseAPI:
            def __init__(self, path: object = fake.default_path, lang: str = "eng") -> None:
                fake._check(path)
                fake.api_kwargs = {"path": path, "lang": lang}

        self.PyTessBaseAPI = PyTessBaseAPI

    @staticmethod
    def _check(path: object) -> None:
        if not isinstance(path, (str, bytes)):
            raise TypeError(f"Expected str or bytes, got {type(path).__name__}")

    def get_languages(self, *args: object) -> tuple[str, list[str]]:
        self.languages_calls.append(args)
        path = args[0] if args else self.default_path
        self._check(path)
        return str(path), ["eng", "osd", "rus"]

    def tesseract_version(self) -> str:
        return "tesseract 5.5.4\n leptonica-1.87.0"


@pytest.fixture
def fake_tesserocr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> _FakeTesserocr:
    (tmp_path / "rus.traineddata").write_bytes(b"synthetic stand-in, not language data")
    fake = _FakeTesserocr(tmp_path)
    monkeypatch.setitem(sys.modules, "tesserocr", fake)
    return fake


def test_tesseract_without_model_dir_uses_the_built_in_path(
    fake_tesserocr: _FakeTesserocr,
) -> None:
    engine = ocr_engines._Tesseract(RecognitionSettings(engine="tesseract"))
    assert fake_tesserocr.languages_calls == [()]  # no explicit None
    assert fake_tesserocr.api_kwargs == {"path": fake_tesserocr.default_path, "lang": "rus"}
    assert engine.version.startswith("5.5.4 rus ")
    assert not engine.version.endswith("?")


def test_tesseract_model_dir_is_passed_through(
    fake_tesserocr: _FakeTesserocr, tmp_path: Path
) -> None:
    model_dir = str(tmp_path) + os.sep
    ocr_engines._Tesseract(RecognitionSettings(engine="tesseract", model_dir=model_dir))
    assert fake_tesserocr.languages_calls == [(model_dir,)]
    assert fake_tesserocr.api_kwargs == {"path": model_dir, "lang": "rus"}
