"""Hand-written recognition engines for tests (level 1, research R-13; contracts/engine.md).

No real engine is ever imported here. Every fake has `name` and `version` and records
the images it got, so tests can count calls and check image sizes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from PIL import Image

from docreader.ocr import EngineOutput, RecognitionEngine


@dataclass
class ScriptedEngine:
    """Returns the given outputs by call number (1-based); the last one repeats."""

    outputs: Sequence[EngineOutput]
    name: str = "scripted"
    version: str = "1"
    calls: int = 0
    image_sizes: list[tuple[int, int]] = field(default_factory=list)

    def recognize(self, image: Image.Image) -> EngineOutput:
        self.calls += 1
        self.image_sizes.append(image.size)
        if not self.outputs:
            return EngineOutput(lines=())
        return self.outputs[min(self.calls, len(self.outputs)) - 1]


@dataclass
class FailingEngine:
    """Raises RuntimeError("engine failed") on the given call numbers, else delegates."""

    fail_calls: set[int]
    inner: RecognitionEngine
    calls: int = 0

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def version(self) -> str:
        return self.inner.version

    def recognize(self, image: Image.Image) -> EngineOutput:
        self.calls += 1
        if self.calls in self.fail_calls:
            raise RuntimeError("engine failed")
        return self.inner.recognize(image)


@dataclass
class InterruptingEngine:
    """Raises KeyboardInterrupt on call `after` (Ctrl-C in the middle of a run)."""

    after: int
    inner: RecognitionEngine
    calls: int = 0

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def version(self) -> str:
        return self.inner.version

    def recognize(self, image: Image.Image) -> EngineOutput:
        self.calls += 1
        if self.calls == self.after:
            raise KeyboardInterrupt
        return self.inner.recognize(image)
