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
import contextlib
import io
import json
import os
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from docreader import cli, extraction_prompt, llm
from docreader.config import ExtractionSettings, is_local_model_url, load_settings
from docreader.guards import FORBID_MODELS_ENV, models_forbidden
from tests.fakes.llm import RECORDINGS_DIR, request_sha256, write_recording
from tests.synthetic import make_pdfs
from tests.synthetic.record_recognition import RefusedPath, check_paths

__all__ = ["RECORDINGS_DIR", "SYNTHETIC_DIR", "load_settings", "main", "record", "request_sha256"]

SYNTHETIC_DIR = Path(__file__).resolve().parent
TEST_DB_ENV = "DOCREADER_TEST_DATABASE_URL"
BASE_URL_ENV = "DOCREADER_RECORD_BASE_URL"

TransportFactory = Callable[[], httpx2.BaseTransport]


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m tests.synthetic.record_extraction",
        description="Записать ответы модели на синтетических договорах (фича 05, уровень 2)",
    )
    p.add_argument("paths", nargs="*", help="PDF внутри tests/synthetic/; без путей — все")
    p.add_argument("--quantization", default="", help="степень сжатия модели, например «4 бита»")
    p.add_argument("--server", default="", help="способ запуска и версия сервера модели")
    return p


class RecordingTransport(httpx2.BaseTransport):
    """Forwards requests to `inner` and keeps every chat answer with its request fingerprint."""

    def __init__(self, inner: httpx2.BaseTransport) -> None:
        self._inner = inner
        self.exchanges: list[dict[str, Any]] = []
        self.served_model = ""

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        response = self._inner.handle_request(request)
        is_chat = request.method == "POST" and request.url.path.endswith("/chat/completions")
        is_models = request.method == "GET" and request.url.path.endswith("/models")
        if not (is_chat or is_models):
            return response
        response.read()
        if response.status_code == 200:
            body = json.loads(response.content)
            if is_chat:
                self.exchanges.append(
                    {
                        "request_sha256": request_sha256(json.loads(request.content)),
                        "attempt": len(self.exchanges) + 1,
                        "response": body,
                    }
                )
            elif body.get("data"):
                self.served_model = str(body["data"][0].get("id", ""))
        skip = {"content-encoding", "content-length", "transfer-encoding"}
        headers = [(k, v) for k, v in response.headers.items() if k.lower() not in skip]
        return httpx2.Response(response.status_code, headers=headers, content=response.content)


@contextlib.contextmanager
def _environment(values: Mapping[str, str]) -> Iterator[None]:
    """Set `values` in os.environ (DOCREADER_FORBID_MODELS removed) and restore it after."""
    saved = dict(os.environ)
    os.environ.update(values)
    os.environ.pop(FORBID_MODELS_ENV, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


@contextlib.contextmanager
def _recording_client(transport: RecordingTransport) -> Iterator[None]:
    """`llm.load_client` builds its client on the recording transport meanwhile."""
    original = llm.load_client

    def load_client(
        settings: ExtractionSettings, transport_: httpx2.BaseTransport | None = None
    ) -> llm.ModelClient:
        return original(settings, transport=transport)

    llm.load_client = load_client
    try:
        yield
    finally:
        llm.load_client = original


def _run(step: str, *args: str) -> None:
    """One pipeline command in-process; its output (contract text) is not shown."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(args))
    if code != 0:
        raise RuntimeError(f"recording: step {step!r} failed with exit code {code}")


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
    name = f"docreader_record_{os.getpid()}"
    admin_url = make_conninfo(database_url, dbname="postgres")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with tempfile.TemporaryDirectory(prefix="docreader-record-") as tmp:
            data_dir = Path(tmp)
            (data_dir / "settings.toml").write_text(
                f'[extraction]\nbase_url = "{base_url}"\n', encoding="utf-8"
            )
            record_url = make_conninfo(database_url, dbname=name)
            env = {"DOCREADER_DATA_DIR": str(data_dir), "DOCREADER_DATABASE_URL": record_url}
            with _environment(env):
                settings = load_settings(env).extraction
                _run("migrate", "migrate")
                return [
                    _record_one(
                        pdf, settings, record_url, quantization, server,
                        recordings_dir, transport_factory,
                    )
                    for pdf in pdfs
                ]
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


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
    _run("add", "add", str(pdf))
    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute("SELECT id FROM document ORDER BY seq DESC LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError(f"recording: step 'add' registered no document for {variant!r}")
    doc_id = row[0]
    _run("read", "read")
    _run("parse", "parse")
    transport = RecordingTransport(transport_factory())
    with _recording_client(transport):
        _run("extract", "extract", doc_id)
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
    database_url = env.get(TEST_DB_ENV, "").strip()
    if not database_url:
        print(
            f"Не задана {TEST_DB_ENV} — нужна локальная PostgreSQL с правом CREATEDB "
            "для временной базы записи",
            file=sys.stderr,
        )
        return 2
    base_url = env.get(BASE_URL_ENV, "").strip() or ExtractionSettings().base_url
    if not is_local_model_url(base_url):
        print(
            f"{BASE_URL_ENV}={base_url!r} — адрес модели не на этой машине; "
            "укажите localhost, 127.0.0.1 или ::1 (принцип I)",
            file=sys.stderr,
        )
        return 2
    if transport_factory is None:
        if models_forbidden(env):
            print(
                f"На этой машине языковая модель не запускается ({FORBID_MODELS_ENV}) — "
                "ответы записываются на ноутбуке аналитика",
                file=sys.stderr,
            )
            return 2
        transport_factory = httpx2.HTTPTransport
    written = record(
        paths,
        database_url=database_url,
        base_url=base_url,
        quantization=args.quantization,
        server=args.server,
        synthetic_dir=synthetic_dir,
        recordings_dir=recordings_dir,
        transport_factory=transport_factory,
    )
    for path in written:
        print(f"Записано: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
