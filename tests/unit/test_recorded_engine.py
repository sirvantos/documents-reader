"""RecordedEngine answers with a real engine's recorded output (level 2; task T037).

The recording holds, for every scan page, the engine output on the image turned 0, 90,
180 and 270 degrees, each with a small thumbnail. The fake finds the entry whose
thumbnail is closest to the image it gets, so the turn trial of recognition works too.
Out-of-date or missing recordings fail; they are never skipped.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from docreader.config import RecognitionSettings
from docreader.recognition import _clockwise
from tests.fakes.ocr import RecordedEngine, StaleRecording, thumbnail
from tests.synthetic import make_scans

SETTINGS = RecognitionSettings(engine="tesseract", dpi=300)


def page_image(mark: tuple[int, int]) -> Image.Image:
    """A white page with one black block; `mark` moves the block (another page)."""
    image = Image.new("L", (210, 297), 255)
    x, y = mark
    ImageDraw.Draw(image).rectangle((x, y, x + 60, y + 20), fill=0)
    return image


def entry(image: Image.Image, turn: int, text: str) -> dict:
    turned = _clockwise(image, turn)
    return {
        "turn": turn,
        "image_size": list(turned.size),
        "thumb": thumbnail(turned),
        "orientation": None,
        "lines": [{"text": text, "box": [1.0, 2.0, 30.0, 12.0], "confidence": 0.9}],
    }


def write_recording(path: Path, pages: dict[int, Image.Image], **overrides) -> Path:
    data = {
        "engine": "tesseract",
        "engine_version": "5.5.4 rus e16e5e036cce",
        "dpi": 300,
        "recorded_at": "2026-11-20T00:00:00+00:00",
        "generator_version": make_scans.SCAN_GENERATOR_VERSION,
        "variant": "clean",
        "source": "scan_clean.pdf",
        "pages": [
            {
                "page": number,
                "turns": [entry(image, t, f"p{number} t{t}") for t in (0, 90, 180, 270)],
            }
            for number, image in pages.items()
        ],
    }
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_name_and_version_come_from_the_recording(tmp_path: Path) -> None:
    path = write_recording(tmp_path / "r.json", {1: page_image((20, 20))})
    engine = RecordedEngine(path, SETTINGS)
    assert (engine.name, engine.version) == ("tesseract", "5.5.4 rus e16e5e036cce")


def test_each_page_and_turn_gets_its_own_answer(tmp_path: Path) -> None:
    first, second = page_image((20, 20)), page_image((120, 240))
    engine = RecordedEngine(write_recording(tmp_path / "r.json", {1: first, 2: second}), SETTINGS)

    assert engine.recognize(second).lines[0].text == "p2 t0"
    assert engine.recognize(first).lines[0].text == "p1 t0"
    assert engine.recognize(_clockwise(first, 180)).lines[0].text == "p1 t180"
    assert engine.recognize(_clockwise(second, 90)).lines[0].text == "p2 t90"
    assert engine.misses == []


def test_lines_keep_box_and_confidence(tmp_path: Path) -> None:
    image = page_image((20, 20))
    engine = RecordedEngine(write_recording(tmp_path / "r.json", {1: image}), SETTINGS)
    (line,) = engine.recognize(image).lines
    assert line.box == (1.0, 2.0, 30.0, 12.0)
    assert line.confidence == pytest.approx(0.9)


def test_an_image_without_a_recorded_entry_is_a_miss(tmp_path: Path) -> None:
    path = write_recording(tmp_path / "r.json", {1: page_image((20, 20))})
    engine = RecordedEngine(path, SETTINGS)
    other = Image.new("L", (400, 100), 0)

    with pytest.raises(LookupError):
        engine.recognize(other)
    assert engine.misses == [(400, 100)]


STALE = re.escape("запись устарела (или отсутствует)")


@pytest.mark.parametrize(
    "override",
    [
        {"engine": "other"},
        {"dpi": 200},
        {"generator_version": make_scans.SCAN_GENERATOR_VERSION - 1},
    ],
)
def test_out_of_date_recording_fails(tmp_path: Path, override: dict) -> None:
    path = write_recording(tmp_path / "r.json", {1: page_image((20, 20))}, **override)
    with pytest.raises(StaleRecording, match=STALE) as raised:
        RecordedEngine(path, SETTINGS)
    assert "python -m tests.synthetic.record_recognition" in str(raised.value)


def test_missing_recording_fails(tmp_path: Path) -> None:
    with pytest.raises(StaleRecording, match=STALE):
        RecordedEngine(tmp_path / "absent.json", SETTINGS)


def test_stale_recording_is_a_failure_not_a_skip() -> None:
    assert issubclass(StaleRecording, AssertionError)
