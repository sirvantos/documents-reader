"""Recognition engine adapters and the guards around loading them (research R-3, R-4).

The only place that names engine libraries. Every adapter is loaded through
`load_engine`, which refuses to run on a machine where DOCREADER_FORBID_MODELS is set
(the development server, Docker, the test suite) and switches network and telemetry off
before the engine library is imported. Engine libraries are imported lazily inside the
factories; they are an optional dependency group (`uv sync --group ocr`).
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable, Sequence
from itertools import pairwise
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


Word = tuple[str, float, Sequence[float]]  # text, confidence 0..100, (l, t, r, b) px
Line = tuple[str, float, Sequence[float], Sequence[Word]]  # Tesseract's line and its words

# A gap between two words wider than this many word heights ends a segment: Tesseract
# joins the two columns of a signature block or the cells of a table row into one line,
# while justified text stretches spaces to about two heights (tuned by measurement).
GAP_FACTOR = 3.0
# Below this OSD confidence the orientation is treated as unknown and the trial decides.
# Measured 2026-11-22: readable scans give ≥ 13 (≥ 19.9 on the working set); on a ~100 dpi
# scan OSD said 180° at 2.0–3.7 and all twelve such turns were wrong.
OSD_MIN_CONFIDENCE = 5.0


def split_wide_gaps(
    lines: Iterable[Line], gap: float = GAP_FACTOR
) -> list[tuple[str, float, Sequence[float]]]:
    """Each Tesseract line, or its segments where the words are more than `gap` heights apart.

    A line without such a gap is kept exactly as Tesseract gave it. A segment gets its words
    joined by one space, the union of their boxes and their confidence weighted by length.
    """
    result: list[tuple[str, float, Sequence[float]]] = []
    for text, confidence, box, words in lines:
        words = [w for w in words if w[0].strip()]
        if not words:
            result.append((text, confidence, box))
            continue
        height = sorted(w[2][3] - w[2][1] for w in words)[len(words) // 2]
        segments: list[list[Word]] = [[words[0]]]
        for previous, word in pairwise(words):
            if word[2][0] - previous[2][2] > gap * height:
                segments.append([word])
            else:
                segments[-1].append(word)
        if len(segments) == 1:
            result.append((text, confidence, box))
            continue
        for segment in segments:
            size = sum(len(w[0]) for w in segment)
            result.append(
                (
                    " ".join(w[0] for w in segment),
                    sum(w[1] * len(w[0]) for w in segment) / size,
                    (
                        min(w[2][0] for w in segment),
                        min(w[2][1] for w in segment),
                        max(w[2][2] for w in segment),
                        max(w[2][3] for w in segment),
                    ),
                )
            )
    return result


# --- the chosen adapter (research R-1, decision 2026-11-20) ------------------------------


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
        # Orientation from Tesseract's own detector when its data is there (R-6): the turn
        # trial alone is misled, because Tesseract reads sideways text as well.
        self._osd: Any = None
        if "osd" in languages:
            osd = Path(path) / "osd.traineddata"
            osd_digest = hashlib.sha256(osd.read_bytes()).hexdigest()[:12] if osd.is_file() else "?"
            self.version += f" osd {osd_digest}"
            self._osd = tesserocr.PyTessBaseAPI(
                path=path, lang="osd", psm=tesserocr.PSM.OSD_ONLY
            )

    def recognize(self, image: Image.Image) -> EngineOutput:
        tesserocr = self._tesserocr
        self._api.SetImage(image)
        self._api.Recognize()
        heads: list[tuple[str, float, Sequence[float]]] = []
        words: list[list[Word]] = []
        for word in tesserocr.iterate_level(self._api.GetIterator(), tesserocr.RIL.WORD):
            if word.IsAtBeginningOf(tesserocr.RIL.TEXTLINE):
                line_box = word.BoundingBox(tesserocr.RIL.TEXTLINE) or (0, 0, 0, 0)
                line_text = _text(word, tesserocr.RIL.TEXTLINE)
                heads.append((line_text, word.Confidence(tesserocr.RIL.TEXTLINE), line_box))
                words.append([])
            text = _text(word, tesserocr.RIL.WORD)
            box = word.BoundingBox(tesserocr.RIL.WORD)
            if words and text and box is not None:
                words[-1].append((text, word.Confidence(tesserocr.RIL.WORD), box))
        lines = [(*head, line_words) for head, line_words in zip(heads, words, strict=True)]
        return EngineOutput(
            lines=tesseract_lines(split_wide_gaps(lines, GAP_FACTOR)),
            orientation=self._orientation(image),
        )

    def _orientation(self, image: Image.Image) -> int | None:
        """0/90/180/270 the text is turned clockwise, or None if OSD is absent or unsure."""
        if self._osd is None:
            return None
        try:
            self._osd.SetImage(image)
            found = self._osd.DetectOrientationScript()
        except RuntimeError:
            return None
        if not found or found.get("orient_conf", 0.0) < OSD_MIN_CONFIDENCE:
            return None
        degrees = int(found["orient_deg"])
        return degrees if degrees in (0, 90, 180, 270) else None


def _text(position: Any, level: Any) -> str:
    """Text at the iterator position; tesserocr raises "No text returned" on an empty one."""
    try:
        return str(position.GetUTF8Text(level) or "")
    except RuntimeError:
        return ""


def _load_tesseract(settings: RecognitionSettings, data_dir: Path) -> RecognitionEngine:
    return _Tesseract(settings)


# name -> factory (contracts/engine.md); the next queue is added only after measurement.
ENGINES: dict[str, EngineFactory] = {
    "tesseract": _load_tesseract,
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
            f"Движок {name} не установлен ({exc}) — выполните "
            "uv sync --group ocr"
        ) from exc
