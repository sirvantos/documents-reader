"""Shared guards and helpers of the recording commands (features 05 and 09; task T017).

`record_extraction` (feature 05) and `record_answers` (feature 09) record the real model's
answers on synthetic contracts only (principle I, guard in code; tech-context «Модели
в автотестах»). The checks run before settings, the database or the model are touched:

1. `DOCREADER_TEST_DATABASE_URL` set — the contracts go through the real pipeline in a
   throwaway database on that server (exit 2 otherwise);
2. the model address (`DOCREADER_RECORD_BASE_URL`, default `[extraction] base_url`) on this
   machine (exit 2 otherwise);
3. no real model where `DOCREADER_FORBID_MODELS` is set (exit 2).

The paths are checked by each command first (`record_recognition.check_paths`, exit 1).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from docreader import cli, llm
from docreader.config import ExtractionSettings, is_local_model_url
from docreader.guards import FORBID_MODELS_ENV, models_forbidden
from tests.fakes.llm import request_sha256

TEST_DB_ENV = "DOCREADER_TEST_DATABASE_URL"
BASE_URL_ENV = "DOCREADER_RECORD_BASE_URL"

TransportFactory = Callable[[], httpx2.BaseTransport]


class RecordingRefused(Exception):
    """The environment does not allow a recording; `code` is the exit code."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RecordingEnvironment:
    database_url: str
    base_url: str
    transport_factory: TransportFactory


def check_environment(
    env: Mapping[str, str], transport_factory: TransportFactory | None
) -> RecordingEnvironment:
    """Checks 1–3 of the module docstring, in this order; RecordingRefused on the first."""
    database_url = env.get(TEST_DB_ENV, "").strip()
    if not database_url:
        raise RecordingRefused(
            f"Не задана {TEST_DB_ENV} — нужна локальная PostgreSQL с правом CREATEDB "
            "для временной базы записи"
        )
    base_url, transport_factory = check_model_environment(env, transport_factory)
    return RecordingEnvironment(database_url, base_url, transport_factory)


def check_model_environment(
    env: Mapping[str, str], transport_factory: TransportFactory | None
) -> tuple[str, TransportFactory]:
    """Checks 2–3 of the module docstring (a recording without a database, feature 10)."""
    base_url = env.get(BASE_URL_ENV, "").strip() or ExtractionSettings().base_url
    if not is_local_model_url(base_url):
        raise RecordingRefused(
            f"{BASE_URL_ENV}={base_url!r} — адрес модели не на этой машине; "
            "укажите localhost, 127.0.0.1 или ::1 (принцип I)"
        )
    if transport_factory is None:
        if models_forbidden(env):
            raise RecordingRefused(
                f"На этой машине языковая модель не запускается ({FORBID_MODELS_ENV}) — "
                "ответы записываются на ноутбуке аналитика"
            )
        transport_factory = httpx2.HTTPTransport
    return base_url, transport_factory


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
def environment(values: Mapping[str, str]) -> Iterator[None]:
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
def recording_client(transport: RecordingTransport) -> Iterator[None]:
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


def run_step(step: str, *args: str) -> None:
    """One pipeline command in-process; its output (contract text) is not shown."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        code = cli.main(list(args))
    if code != 0:
        raise RuntimeError(f"recording: step {step!r} failed with exit code {code}")


@dataclass(frozen=True)
class Workspace:
    """The throwaway data dir and database of one recording run."""

    data_dir: Path
    database_url: str
    env: dict[str, str]


@contextlib.contextmanager
def throwaway_workspace(database_url: str, base_url: str) -> Iterator[Workspace]:
    """A database `docreader_record_<pid>` and a temporary data dir with `[extraction]
    base_url`; the environment points at both meanwhile; both are dropped after."""
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
            with environment(env):
                yield Workspace(data_dir, record_url, env)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )
