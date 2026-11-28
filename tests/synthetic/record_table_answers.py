"""Record the real model's replies to synthetic table questions (level 2; feature 10, R-11).

Run only where the model server runs — the analyst's Mac (quickstart Б2):

    uv run python -m tests.synthetic.record_table_answers [VARIANT ...] \\
      --quantization "4 бита" --server "mlx_lm.server 0.32.2"

The questions come from `--questions` (default `tests/synthetic/table_questions.toml`),
which must lie inside `tests/synthetic/` of this repository (symlinks resolved): real
questions are never recorded (principle I, guard in code). No database and no contracts:
the model sees only the question and the date, so each variant goes through
`table_answer.translate` (model, check, one retry) with today fixed at 2026-11-28. The
model is the real one (`DOCREADER_RECORD_BASE_URL` or `[extraction] base_url` by default,
on this machine only), with the default settings, as the level 2 tests use them.

Recordings: `tests/recordings/10-table-answers/<variant>.json` (contracts/model.md). They are
never edited by hand.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from docreader import llm, table_answer, table_prompt
from docreader.config import ExtractionSettings, TableSettings
from tests.fakes.llm import write_recording
from tests.synthetic.record_recognition import RefusedPath, check_paths
from tests.synthetic.recording import (
    RecordingRefused,
    RecordingTransport,
    TransportFactory,
    check_model_environment,
)

__all__ = ["QUESTIONS_VERSION", "RECORDINGS_DIR", "SYNTHETIC_DIR", "TODAY", "main", "record"]

SYNTHETIC_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = SYNTHETIC_DIR.parent / "recordings" / "10-table-answers"
QUESTIONS_FILE = "table_questions.toml"
QUESTIONS_VERSION = 1  # raise when a question of the file changes: recordings go stale
TODAY = date(2026, 11, 28)
RERECORD = "uv run python -m tests.synthetic.record_table_answers"


@dataclass(frozen=True)
class Variant:
    name: str
    question: str
    expected: dict[str, Any] | None
    alternatives: tuple[dict[str, Any], ...]
    expected_outcome: str | None
    expected_other: bool


def load_variants(path: Path) -> dict[str, Variant]:
    """The variants of a questions file, by name, in file order."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    out: dict[str, Variant] = {}
    for item in data.get("variant", []):
        out[item["name"]] = Variant(
            name=item["name"],
            question=item["question"],
            expected=item.get("expected"),
            alternatives=tuple(item.get("alternatives", ())),
            expected_outcome=item.get("expected_outcome"),
            expected_other=bool(item.get("expected_other", False)),
        )
    return out


def model_settings(base_url: str | None = None) -> ExtractionSettings:
    """The default `[extraction]` with the `[table]` limits (as `ask_table` builds them)."""
    table = TableSettings()
    extraction = ExtractionSettings()
    if base_url is not None:
        extraction = dataclasses.replace(extraction, base_url=base_url)
    return dataclasses.replace(
        extraction, max_tokens=table.max_tokens, max_retries=table.max_retries
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tests.synthetic.record_table_answers",
        description="Записать ответы модели на синтетические вопросы к таблице (фича 10)",
    )
    p.add_argument("variants", nargs="*", metavar="ВАРИАНТ", help="варианты; без них — все")
    p.add_argument("--questions", help="файл вопросов внутри tests/synthetic/")
    p.add_argument("--quantization", default="", help="степень сжатия модели, например «4 бита»")
    p.add_argument("--server", default="", help="способ запуска и версия сервера модели")
    return p


def record(
    variants: Sequence[Variant],
    *,
    base_url: str,
    quantization: str,
    server: str,
    recordings_dir: Path,
    transport_factory: TransportFactory,
) -> list[Path]:
    """One recording per variant: the exchanges of `table_answer.translate`."""
    settings = model_settings(base_url)
    written: list[Path] = []
    for variant in variants:
        transport = RecordingTransport(transport_factory())
        client = llm.load_client(settings, transport=transport)
        client.check()
        table_answer.translate(client, variant.question, TODAY)
        path = recordings_dir / f"{variant.name}.json"
        write_recording(
            path,
            {
                "variant": variant.name,
                "generator_version": QUESTIONS_VERSION,
                "prompt_version": table_prompt.PROMPT_VERSION,
                "prompt_sha256": table_prompt.prompt_sha256(),
                "today": TODAY.isoformat(),
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
        written.append(path)
    return written


def main(
    argv: Sequence[str] | None = None,
    *,
    synthetic_dir: Path = SYNTHETIC_DIR,
    recordings_dir: Path = RECORDINGS_DIR,
    env: Mapping[str, str] = os.environ,
    transport_factory: TransportFactory | None = None,
) -> int:
    args = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    questions = Path(args.questions) if args.questions else synthetic_dir / QUESTIONS_FILE
    try:
        (path,) = check_paths([questions], synthetic_dir)  # before anything else is loaded
    except RefusedPath as exc:
        print(str(exc), file=sys.stderr)
        return 1
    variants = load_variants(path)
    unknown = [v for v in args.variants if v not in variants]
    if unknown:
        _parser().error(f"неизвестный вариант: {', '.join(unknown)}")
    try:
        base_url, factory = check_model_environment(env, transport_factory)
    except RecordingRefused as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    chosen = [variants[v] for v in args.variants] if args.variants else list(variants.values())
    written = record(
        chosen,
        base_url=base_url,
        quantization=args.quantization,
        server=args.server,
        recordings_dir=recordings_dir,
        transport_factory=factory,
    )
    for p in written:
        print(f"Записано: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
