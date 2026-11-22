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


# --- 0003_recognition (feature 13, task T003) ------------------------------------------


def _apply_up_to(conn: psycopg.Connection, last: str) -> None:
    """Apply the shipped migrations up to and including `last`, as `migrate` would."""
    from docreader import db as dbmod

    conn.execute(dbmod._CREATE_SCHEMA_MIGRATIONS)
    for version, path in dbmod.available_migrations():
        with conn.transaction():
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        if version == last:
            return
    raise AssertionError(f"no migration {last}")


def test_recognition_migration_is_listed_as_applied(db) -> None:
    versions = {r[0] for r in db.execute("SELECT version FROM schema_migrations")}
    assert "0003_recognition" in versions


def test_recognition_stage_added_for_existing_documents(empty_database_url: str) -> None:
    from docreader import db as dbmod

    with psycopg.connect(empty_database_url, autocommit=True) as conn:
        _apply_up_to(conn, "0002_reading")
        _seed_page(conn)
        conn.execute(
            "INSERT INTO stage_status (document_id, stage) VALUES ('D-0001', 'reading')"
        )
        # later migrations (0004 and on) are applied after it
        assert dbmod.apply_migrations(conn)[0] == "0003_recognition"
        row = conn.execute(
            "SELECT state, reason FROM stage_status "
            "WHERE document_id = 'D-0001' AND stage = 'recognition'"
        ).fetchone()
        assert row == ("pending", None)
        assert dbmod.apply_migrations(conn) == []


def test_old_page_text_rows_get_source_pdf(empty_database_url: str) -> None:
    from docreader import db as dbmod

    with psycopg.connect(empty_database_url, autocommit=True) as conn:
        _apply_up_to(conn, "0002_reading")
        run_id = _seed_page(conn)
        _insert_page_text(conn, run_id)
        dbmod.apply_migrations(conn)
        assert conn.execute("SELECT source FROM page_text").fetchone()[0] == "pdf"


def test_page_text_source_rejects_unknown(db) -> None:
    run_id = _seed_page(db)
    _insert_page_text(db, run_id)
    db.execute("UPDATE page_text SET source = 'recognized'")
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute("UPDATE page_text SET source = 'other'")


@pytest.mark.parametrize("code", ["low_recognition_quality", "scan_no_text"])
def test_page_flag_accepts_recognition_codes(db, code: str) -> None:
    run_id = _seed_page(db)
    _insert_page_text(db, run_id)
    db.execute(
        "INSERT INTO page_flag (document_id, page_number, code, reason) "
        "VALUES ('D-0001', 1, %s, 'причина')",
        (code,),
    )


def test_stage_status_accepts_recognition(db) -> None:
    _seed_page(db)
    db.execute(
        "INSERT INTO stage_status (document_id, stage, state, reason) "
        "VALUES ('D-0001', 'recognition', 'needs_review', 'стр. 1: ошибка')"
    )
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute(
            "INSERT INTO stage_status (document_id, stage) VALUES ('D-0001', 'ocr')"
        )


def _insert_recognition(db, run_id: int, **overrides) -> None:
    row = {
        "engine": "fake",
        "engine_version": "1",
        "dpi": 300,
        "turn": 0,
        "lines": "[]",
        "quality": None,
        "ink_share": 0.0,
        "result_sha256": SHA,
        "seconds": 1.5,
        "error": None,
    }
    row.update(overrides)
    db.execute(
        "INSERT INTO page_recognition (document_id, page_number, engine, engine_version, dpi,"
        " turn, lines, quality, ink_share, result_sha256, seconds, error, run_id)"
        " VALUES ('D-0001', 1, %(engine)s, %(engine_version)s, %(dpi)s, %(turn)s,"
        " %(lines)s::jsonb, %(quality)s, %(ink_share)s, %(result_sha256)s, %(seconds)s,"
        " %(error)s, %(run_id)s)",
        {**row, "run_id": run_id},
    )


def test_page_recognition_accepts_a_good_row(db) -> None:
    run_id = _seed_page(db)
    _insert_recognition(
        db,
        run_id,
        lines='[{"i": 0, "text": "x", "bbox": [1, 2, 3, 4], "confidence": 0.9}]',
        quality=0.9,
    )
    row = db.execute(
        "SELECT orientation_unknown, recognized_at IS NOT NULL FROM page_recognition"
    ).fetchone()
    assert row == (False, True)


@pytest.mark.parametrize(
    "overrides",
    [
        {"turn": 45},
        {"dpi": 50},
        {"dpi": 1300},
        {"quality": 1.5},
        {"ink_share": -0.1},
        {"error": ""},
        {"error": "  "},
        {"error": "boom", "lines": '[{"i": 0}]'},
        {"error": "boom", "quality": 0.5},
        {"result_sha256": "xyz"},
        {"result_sha256": "A" * 64},
        {"seconds": -1.0},
        {"engine": ""},
        {"engine_version": " "},
        {"lines": '{"i": 0}'},
    ],
)
def test_page_recognition_rejects_bad_rows(db, overrides) -> None:
    run_id = _seed_page(db)
    with pytest.raises(psycopg.errors.IntegrityError):
        _insert_recognition(db, run_id, **overrides)


def test_page_recognition_is_one_row_per_page(db) -> None:
    run_id = _seed_page(db)
    _insert_recognition(db, run_id)
    with pytest.raises(psycopg.errors.IntegrityError):
        _insert_recognition(db, run_id)


def test_page_recognition_run_is_restricted_and_document_cascades(db) -> None:
    _seed_page(db)
    rec_run = db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('recognition', 'test', '{}') "
        "RETURNING id"
    ).fetchone()[0]
    _insert_recognition(db, rec_run)
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute("DELETE FROM run WHERE id = %s", (rec_run,))
    db.execute("DELETE FROM document WHERE id = 'D-0001'")
    assert db.execute("SELECT count(*) FROM page_recognition").fetchone()[0] == 0


# --- 0004_structure (feature 04, task T002) --------------------------------------------

HASH = "a" * 64


def _structure_run(db) -> int:
    return db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('structure', 'test', '{}') "
        "RETURNING id"
    ).fetchone()[0]


def _insert_clause(db, run_id: int, **overrides) -> None:
    row = {
        "key": "5.2",
        "ordinal": 0,
        "kind": "clause",
        "number_printed": "5.2.",
        "number": [5, 2],
        "depth": 2,
        "parent_key": None,
        "start": 0,
        "end_": 10,
        "first_page": 1,
        "last_page": 1,
        "sha": HASH,
    }
    row.update(overrides)
    db.execute(
        "INSERT INTO clause (document_id, key, ordinal, kind, number_printed, number, depth,"
        " parent_key, start, end_, first_page, last_page, source_text_sha256, run_id)"
        " VALUES ('D-0001', %(key)s, %(ordinal)s, %(kind)s, %(number_printed)s, %(number)s,"
        " %(depth)s, %(parent_key)s, %(start)s, %(end_)s, %(first_page)s, %(last_page)s,"
        " %(sha)s, %(run_id)s)",
        {**row, "run_id": run_id},
    )


def test_structure_migration_is_listed_as_applied(db) -> None:
    versions = {r[0] for r in db.execute("SELECT version FROM schema_migrations")}
    assert "0004_structure" in versions


def test_clause_accepts_every_kind(db) -> None:
    _seed_page(db)
    run_id = _structure_run(db)
    _insert_clause(
        db, run_id, key="преамбула", ordinal=0, kind="preamble", number_printed=None,
        number=None, depth=0, start=0, end_=5,
    )
    _insert_clause(
        db, run_id, key="5", ordinal=1, kind="section", number_printed="5.", number=[5],
        depth=1, start=5, end_=8,
    )
    _insert_clause(db, run_id, key="5.2", ordinal=2, parent_key="5", start=8, end_=12)
    _insert_clause(
        db, run_id, key="реквизиты", ordinal=3, kind="tail", number_printed=None,
        number=None, depth=0, start=12, end_=20,
    )
    assert db.execute("SELECT count(*) FROM clause").fetchone()[0] == 4


@pytest.mark.parametrize(
    "overrides",
    [
        {"key": " "},
        {"kind": "appendix"},
        {"kind": "section", "number": None},
        {"kind": "section", "number_printed": None},
        {"kind": "preamble"},  # a preamble has no number
        {"depth": 3},  # number {5,2} has depth 2
        {"end_": 0},  # end_ <= start
        {"start": -1},
        {"ordinal": -1},
        {"first_page": 2, "last_page": 1},
        {"sha": "z" * 64},
        {"parent_key": "9"},  # no such record
    ],
)
def test_clause_rejects_bad_rows(db, overrides) -> None:
    _seed_page(db)
    run_id = _structure_run(db)
    with pytest.raises(psycopg.errors.IntegrityError):
        _insert_clause(db, run_id, **overrides)


def test_clause_keys_and_ordinals_are_unique_per_document(db) -> None:
    _seed_page(db)
    run_id = _structure_run(db)
    _insert_clause(db, run_id)
    with pytest.raises(psycopg.errors.IntegrityError):
        _insert_clause(db, run_id, ordinal=1)  # same key
    with pytest.raises(psycopg.errors.IntegrityError):
        _insert_clause(db, run_id, key="5.3")  # same ordinal


def test_clause_run_is_restricted_and_document_cascades(db) -> None:
    _seed_page(db)
    run_id = _structure_run(db)
    _insert_clause(db, run_id)
    with pytest.raises(psycopg.errors.IntegrityError):
        db.execute("DELETE FROM run WHERE id = %s", (run_id,))
    db.execute("DELETE FROM document WHERE id = 'D-0001'")
    assert db.execute("SELECT count(*) FROM clause").fetchone()[0] == 0
