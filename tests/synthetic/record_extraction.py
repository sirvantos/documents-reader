"""Record the real model's answers on synthetic contracts (level 2; feature 05, R-2).

Run only where the model server runs — the analyst's Mac (quickstart Б2):

    DOCREADER_TEST_DATABASE_URL=postgresql:///postgres \\
      uv run python -m tests.synthetic.record_extraction [PATH ...] \\
        --quantization "4 бита" --server "llama.cpp <version>"

Without paths, every variant of `make_extraction_contracts` is generated into
`tests/synthetic/out/` and recorded. Every given path must lie inside `tests/synthetic/`
of this repository (symlinks resolved): real contracts are never recorded (principle I,
guard in code). The guards run before settings, the database or the model are touched:

1. paths inside tests/synthetic/ (exit 1 otherwise);
2. DOCREADER_TEST_DATABASE_URL set — the contracts go through the real pipeline in a
   throwaway database on that server (exit 2 otherwise);
3. the model address (DOCREADER_RECORD_BASE_URL, default `[extraction] base_url`) on this
   machine (exit 2 otherwise);
4. no real model where DOCREADER_FORBID_MODELS is set (exit 2).

Recordings: `tests/recordings/05-field-extraction/<variant>.json`
(contracts/model.md «Формат записи»). They are never edited by hand.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from docreader import extraction_prompt
from docreader.config import ExtractionSettings, load_settings
from tests.fakes.llm import RECORDINGS_DIR, request_sha256, write_recording
from tests.synthetic import make_pdfs
from tests.synthetic.record_recognition import RefusedPath, check_paths
from tests.synthetic.recording import (
    BASE_URL_ENV,
    TEST_DB_ENV,
    RecordingRefused,
    RecordingTransport,
    TransportFactory,
    check_environment,
    recording_client,
    run_step,
    throwaway_workspace,
)

__all__ = [
    "BASE_URL_ENV",
    "RECORDINGS_DIR",
    "SYNTHETIC_DIR",
    "TEST_DB_ENV",
    "load_settings",
    "main",
    "record",
    "request_sha256",
]

SYNTHETIC_DIR = Path(__file__).resolve().parent


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tests.synthetic.record_extraction",
        description="Записать ответы модели на синтетических договорах (фича 05, уровень 2)",
    )
    p.add_argument("paths", nargs="*", help="PDF внутри tests/synthetic/; без путей — все")
    p.add_argument("--quantization", default="", help="степень сжатия модели, например «4 бита»")
    p.add_argument("--server", default="", help="способ запуска и версия сервера модели")
    return p


def record(
    paths: Sequence[Path],
    *,
    database_url: str,
    base_url: str,
    quantization: str,
    server: str,
    synthetic_dir: Path,
    recordings_dir: Path,
    transport_factory: TransportFactory,
) -> list[Path]:
    """Run each contract through the pipeline and write its recording; T025."""
    pdfs = list(paths) or make_pdfs.make_extraction_contracts(synthetic_dir / "out")
    with throwaway_workspace(database_url, base_url) as workspace:
        settings = load_settings(workspace.env).extraction
        run_step("migrate", "migrate")
        return [
            _record_one(
                pdf, settings, workspace.database_url, quantization, server,
                recordings_dir, transport_factory,
            )
            for pdf in pdfs
        ]


def _record_one(
    pdf: Path,
    settings: ExtractionSettings,
    database_url: str,
    quantization: str,
    server: str,
    recordings_dir: Path,
    transport_factory: TransportFactory,
) -> Path:
    variant = pdf.stem
    run_step("add", "add", str(pdf))
    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute("SELECT id FROM document ORDER BY seq DESC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError(f"recording: step 'add' registered no document for {variant!r}")
    doc_id = row[0]
    run_step("read", "read")
    run_step("parse", "parse")
    transport = RecordingTransport(transport_factory())
    with recording_client(transport):
        run_step("extract", "extract", doc_id)
    path = recordings_dir / f"{variant}.json"
    write_recording(
        path,
        {
            "variant": variant,
            "generator_version": make_pdfs.GENERATOR_VERSION,
            "prompt_version": extraction_prompt.PROMPT_VERSION,
            "prompt_sha256": extraction_prompt.prompt_sha256(),
            "model": settings.model,
            "served_model": transport.served_model,
            "quantization": quantization,
            "server": server,
            "settings": {
                "mode": settings.mode,
                "temperature": settings.temperature,
                "seed": settings.seed,
                "max_tokens": settings.max_tokens,
                "extra_body": dict(settings.extra_body),
            },
            "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "exchanges": transport.exchanges,
        },
    )
    return path


def main(
    argv: Sequence[str] | None = None,
    *,
    synthetic_dir: Path = SYNTHETIC_DIR,
    recordings_dir: Path = RECORDINGS_DIR,
    env: Mapping[str, str] = os.environ,
    transport_factory: TransportFactory | None = None,
) -> int:
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        paths = check_paths(args.paths, synthetic_dir)  # before anything else is loaded
    except RefusedPath as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        checked = check_environment(env, transport_factory)
    except RecordingRefused as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    written = record(
        paths,
        database_url=checked.database_url,
        base_url=checked.base_url,
        quantization=args.quantization,
        server=args.server,
        synthetic_dir=synthetic_dir,
        recordings_dir=recordings_dir,
        transport_factory=checked.transport_factory,
    )
    for path in written:
        print(f"Записано: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
