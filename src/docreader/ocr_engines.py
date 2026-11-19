"""Recognition engine adapters and the guards around loading them (research R-3, R-4).

The only place that names engine libraries. Every adapter is loaded through
`load_engine`, which refuses to run on a machine where DOCREADER_FORBID_MODELS is set
(the development server, Docker, the test suite) and switches network and telemetry off
before the engine library is imported. Engine libraries are imported lazily inside the
factories; they are an optional dependency group (`uv sync --group ocr`, Mac only).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from docreader.config import RecognitionSettings
from docreader.errors import EnvironmentProblem
from docreader.ocr import RecognitionEngine

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

# name -> factory; adapters of queue 1 are added with the measurement step (task T031).
ENGINES: dict[str, EngineFactory] = {}


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
