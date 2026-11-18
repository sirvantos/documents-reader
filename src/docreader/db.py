"""Database connection and the migration runner (research R-6)."""

from __future__ import annotations

from pathlib import Path

import psycopg

from docreader.config import Settings
from docreader.errors import EnvironmentProblem

# Document processing stages (FR-008). Must match the CHECK on stage_status.stage.
STAGES = ("reading", "structure", "extraction", "checks", "indexing")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_CREATE_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
)
"""


def fetch_row(cur: psycopg.Cursor) -> tuple:
    """The one row of a query that always returns one (aggregate, RETURNING, key lookup)."""
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("the query returned no row")
    return row


def connect(settings: Settings) -> psycopg.Connection:
    try:
        return psycopg.connect(settings.database_url, connect_timeout=10)
    except psycopg.OperationalError as exc:
        detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise EnvironmentProblem(
            f"База данных недоступна ({detail}) — запустите PostgreSQL "
            "и проверьте DOCREADER_DATABASE_URL"
        ) from exc


def available_migrations() -> list[tuple[str, Path]]:
    """(version, path) of every migration shipped with the package, in name order."""
    return [(p.stem, p) for p in sorted(MIGRATIONS_DIR.glob("*.sql"))]


def _applied_versions(conn: psycopg.Connection) -> set[str]:
    exists = fetch_row(conn.execute("SELECT to_regclass('schema_migrations') IS NOT NULL"))[0]
    if not exists:
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def pending_migrations(conn: psycopg.Connection) -> list[str]:
    applied = _applied_versions(conn)
    return [version for version, _ in available_migrations() if version not in applied]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply unapplied migrations, each in its own transaction; return their versions."""
    conn.execute(_CREATE_SCHEMA_MIGRATIONS)
    conn.commit()
    applied = _applied_versions(conn)
    conn.commit()

    done: list[str] = []
    for version, path in available_migrations():
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        with conn.transaction():
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        done.append(version)
    return done


def ensure_schema_current(conn: psycopg.Connection) -> None:
    pending = pending_migrations(conn)
    conn.commit()
    if pending:
        raise EnvironmentProblem(
            "Схема базы устарела — выполните docreader migrate "
            f"(не применены: {', '.join(pending)})"
        )
