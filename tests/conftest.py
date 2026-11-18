"""Shared test infrastructure (task T014).

- Integration tests run against a throwaway PostgreSQL database created from
  DOCREADER_TEST_DATABASE_URL (a local server with the right to create databases).
  Without that variable they fail with a clear message instead of being skipped.
- Every test gets an empty registry, a temporary data folder outside the repository
  and a `cli` helper that calls docreader.cli.main in-process.
- An autouse guard makes any non-local network connection fail (FR-013).
"""

from __future__ import annotations

import contextlib
import io
import ipaddress
import os
import socket
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from docreader import db as dbmod
from docreader.config import _check_local_database

TEST_DB_ENV = "DOCREADER_TEST_DATABASE_URL"
INTEGRATION_DIR = Path(__file__).resolve().parent / "integration"
REGISTRY_TABLES = (
    "run",
    "document",
    "page",
    "stage_status",
    "deletion_log",
    # feature 03 (reading); TRUNCATE … CASCADE handles the FK order
    "page_text",
    "page_flag",
    "document_text",
    "text_span",
)
LIBPQ_ENV = ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGDATABASE")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if INTEGRATION_DIR in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.integration)


# --- network guard (FR-013) --------------------------------------------------------


def _is_local_address(family: int, address: object) -> bool:
    if family == getattr(socket, "AF_UNIX", object()):
        return True
    if not isinstance(address, tuple) or not address:
        return False
    host = address[0]
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def check(sock: socket.socket, address: object) -> None:
        if not _is_local_address(sock.family, address):
            raise RuntimeError(f"Network access is forbidden in tests: {address!r}")

    def guarded_connect(self: socket.socket, address: object) -> None:
        check(self, address)
        return real_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: object) -> int:
        check(self, address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex)


# --- database --------------------------------------------------------------------


@pytest.fixture(scope="session")
def _test_database() -> Iterator[str]:
    admin_url = os.environ.get(TEST_DB_ENV, "").strip()
    if not admin_url:
        pytest.fail(
            f"Задайте {TEST_DB_ENV} — адрес локального PostgreSQL с правом создавать базы "
            "(например postgresql:///postgres)",
            pytrace=False,
        )
    _check_local_database(admin_url, os.environ)

    name = f"docreader_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = make_conninfo(admin_url, dbname=name)
    try:
        with psycopg.connect(url) as conn:
            dbmod.apply_migrations(conn)
        yield url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def database_url(_test_database: str) -> str:
    """URL of the test database, emptied before each test."""
    with psycopg.connect(_test_database) as conn:
        conn.execute(
            sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
                sql.SQL(", ").join(sql.Identifier(t) for t in REGISTRY_TABLES)
            )
        )
        conn.execute("UPDATE document_counter SET last_seq = 0")
    return _test_database


@pytest.fixture
def db(database_url: str) -> Iterator[psycopg.Connection]:
    """Autocommit connection to the test database for assertions and setup."""
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


@pytest.fixture
def empty_database_url(_test_database: str) -> Iterator[str]:
    """A second database without any schema (for «migrate» / outdated-schema tests)."""
    params = conninfo_to_dict(_test_database)
    name = f"{params['dbname']}_empty_{uuid.uuid4().hex[:6]}"
    admin_url = make_conninfo(_test_database, dbname="postgres")
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield make_conninfo(_test_database, dbname=name)
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


# --- data folder and CLI -------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@dataclass
class CliResult:
    exit_code: int
    stdout: str
    stderr: str


class _FakeStdin(io.StringIO):
    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


CliRunner = Callable[..., CliResult]


@pytest.fixture
def cli_env(monkeypatch: pytest.MonkeyPatch, data_dir: Path) -> Callable[[str], None]:
    """Point the CLI at a database URL and the temporary data folder."""
    for var in LIBPQ_ENV:
        monkeypatch.delenv(var, raising=False)

    def use(database_url: str) -> None:
        monkeypatch.setenv("DOCREADER_DATA_DIR", str(data_dir))
        monkeypatch.setenv("DOCREADER_DATABASE_URL", database_url)

    return use


def _make_runner(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    from docreader import cli

    def run(*args: object, input: str | None = None, tty: bool | None = None) -> CliResult:
        """Run `docreader <args>` in-process.

        `input` is fed to stdin; stdin looks like a terminal when `input` is given,
        unless `tty` says otherwise.
        """
        stdin = _FakeStdin(input or "", tty if tty is not None else input is not None)
        monkeypatch.setattr("sys.stdin", stdin)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main([str(a) for a in args])
        return CliResult(code, out.getvalue(), err.getvalue())

    return run


@pytest.fixture
def cli(cli_env: Callable[[str], None], database_url: str, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    """`cli("add", path, "--json")` → CliResult(exit_code, stdout, stderr)."""
    cli_env(database_url)
    return _make_runner(monkeypatch)


@pytest.fixture
def cli_on(cli_env: Callable[[str], None], monkeypatch: pytest.MonkeyPatch) -> Callable[[str], CliRunner]:
    """`cli_on(url)` → runner bound to another database (e.g. `empty_database_url`)."""

    def bind(database_url: str) -> CliRunner:
        cli_env(database_url)
        return _make_runner(monkeypatch)

    return bind
