"""The test fakes of the recognition engine behave as documented (task T006)."""

from __future__ import annotations

import pytest
from PIL import Image

from docreader.ocr import EngineLine, EngineOutput
from tests.fakes.ocr import FailingEngine, InterruptingEngine, ScriptedEngine

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
