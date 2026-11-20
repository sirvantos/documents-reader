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
from docreader.ocr_engines import split_wide_gaps, tesseract_lines


def test_only_the_chosen_engine_is_registered() -> None:
    # Tesseract chosen on 2026-11-20; Apple Vision rejected (docs/tech-context.md).
    assert set(ocr_engines.ENGINES) == {"tesseract"}


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
            def __init__(
                self, path: object = fake.default_path, lang: str = "eng", psm: object = None
            ) -> None:
                fake._check(path)
                if lang == "osd":
                    fake.osd_kwargs = {"path": path, "lang": lang, "psm": psm}
                else:
                    fake.api_kwargs = {"path": path, "lang": lang}

        self.PyTessBaseAPI = PyTessBaseAPI
        self.PSM = types.SimpleNamespace(OSD_ONLY="OSD_ONLY")
        self.osd_kwargs: dict[str, object] = {}

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
    assert " osd " in engine.version  # orientation data is part of the version
    assert fake_tesserocr.osd_kwargs["psm"] == "OSD_ONLY"


def test_tesseract_model_dir_is_passed_through(
    fake_tesserocr: _FakeTesserocr, tmp_path: Path
) -> None:
    model_dir = str(tmp_path) + os.sep
    ocr_engines._Tesseract(RecognitionSettings(engine="tesseract", model_dir=model_dir))
    assert fake_tesserocr.languages_calls == [(model_dir,)]
    assert fake_tesserocr.api_kwargs == {"path": model_dir, "lang": "rus"}


class _FakeWord:
    """A word position of tesserocr's result iterator (WORD level), with its line."""

    def __init__(self, text: str | None, box, conf: float, line: tuple | None = None) -> None:
        self.text, self.box, self.conf, self.line = text, box, conf, line

    def IsAtBeginningOf(self, level: object) -> bool:  # tesserocr's method names
        return self.line is not None

    def GetUTF8Text(self, level: object) -> str:
        text = self.line[0] if level == "TEXTLINE" else self.text
        if text is None:  # what tesserocr 2.13 does on a line or word without text
            raise RuntimeError("No text returned")
        return text

    def BoundingBox(self, level: object):
        return self.line[2] if level == "TEXTLINE" else self.box

    def Confidence(self, level: object) -> float:
        return self.line[1] if level == "TEXTLINE" else self.conf


class _Api:
    def __init__(self, osd: dict | None = None) -> None:
        self.osd = osd

    def SetImage(self, image: object) -> None:
        pass

    def Recognize(self) -> None:
        pass

    def GetIterator(self) -> object:
        return object()

    def DetectOrientationScript(self) -> dict | None:
        return self.osd


def _engine(fake_tesserocr, words, osd: dict | None = None):
    fake_tesserocr.RIL = types.SimpleNamespace(TEXTLINE="TEXTLINE", WORD="WORD")
    fake_tesserocr.iterate_level = lambda iterator, level: iter(words)
    engine = ocr_engines._Tesseract(RecognitionSettings(engine="tesseract"))
    engine._api = _Api()
    engine._osd = _Api(osd) if osd is not None else None
    return engine


def _image():
    from PIL import Image

    return Image.new("L", (1000, 200), 255)


def test_a_line_without_text_is_skipped_not_a_page_error(fake_tesserocr) -> None:
    words = [
        _FakeWord("1.1.", (10, 10, 50, 30), 90.0, ("1.1. Подрядчик\n", 90.0, (10, 10, 200, 30))),
        _FakeWord("Подрядчик", (60, 10, 200, 30), 90.0),
        _FakeWord(None, (10, 40, 200, 60), 0.0, (None, 0.0, (10, 40, 200, 60))),
        _FakeWord("ИНН", (10, 70, 60, 90), 80.0, ("ИНН 7701234567\n", 80.0, (10, 70, 200, 90))),
        _FakeWord("7701234567", (70, 70, 200, 90), 80.0),
    ]
    output = _engine(fake_tesserocr, words).recognize(_image())
    assert [ln.text for ln in output.lines] == ["1.1. Подрядчик", "ИНН 7701234567"]


def test_a_line_across_two_columns_is_cut_at_the_wide_gap(fake_tesserocr) -> None:
    line = ("Заказчик: Подрядчик:\n", 85.0, (10, 10, 700, 30))
    words = [
        _FakeWord("Заказчик:", (10, 10, 120, 30), 90.0, line),
        _FakeWord("Подрядчик:", (560, 10, 700, 30), 80.0),
    ]
    output = _engine(fake_tesserocr, words).recognize(_image())
    assert [(ln.text, ln.box) for ln in output.lines] == [
        ("Заказчик:", (10, 10, 120, 30)),
        ("Подрядчик:", (560, 10, 700, 30)),
    ]
    assert [ln.confidence for ln in output.lines] == [pytest.approx(0.9), pytest.approx(0.8)]


@pytest.mark.parametrize(
    ("osd", "expected"),
    [
        ({"orient_deg": 180, "orient_conf": 18.4}, 180),
        ({"orient_deg": 0, "orient_conf": 13.0}, 0),
        ({"orient_deg": 90, "orient_conf": 0.5}, None),  # unsure: the trial decides
        (None, None),  # blank page: OSD finds nothing
    ],
)
def test_orientation_comes_from_osd(fake_tesserocr, osd, expected) -> None:
    words = [_FakeWord("Договор", (10, 10, 120, 30), 90.0, ("Договор\n", 90.0, (10, 10, 120, 30)))]
    engine = _engine(fake_tesserocr, words, osd=osd if osd is not None else {})
    if osd is None:
        engine._osd.osd = None
    assert engine.recognize(_image()).orientation == expected


def test_without_osd_data_there_is_no_orientation(fake_tesserocr) -> None:
    words = [_FakeWord("Договор", (10, 10, 120, 30), 90.0, ("Договор\n", 90.0, (10, 10, 120, 30)))]
    assert _engine(fake_tesserocr, words).recognize(_image()).orientation is None


# --- cutting a Tesseract line at wide gaps (pure, research R-7) --------------------------


def _w(text: str, left: int, right: int, conf: float = 90.0):
    return (text, conf, (left, 10, right, 30))  # height 20


def test_line_without_wide_gaps_stays_as_tesseract_gave_it() -> None:
    words = [_w("по", 10, 40), _w("формам,", 80, 200), _w("установленным", 245, 450)]
    line = ("по   формам,   установленным", 77.0, (10, 8, 450, 32), words)
    assert split_wide_gaps([line], gap=3.0) == [line[:3]]  # justified gaps of ~2 heights


def test_segments_get_joined_text_union_box_and_weighted_confidence() -> None:
    words = [_w("ИНН", 10, 60, 60.0), _w("7701234567", 70, 250, 90.0), _w("КПП", 400, 450, 80.0)]
    line = ("ИНН 7701234567 КПП", 85.0, (10, 10, 450, 30), words)
    assert split_wide_gaps([line], gap=3.0) == [
        ("ИНН 7701234567", pytest.approx((3 * 60 + 10 * 90) / 13), (10, 10, 250, 30)),
        ("КПП", 80.0, (400, 10, 450, 30)),
    ]


def test_line_without_words_is_kept() -> None:
    line = ("текст", 50.0, (0, 0, 9, 9), [])
    assert split_wide_gaps([line], gap=3.0) == [line[:3]]
