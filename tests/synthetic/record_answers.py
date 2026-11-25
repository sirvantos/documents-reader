"""Record the real model's answers on synthetic contracts (level 2; feature 09, research R-9).

Run only where the model server runs — the analyst's Mac (quickstart Б2):

    DOCREADER_TEST_DATABASE_URL=postgresql:///postgres \\
      uv run python -m tests.synthetic.record_answers [VARIANT ...] \\
        --quantization "4 бита" --server "mlx_lm.server 0.32.2"

The contracts of `make_answer_contracts` are written into `--out` (default
`tests/synthetic/out/`), which must lie inside `tests/synthetic/` of this repository
(symlinks resolved): real contracts are never recorded (principle I, guard in code). They go
through the real pipeline (`add`, `read`, `parse`, `index`) in a throwaway database; the
search model and the reranker are the fakes of `tests/integration/answer_fixtures.py`, the
language model is the real one (`DOCREADER_RECORD_BASE_URL` or `[extraction] base_url`, on
this machine only). Each variant asks one question with `answer.ask`.

Recordings: `tests/recordings/09-text-answers/<variant>.json` (contracts/model.md). They are
never edited by hand.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from docreader import answer, answer_prompt, embedding, llm, reranker
from docreader.config import Settings, load_settings
from docreader.db import connect
from tests.fakes.embedding import TopicEmbedder
from tests.fakes.llm import write_recording
from tests.fakes.reranker import TableReranker
from tests.integration.answer_fixtures import ANSWER_SCORES, ANSWER_TOPICS, ANSWER_VARIANTS
from tests.synthetic import make_pdfs
from tests.synthetic.record_recognition import RefusedPath, check_paths
from tests.synthetic.recording import (
    RecordingRefused,
    RecordingTransport,
    TransportFactory,
    check_environment,
    run_step,
    throwaway_workspace,
)

__all__ = ["RECORDINGS_DIR", "SYNTHETIC_DIR", "load_settings", "main", "record"]

SYNTHETIC_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = SYNTHETIC_DIR.parent / "recordings" / "09-text-answers"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tests.synthetic.record_answers",
        description="Записать ответы модели на синтетических договорах (фича 09, уровень 2)",
    )
    # checked in main: argparse `choices` with nargs="*" rejects the empty list
    p.add_argument(
        "variants", nargs="*", metavar="ВАРИАНТ",
        help="варианты: " + ", ".join(ANSWER_VARIANTS) + "; без них — все",
    )
    p.add_argument("--out", help="папка для договоров внутри tests/synthetic/ (по умолчанию out/)")
    p.add_argument("--quantization", default="", help="степень сжатия модели, например «4 бита»")
    p.add_argument("--server", default="", help="способ запуска и версия сервера модели")
    return p


@contextmanager
def _fake_embedder_for_index(fake: TopicEmbedder) -> Iterator[None]:
    """`embedding.load_embedder` uses the fake's transport meanwhile (for `index`)."""
    original = embedding.load_embedder

    def load(settings, transport=None):
        return original(settings, fake.transport)

    embedding.load_embedder = load
    try:
        yield
    finally:
        embedding.load_embedder = original


def _answer_client(settings: Settings, transport: RecordingTransport) -> llm.ModelClient:
    return llm.load_client(
        dataclasses.replace(
            settings.extraction,
            max_tokens=settings.answer.max_tokens,
            max_retries=settings.answer.max_retries,
        ),
        transport=transport,
    )


def record(
    variants: Sequence[str],
    *,
    out_dir: Path,
    database_url: str,
    base_url: str,
    quantization: str,
    server: str,
    recordings_dir: Path,
    transport_factory: TransportFactory,
) -> list[Path]:
    """Run the contracts through the pipeline and write one recording per variant."""
    pdfs = make_pdfs.make_answer_contracts(out_dir)
    written: list[Path] = []
    with throwaway_workspace(database_url, base_url) as workspace:
        settings = load_settings(workspace.env)
        run_step("migrate", "migrate")
        for pdf in pdfs:  # in this order: D-0001, D-0002
            run_step("add", "add", str(pdf))
        run_step("read", "read")
        run_step("parse", "parse")
        with _fake_embedder_for_index(TopicEmbedder(ANSWER_TOPICS)):
            run_step("index", "index")
        for variant in variants:
            v = ANSWER_VARIANTS[variant]
            transport = RecordingTransport(transport_factory())
            client = _answer_client(settings, transport)
            embedder = embedding.load_embedder(
                settings.embedding, TopicEmbedder(ANSWER_TOPICS).transport
            )
            ranker = reranker.load_reranker(
                settings.reranker, TableReranker(ANSWER_SCORES).transport
            )
            with connect(settings) as conn:
                answer.ask(
                    conn, settings, v.question, document_id=v.document,
                    passages=v.passages, client=client, embedder=embedder, reranker=ranker,
                )
            written.append(_write(variant, settings, transport, quantization, server,
                                  recordings_dir))
    return written


def _write(
    variant: str,
    settings: Settings,
    transport: RecordingTransport,
    quantization: str,
    server: str,
    recordings_dir: Path,
) -> Path:
    extraction = settings.extraction
    path = recordings_dir / f"{variant}.json"
    write_recording(
        path,
        {
            "variant": variant,
            "generator_version": make_pdfs.ANSWER_GENERATOR_VERSION,
            "prompt_version": answer_prompt.PROMPT_VERSION,
            "prompt_sha256": answer_prompt.prompt_sha256(),
            "model": extraction.model,
            "served_model": transport.served_model,
            "quantization": quantization,
            "server": server,
            "settings": {
                "mode": extraction.mode,
                "temperature": extraction.temperature,
                "seed": extraction.seed,
                "max_tokens": settings.answer.max_tokens,
                "extra_body": dict(extraction.extra_body),
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
    unknown = [v for v in args.variants if v not in ANSWER_VARIANTS]
    if unknown:
        _parser().error(f"неизвестный вариант: {', '.join(unknown)}")
    out = Path(args.out) if args.out else synthetic_dir / "out"
    try:
        (out_dir,) = check_paths([out], synthetic_dir)  # before anything else is loaded
    except RefusedPath as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        checked = check_environment(env, transport_factory)
    except RecordingRefused as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    written = record(
        args.variants or list(ANSWER_VARIANTS),
        out_dir=out_dir,
        database_url=checked.database_url,
        base_url=checked.base_url,
        quantization=args.quantization,
        server=args.server,
        recordings_dir=recordings_dir,
        transport_factory=checked.transport_factory,
    )
    for path in written:
        print(f"Записано: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
