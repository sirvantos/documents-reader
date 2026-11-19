"""Record the real engine's answers on synthetic scans (level 2, research R-13; task T036).

Run only on the analyst's Mac, with the engine set in `[recognition]`:

    uv run python -m tests.synthetic.record_recognition [PATH ...]

Without paths, every variant of `make_scans` is generated into `tests/synthetic/out/`
and recorded. Every given path must lie inside `tests/synthetic/` of this repository
(symlinks resolved): real contracts are never recorded (principle I, guard in code).
The check runs before any settings or engine are loaded. On the development server the
engine guard (DOCREADER_FORBID_MODELS) stops the command.

Recordings: `tests/recordings/13-scan-recognition/<engine>/<variant>.json` with the
engine, its version, dpi, date, generator version and the raw engine output per page
(pixels of the rendered image). They are never edited by hand.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pypdfium2 as pdfium

from docreader import ocr_engines
from docreader.config import RecognitionSettings, load_settings
from docreader.errors import DocreaderError
from docreader.ocr import RecognitionEngine, render_page
from tests.synthetic import make_scans

SYNTHETIC_DIR = Path(__file__).resolve().parent
REPO_ROOT = SYNTHETIC_DIR.parents[1]
RECORDINGS_DIR = REPO_ROOT / "tests" / "recordings" / "13-scan-recognition"
REFUSED = "записываются только синтетические файлы из tests/synthetic/"

EngineFactory = Callable[[RecognitionSettings, Path], RecognitionEngine]


class RefusedPath(Exception):
    """A path outside tests/synthetic/ was given."""


def check_paths(paths: Sequence[str | Path], synthetic_dir: Path = SYNTHETIC_DIR) -> list[Path]:
    """Resolved paths, all inside `synthetic_dir`; otherwise RefusedPath."""
    root = synthetic_dir.resolve()
    checked = []
    for raw in paths:
        path = Path(raw).resolve()
        if not path.is_relative_to(root):
            raise RefusedPath(f"{raw}: {REFUSED}")
        checked.append(path)
    return checked


def _scan_pages(pdf_path: Path, page_count: int) -> list[int]:
    truth = pdf_path.with_suffix(".truth.json")
    if truth.is_file():
        pages = json.loads(truth.read_text(encoding="utf-8"))["pages"]
        return [p["page"] for p in pages if p["kind"] == "scan"]
    return list(range(1, page_count + 1))


def _variant(pdf_path: Path) -> str:
    truth = pdf_path.with_suffix(".truth.json")
    if truth.is_file():
        return str(json.loads(truth.read_text(encoding="utf-8"))["variant"])
    return pdf_path.stem


def record_file(pdf_path: Path, engine: RecognitionEngine, dpi: int) -> dict:
    """The recording of one synthetic PDF: engine output for each of its scan pages."""
    pdf = pdfium.PdfDocument(str(pdf_path))
    pages = []
    try:
        for number in _scan_pages(pdf_path, len(pdf)):
            page = pdf[number - 1]
            try:
                image = render_page(page, dpi)
            finally:
                page.close()
            output = engine.recognize(image)
            pages.append(
                {
                    "page": number,
                    "image_size": list(image.size),
                    "orientation": output.orientation,
                    "lines": [
                        {"text": ln.text, "box": list(ln.box), "confidence": ln.confidence}
                        for ln in output.lines
                    ],
                }
            )
    finally:
        pdf.close()
    return {
        "engine": engine.name,
        "engine_version": engine.version,
        "dpi": dpi,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator_version": make_scans.SCAN_GENERATOR_VERSION,
        "variant": _variant(pdf_path),
        "source": pdf_path.name,
        "pages": pages,
    }


def main(
    argv: Sequence[str] | None = None,
    *,
    synthetic_dir: Path = SYNTHETIC_DIR,
    recordings_dir: Path = RECORDINGS_DIR,
    settings: RecognitionSettings | None = None,
    data_dir: Path | None = None,
    engine_factory: EngineFactory | None = None,
) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        paths = check_paths(args, synthetic_dir)  # before anything else is loaded
    except RefusedPath as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        if settings is None or data_dir is None:
            loaded = load_settings()
            settings, data_dir = loaded.recognition, loaded.data_dir
        factory = engine_factory if engine_factory is not None else ocr_engines.load_engine
        engine = factory(settings, data_dir)
    except DocreaderError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    if not paths:
        paths = [p for p in make_scans.make_all(synthetic_dir / "out") if "scan" in p.name]
    target = recordings_dir / engine.name
    target.mkdir(parents=True, exist_ok=True)
    for pdf_path in paths:
        recording = record_file(pdf_path, engine, settings.dpi)
        out = target / f"{recording['variant']}.json"
        out.write_text(json.dumps(recording, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"Записано: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
