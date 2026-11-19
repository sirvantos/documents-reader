"""Recognition engine adapters and the guards around loading them (research R-3, R-4).

The only place that names engine libraries. Every adapter is loaded through
`load_engine`, which refuses to run on a machine where DOCREADER_FORBID_MODELS is set
(the development server, Docker, the test suite) and switches network and telemetry off
before the engine library is imported. Engine libraries are imported lazily inside the
factories; they are an optional dependency group (`uv sync --group ocr`, Mac only).
"""

from __future__ import annotations

import hashlib
import io
import os
import platform
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from docreader.config import RecognitionSettings
from docreader.errors import EnvironmentProblem
from docreader.ocr import EngineLine, EngineOutput, PixelBox, RecognitionEngine

if TYPE_CHECKING:
    from PIL import Image

EngineFactory = Callable[[RecognitionSettings, Path], RecognitionEngine]

FORBID_MODELS_ENV = "DOCREADER_FORBID_MODELS"
# Set before an engine library is imported; libraries that would download a model or
# send telemetry read them (principle I).
OFFLINE_ENV = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "DISABLE_TELEMETRY": "1",
}

# --- pure conversions (tested on the server without any engine) ----------------------------


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _pixel_box(box: Iterable[float]) -> PixelBox:
    left, top, right, bottom = (float(v) for v in box)
    return (left, top, right, bottom)


def tesseract_lines(items: Iterable[tuple[str, float, Iterable[float]]]) -> tuple[EngineLine, ...]:
    """(text, confidence 0..100, (left, top, right, bottom) px) per text line."""
    lines = []
    for text, confidence, box in items:
        text = text.rstrip("\n")
        if text.strip():
            lines.append(EngineLine(text, _pixel_box(box), _clamp(confidence / 100)))
    return tuple(lines)


def vision_lines(
    items: Iterable[tuple[str, float, tuple[float, float, float, float]]],
    *,
    size: tuple[int, int],
) -> tuple[EngineLine, ...]:
    """(text, confidence 0..1, normalised (x, y, w, h) with a bottom-left origin)."""
    width, height = size
    lines = []
    for text, confidence, (x, y, w, h) in items:
        if text.strip():
            box = (x * width, (1 - y - h) * height, (x + w) * width, (1 - y) * height)
            lines.append(EngineLine(text, box, _clamp(confidence)))
    return tuple(lines)


# --- queue 1 adapters (research R-1); they run only on the analyst's Mac -------------------


class _Tesseract:
    """Tesseract 5 through tesserocr (C API, image in memory, no temp files)."""

    name = "tesseract"

    def __init__(self, settings: RecognitionSettings) -> None:
        import tesserocr  # lazy: optional group `ocr`

        self._tesserocr = tesserocr
        # tesserocr's `path` defaults to its built-in tessdata path; an explicit None is a
        # TypeError there, so the argument is passed only when model_dir is set.
        if settings.model_dir:
            path, languages = tesserocr.get_languages(settings.model_dir)
        else:
            path, languages = tesserocr.get_languages()
        if "rus" not in languages:
            raise EnvironmentProblem(
                f"Движок tesseract: нет языковых данных rus в {path} — на ноутбуке: "
                "brew install tesseract-lang (или укажите [recognition] model_dir)"
            )
        data = Path(path) / "rus.traineddata"
        digest = hashlib.sha256(data.read_bytes()).hexdigest()[:12] if data.is_file() else "?"
        engine = tesserocr.tesseract_version().splitlines()[0].replace("tesseract ", "")
        self.version = f"{engine} rus {digest}"
        self._api = tesserocr.PyTessBaseAPI(path=path, lang="rus")

    def recognize(self, image: Image.Image) -> EngineOutput:
        tesserocr = self._tesserocr
        level = tesserocr.RIL.TEXTLINE
        self._api.SetImage(image)
        self._api.Recognize()
        items: list[tuple[str, float, Iterable[float]]] = []
        iterator = self._api.GetIterator()
        for line in tesserocr.iterate_level(iterator, level):
            text = line.GetUTF8Text(level) or ""
            box = line.BoundingBox(level)
            if box is not None:
                items.append((text, line.Confidence(level), box))
        return EngineOutput(lines=tesseract_lines(items))


def _load_tesseract(settings: RecognitionSettings, data_dir: Path) -> RecognitionEngine:
    return _Tesseract(settings)


class _AppleVision:
    """Apple Vision text recognition (macOS only), language correction off (FR-010)."""

    name = "apple_vision"

    def __init__(self) -> None:
        import Quartz  # lazy: optional group `ocr`, macOS only
        import Vision

        self._quartz = Quartz
        self._vision = Vision
        self.version = f"macOS {platform.mac_ver()[0]}"

    def _cg_image(self, image: Image.Image) -> Any:
        from Foundation import NSData

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")  # in memory, nothing written to disk
        data = NSData.dataWithBytes_length_(buffer.getvalue(), len(buffer.getvalue()))
        source = self._quartz.CGImageSourceCreateWithData(data, None)
        return self._quartz.CGImageSourceCreateImageAtIndex(source, 0, None)

    def recognize(self, image: Image.Image) -> EngineOutput:
        vision = self._vision
        request = vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(vision.VNRequestTextRecognitionLevelAccurate)
        request.setRecognitionLanguages_(["ru-RU"])
        request.setUsesLanguageCorrection_(False)
        handler = vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            self._cg_image(image), None
        )
        ok, error = handler.performRequests_error_([request], None)
        if not ok:
            raise RuntimeError(f"Vision: {error}")
        items = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            best = candidates[0]
            rect = observation.boundingBox()
            items.append(
                (
                    str(best.string()),
                    float(best.confidence()),
                    (rect.origin.x, rect.origin.y, rect.size.width, rect.size.height),
                )
            )
        return EngineOutput(lines=vision_lines(items, size=image.size))


def _load_apple_vision(settings: RecognitionSettings, data_dir: Path) -> RecognitionEngine:
    if sys.platform != "darwin":
        raise EnvironmentProblem("Движок apple_vision работает только на macOS")
    return _AppleVision()


# name -> factory (contracts/engine.md); the next queue is added only after measurement.
ENGINES: dict[str, EngineFactory] = {
    "tesseract": _load_tesseract,
    "apple_vision": _load_apple_vision,
}


def load_engine(settings: RecognitionSettings, data_dir: Path) -> RecognitionEngine:
    """The engine named in `[recognition] engine`, or EnvironmentProblem with a hint."""
    name = settings.engine.strip()
    if not name:
        raise EnvironmentProblem(
            "Не выбран движок распознавания — укажите [recognition] engine в settings.toml "
            "(выбор — замером, quickstart Б1)"
        )
    factory = ENGINES.get(name)
    if factory is None:
        known = ", ".join(sorted(ENGINES)) or "нет"
        raise EnvironmentProblem(
            f"Неизвестный движок распознавания «{name}» — известные: {known}"
        )
    if os.environ.get(FORBID_MODELS_ENV, "").strip():
        raise EnvironmentProblem(
            "На этой машине движок распознавания не запускается (DOCREADER_FORBID_MODELS)"
        )
    os.environ.update(OFFLINE_ENV)
    try:
        return factory(settings, data_dir)
    except ImportError as exc:
        raise EnvironmentProblem(
            f"Движок {name} не установлен ({exc}) — на ноутбуке выполните "
            "uv sync --group ocr"
        ) from exc
