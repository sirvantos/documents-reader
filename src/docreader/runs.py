"""Pipeline run bookkeeping (research R-9): one row in `run` per pipeline run."""

from __future__ import annotations

import functools
import importlib.metadata
import subprocess
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


@functools.lru_cache(maxsize=1)
def code_version() -> str:
    """Return `git describe --always --dirty` for the package, or the package version."""
    try:
        result = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return importlib.metadata.version("docreader")


def start_run(
    conn: psycopg.Connection,
    stage: str,
    settings: dict,
    label: str | None = None,
) -> int:
    """Insert a run row and commit it so it survives later rollbacks of per-file work."""
    row = conn.execute(
        "INSERT INTO run (stage, code_version, settings, label) "
        "VALUES (%s, %s, %s, %s) RETURNING id",
        (stage, code_version(), Jsonb(settings), label),
    ).fetchone()
    conn.commit()
    return row[0]


def finish_run(conn: psycopg.Connection, run_id: int) -> None:
    """Mark the run as finished."""
    conn.execute("UPDATE run SET finished_at = now() WHERE id = %s", (run_id,))
    conn.commit()
