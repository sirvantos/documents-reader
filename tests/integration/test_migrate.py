"""Integration tests for `docreader migrate` and environment errors (task T016)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_migrate_applies_then_is_current(cli_on, empty_database_url: str) -> None:
    run = cli_on(empty_database_url)

    first = run("migrate")
    assert first.exit_code == 0
    assert "Применена миграция 0001_intake" in first.stdout

    second = run("migrate")
    assert second.exit_code == 0
    assert "Схема актуальна" in second.stdout


def test_list_without_schema_suggests_migrate(cli_on, empty_database_url: str) -> None:
    run = cli_on(empty_database_url)

    result = run("list")

    assert result.exit_code == 2
    assert "docreader migrate" in result.stderr


def test_migrate_on_migrated_database_is_current(cli) -> None:
    result = cli("migrate")

    assert result.exit_code == 0
    assert "Схема актуальна" in result.stdout


def test_missing_data_dir_variable(cli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DOCREADER_DATA_DIR")

    result = cli("list")

    assert result.exit_code == 2
    assert "DOCREADER_DATA_DIR" in result.stderr


def test_data_dir_inside_repository_is_refused(cli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCREADER_DATA_DIR", str(REPO_ROOT / "data-inside"))

    result = cli("list")

    assert result.exit_code == 2
    assert not (REPO_ROOT / "data-inside").exists()


def test_non_local_database_is_refused(cli, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCREADER_DATABASE_URL", "postgresql://db.example.com/docreader")

    result = cli("list")

    assert result.exit_code == 2
    assert "локальн" in result.stderr
