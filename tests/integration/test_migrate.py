"""Integration tests for `docreader migrate` and environment errors (task T016)."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_migrate_applies_then_is_current(cli_on, empty_database_url: str) -> None:
    run = cli_on(empty_database_url)

    first = run("migrate")
    assert first.exit_code == 0
    assert "Применена миграция 0001_intake" in first.stdout
    assert "Применена миграция 0002_reading" in first.stdout

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


# --- 0002_reading constraints (feature 03, task T006) ----------------------------------

SHA = "a" * 64


def _seed_page(db) -> int:
    """One run, one document with one page; returns the run id."""
    run_id = db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('reading', 'test', '{}') "
        "RETURNING id"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO document (id, seq, sha256, original_name, source_path, copy_path, "
        "size_bytes, page_count, intake_run_id) "
        "VALUES ('D-0001', 1, %s, 'a.pdf', '/x/a.pdf', 'originals/a.pdf', 10, 1, %s)",
        (SHA, run_id),
    )
    db.execute(
        "INSERT INTO page (document_id, page_number, kind, char_count, image_coverage, "
        "kind_run_id) VALUES ('D-0001', 1, 'text', 100, 0, %s)",
        (run_id,),
    )
    return run_id


def _insert_page_text(db, run_id: int, **overrides) -> None:
    row = {"page": 1, "rotation": 0, "width": 595.0, "height": 842.0, "lines": "[]"}
    row.update(overrides)
    db.execute(
        "INSERT INTO page_text (document_id, page_number, rotation, width, height, lines, "
        "has_table, run_id) VALUES ('D-0001', %s, %s, %s, %s, %s::jsonb, false, %s)",
        (row["page"], row["rotation"], row["width"], row["height"], row["lines"], run_id),
    )


def test_reading_migration_is_listed_as_applied(db) -> None:
    versions = {r[0] for r in db.execute("SELECT version FROM schema_migrations")}
    assert {"0001_intake", "0002_reading"} <= versions


@pytest.mark.parametrize(
    "overrides",
    [
        {"rotation": 45},
        {"width": 0.0},
        {"height": -1.0},
        {"lines": '{"i": 0}'},
        {"page": 2},  # no such page
    ],
)
def test_page_text_rejects_bad_rows(db, overrides) -> None:
    run_id = _seed_page(db)
    with pytest.raises(psycopg.errors.IntegrityError):
        _insert_page_text(db, run_id, **overrides)


@pytest.mark.parametrize(("code", "reason"), [("bogus", "x"), ("empty", "  ")])
def test_page_flag_rejects_bad_rows(db, code: str, reason: str) -> None:
    run_id = _seed_page(db)
    _insert_page_text(db, run_id)
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute(
            "INSERT INTO page_flag (document_id, page_number, code, reason) "
            "VALUES ('D-0001', 1, %s, %s)",
            (code, reason),
        )


@pytest.mark.parametrize(
    ("sha", "read_pages"), [("xyz", 1), ("A" * 64, 1), (SHA, -1)]
)
def test_document_text_rejects_bad_rows(db, sha: str, read_pages: int) -> None:
    run_id = _seed_page(db)
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute(
            "INSERT INTO document_text (document_id, text, text_sha256, read_pages, run_id) "
            "VALUES ('D-0001', '', %s, %s, %s)",
            (sha, read_pages, run_id),
        )


@pytest.mark.parametrize(("start", "end", "line"), [(-1, 3, 0), (5, 5, 0), (0, 3, -1)])
def test_text_span_rejects_bad_rows(db, start: int, end: int, line: int) -> None:
    run_id = _seed_page(db)
    db.execute(
        "INSERT INTO document_text (document_id, text, text_sha256, read_pages, run_id) "
        "VALUES ('D-0001', 'abcdef', %s, 1, %s)",
        (SHA, run_id),
    )
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute(
            "INSERT INTO text_span (document_id, start, end_, page_number, line_index) "
            "VALUES ('D-0001', %s, %s, 1, %s)",
            (start, end, line),
        )


def test_reading_rows_cascade_with_document(db) -> None:
    run_id = _seed_page(db)
    _insert_page_text(db, run_id)
    db.execute(
        "INSERT INTO page_flag (document_id, page_number, code, reason) "
        "VALUES ('D-0001', 1, 'empty', 'пустая')"
    )
    db.execute(
        "INSERT INTO document_text (document_id, text, text_sha256, read_pages, run_id) "
        "VALUES ('D-0001', 'abc', %s, 1, %s)",
        (SHA, run_id),
    )
    db.execute(
        "INSERT INTO text_span (document_id, start, end_, page_number, line_index) "
        "VALUES ('D-0001', 0, 3, 1, 0)"
    )
    db.execute("DELETE FROM document WHERE id = 'D-0001'")
    for table in ("page_text", "page_flag", "document_text", "text_span"):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("table", ["page_text", "document_text"])
def test_reading_run_cannot_be_deleted_while_referenced(db, table: str) -> None:
    _seed_page(db)
    read_run = db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('reading', 'test', '{}') "
        "RETURNING id"
    ).fetchone()[0]
    if table == "page_text":
        _insert_page_text(db, read_run)
    else:
        db.execute(
            "INSERT INTO document_text (document_id, text, text_sha256, read_pages, run_id) "
            "VALUES ('D-0001', 'abc', %s, 1, %s)",
            (SHA, read_run),
        )
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute("DELETE FROM run WHERE id = %s", (read_run,))
