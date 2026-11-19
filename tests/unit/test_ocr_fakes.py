"""The test fakes of the recognition engine behave as documented (task T006)."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from docreader.ocr import EngineLine, EngineOutput, image_box_to_pdf
from tests.fakes.ocr import FailingEngine, InterruptingEngine, ScriptedEngine, TruthEngine
from tests.synthetic import make_scans

LINE = EngineLine(text="Договор", box=(10, 20, 110, 40), confidence=0.9)


def _image(w: int = 100, h: int = 200) -> Image.Image:
    return Image.new("L", (w, h), 255)


def test_scripted_engine_returns_outputs_by_call_and_repeats_the_last() -> None:
    first = EngineOutput(lines=(LINE,))
    second = EngineOutput(lines=(), orientation=180)
    engine = ScriptedEngine([first, second])

    assert engine.recognize(_image()) is first
    assert engine.recognize(_image(50, 60)) is second
    assert engine.recognize(_image()) is second
    assert engine.calls == 3
    assert engine.image_sizes == [(100, 200), (50, 60), (100, 200)]
    assert (engine.name, engine.version) == ("scripted", "1")


def test_scripted_engine_without_outputs_returns_no_lines() -> None:
    assert ScriptedEngine([]).recognize(_image()) == EngineOutput(lines=())


def test_failing_engine_fails_only_on_given_calls() -> None:
    inner = ScriptedEngine([EngineOutput(lines=(LINE,))])
    engine = FailingEngine({2}, inner)

    engine.recognize(_image())
    with pytest.raises(RuntimeError, match="engine failed"):
        engine.recognize(_image())
    engine.recognize(_image())
    assert inner.calls == 2
    assert engine.name == "scripted"


def test_interrupting_engine_raises_keyboard_interrupt_on_call_n() -> None:
    engine = InterruptingEngine(2, ScriptedEngine([EngineOutput(lines=(LINE,))]))

    engine.recognize(_image())
    with pytest.raises(KeyboardInterrupt):
        engine.recognize(_image())


# --- TruthEngine (task T012) -----------------------------------------------------------

A4_CROP = (0.0, 0.0, 595.0, 842.0)


@pytest.mark.parametrize(
    ("make", "rotation"),
    [(make_scans.make_scan_clean, 0), (make_scans.make_scan_page_rotate_90, 90)],
)
def test_truth_engine_boxes_map_back_to_the_truth(tmp_path, make, rotation: int) -> None:
    pdf = make(tmp_path / "scan.pdf")
    truth = json.loads(pdf.with_suffix(".truth.json").read_text(encoding="utf-8"))
    first = truth["pages"][0]
    disp = (842, 595) if rotation in (90, 270) else (595, 842)
    image = Image.new("L", (disp[0] * 2, disp[1] * 2), 255)  # 144 dpi
    engine = TruthEngine(truth, rotations={first["page"]: rotation})

    out = engine.recognize(image)

    assert [ln.text for ln in out.lines] == [ln["text"] for ln in first["lines"]]
    for got, want in zip(out.lines, first["lines"], strict=True):
        back = image_box_to_pdf(got.box, scale=2.0, turn=0, rotation=rotation, crop=A4_CROP)
        assert back == pytest.approx(want["bbox"], abs=0.5)
        assert got.confidence == 0.99


def test_truth_engine_answers_scan_pages_in_order_or_as_given(tmp_path) -> None:
    pdf = make_scans.make_scan_mixed(tmp_path / "mixed.pdf")
    truth = json.loads(pdf.with_suffix(".truth.json").read_text(encoding="utf-8"))
    scans = [p for p in truth["pages"] if p["kind"] == "scan"]
    image = Image.new("L", (1190, 1684), 255)

    engine = TruthEngine(truth)
    texts = [engine.recognize(image).lines[0].text for _ in scans]
    assert texts == [p["lines"][0]["text"] for p in scans]

    last = TruthEngine(truth, pages=[scans[-1]["page"]])
    assert last.recognize(image).lines[0].text == scans[-1]["lines"][0]["text"]
