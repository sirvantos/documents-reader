"""Hand-written recognition engines for tests (level 1, research R-13; contracts/engine.md).

No real engine is ever imported here. Every fake has `name` and `version` and records
the images it got, so tests can count calls and check image sizes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from docreader.ocr import EngineLine, EngineOutput, RecognitionEngine, display_point


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


# --- TruthEngine (task T012) -----------------------------------------------------------

A4 = (595.0, 842.0)


def pdf_box_to_image(
    bbox: Sequence[float],
    *,
    image_size: tuple[int, int],
    rotation: int,
    page_size: tuple[float, float] = A4,
) -> tuple[float, float, float, float]:
    """Unrotated PDF box → pixels of the image rendered in display orientation (turn 0).

    The inverse of `docreader.ocr.image_box_to_pdf` with `turn = 0` and a CropBox at 0, 0.
    """
    width, height = page_size
    disp_w, disp_h = (height, width) if rotation in (90, 270) else (width, height)
    scale = image_size[0] / disp_w
    xs: list[float] = []
    ys: list[float] = []
    for x in (bbox[0], bbox[2]):
        for y in (bbox[1], bbox[3]):
            dx, dy = display_point(x, y, rotation, width, height)
            xs.append(dx * scale)
            ys.append((disp_h - dy) * scale)
    return (min(xs), min(ys), max(xs), max(ys))


@dataclass
class TruthEngine:
    """The ideal engine: the exact truth lines of a generated scan, with their boxes.

    `truth` is a parsed `<name>.truth.json` of `tests/synthetic/make_scans.py`. Call k
    answers for page `pages[k - 1]`; by default the scan pages of the truth, in order.
    A run that resumes in the middle of a document needs its own `pages`. A truth line
    may carry its own `confidence`; otherwise `confidence` applies.
    """

    truth: Mapping[str, Any]
    pages: Sequence[int] | None = None
    rotations: Mapping[int, int] = field(default_factory=dict)
    confidence: float = 0.99
    name: str = "truth"
    version: str = "1"
    calls: int = 0
    image_sizes: list[tuple[int, int]] = field(default_factory=list)

    def _page_order(self) -> list[int]:
        if self.pages is not None:
            return list(self.pages)
        return [p["page"] for p in self.truth["pages"] if p["kind"] == "scan"]

    def recognize(self, image: Image.Image) -> EngineOutput:
        self.calls += 1
        self.image_sizes.append(image.size)
        number = self._page_order()[self.calls - 1]
        page = next(p for p in self.truth["pages"] if p["page"] == number)
        rotation = self.rotations.get(number, 0)
        return EngineOutput(
            lines=tuple(
                EngineLine(
                    text=line["text"],
                    box=pdf_box_to_image(line["bbox"], image_size=image.size, rotation=rotation),
                    confidence=line.get("confidence", self.confidence),
                )
                for line in page["lines"]
            )
        )


# --- engine factory spy -------------------------------------------------------------------


class EngineFactorySpy:
    """Stands in for `ocr_engines.load_engine`: hands out the given engines, one per call."""

    def __init__(self, *engines: Any) -> None:
        self.engines = list(engines)
        self.calls = 0

    def __call__(self, settings: Any, data_dir: Any) -> Any:
        self.calls += 1
        return self.engines[min(self.calls, len(self.engines)) - 1]
