"""Hand-written recognition engines for tests (level 1, research R-13; contracts/engine.md).

No real engine is ever imported here. Every fake has `name` and `version` and records
the images it got, so tests can count calls and check image sizes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from docreader.config import RecognitionSettings
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
    A run that resumes in the middle of a document needs its own `pages`; calls beyond
    them (the turn trial of a weak page) answer the last page again. A truth line
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
        order = self._page_order()
        number = order[min(self.calls, len(order)) - 1]  # extra calls (turn trial): last page
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


# --- RecordedEngine (level 2, task T037) ---------------------------------------------------

STALE_HINT = (
    "запись устарела (или отсутствует) — перезапишите её: "
    "uv run python -m tests.synthetic.record_recognition (quickstart Б3)"
)
THUMB_SIZE = (32, 32)
# Mean absolute grey difference (0..255) of two thumbnails that still show the same image:
# the same page rendered by another pdfium build differs by a few levels at most, while
# another page or another turn of the same page differs by tens.
MAX_THUMB_DIFF = 8.0


class StaleRecording(AssertionError):
    """The recording is missing or does not match the settings: the test fails, not skips."""


def thumbnail(image: Image.Image) -> str:
    """A 32x32 grey thumbnail as hex: enough to tell pages and turns apart."""
    return image.convert("L").resize(THUMB_SIZE, Image.Resampling.BOX).tobytes().hex()


class RecordedEngine:
    """Answers with the recorded output of a real engine (`record_recognition`).

    A recording holds, per scan page, the engine output on the image turned 0, 90, 180
    and 270 degrees with a thumbnail of each image. `recognize` returns the output of the
    entry with the same image size whose thumbnail is closest; an image without such an
    entry is a miss (`misses`, LookupError). The recording must match the engine and dpi
    of `settings` and the current `SCAN_GENERATOR_VERSION`, otherwise StaleRecording.
    """

    def __init__(self, path: str | Path, settings: RecognitionSettings) -> None:
        from tests.synthetic import make_scans

        path = Path(path)
        if not path.is_file():
            raise StaleRecording(f"{path.name}: {STALE_HINT}")
        data = json.loads(path.read_text(encoding="utf-8"))
        got = (data["engine"], data["dpi"], data["generator_version"])
        expected = (settings.engine, settings.dpi, make_scans.SCAN_GENERATOR_VERSION)
        if got != expected:
            raise StaleRecording(
                f"{path.name}: {STALE_HINT}; в записи (движок, dpi, генератор) = {got}, "
                f"нужно {expected}"
            )
        self.name: str = data["engine"]
        self.version: str = data["engine_version"]
        self.calls = 0
        self.misses: list[tuple[int, int]] = []
        self._entries = [
            (
                (turn["image_size"][0], turn["image_size"][1]),
                bytes.fromhex(turn["thumb"]),
                EngineOutput(
                    lines=tuple(
                        EngineLine(ln["text"], tuple(ln["box"]), ln["confidence"])
                        for ln in turn["lines"]
                    ),
                    orientation=turn["orientation"],
                ),
            )
            for page in data["pages"]
            for turn in page["turns"]
        ]

    def recognize(self, image: Image.Image) -> EngineOutput:
        self.calls += 1
        thumb = bytes.fromhex(thumbnail(image))
        width, height = image.size
        best: tuple[float, EngineOutput] | None = None
        for (w, h), recorded, output in self._entries:
            if abs(w - width) > 2 or abs(h - height) > 2:
                continue
            diff = sum(abs(a - b) for a, b in zip(recorded, thumb, strict=True)) / len(thumb)
            if best is None or diff < best[0]:
                best = (diff, output)
        if best is None or best[0] > MAX_THUMB_DIFF:
            self.misses.append(image.size)
            raise LookupError(f"no recorded answer for an image of size {image.size}")
        return best[1]
