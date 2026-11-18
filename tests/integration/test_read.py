"""Integration tests for `docreader read` and `docreader text` (task T011, feature 03).

Everything goes through the CLI and the database; no internal functions are called.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from tests.synthetic import make_pdfs as mk

UNREAD_MSG = "Документ D-0001 ещё не прочитан — выполните docreader read D-0001"
NOTHING_MSG = "Нечего читать: все документы прочитаны (перечитать: docreader read --all)"
LATER_STAGES = ("structure", "extraction", "checks", "indexing")


# --- helpers ------------------------------------------------------------------------


def add_files(cli, folder: Path, makers: list) -> list[str]:
    folder.mkdir(parents=True, exist_ok=True)
    for i, make in enumerate(makers):
        make(folder / f"f{i}.pdf")
    result = cli("add", folder, "--json")
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["totals"]["added"] == len(makers)
    return sorted(f["document_id"] for f in report["files"])


def make_text_and_blank(path: Path) -> Path:
    """Page 1 has text, page 2 is blank."""

    def draw(c: canvas.Canvas) -> None:
        mk._ru_page(c, mk.CONTRACT_RU_PAGES[0])
        c.showPage()
        c.showPage()

    return mk._write(path, mk._pdf(draw))


def digital(seed: str):
    return lambda p: mk.make_digital(p, pages=2, text_seed=seed)


def copy_of(db, data_dir: Path, doc_id: str) -> Path:
    (rel,) = db.execute("SELECT copy_path FROM document WHERE id = %s", (doc_id,)).fetchone()
    return data_dir / rel


def stage(db, doc_id: str, name: str = "reading") -> tuple:
    return db.execute(
        "SELECT state, reason, run_id FROM stage_status WHERE document_id = %s AND stage = %s",
        (doc_id, name),
    ).fetchone()


def set_stage(db, doc_id: str, name: str, state: str, reason: str | None = None) -> None:
    db.execute(
        "UPDATE stage_status SET state = %s, reason = %s WHERE document_id = %s AND stage = %s",
        (state, reason, doc_id, name),
    )


def page_rows(db, doc_id: str) -> list[tuple]:
    return db.execute(
        "SELECT page_number, rotation, width, height, lines, has_table FROM page_text "
        "WHERE document_id = %s ORDER BY page_number",
        (doc_id,),
    ).fetchall()


def count(db, table: str, doc_id: str) -> int:
    return db.execute(
        f"SELECT count(*) FROM {table} WHERE document_id = %s", (doc_id,)  # noqa: S608
    ).fetchone()[0]


def flags_of(db, doc_id: str) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    for page, code in db.execute(
        "SELECT page_number, code FROM page_flag WHERE document_id = %s", (doc_id,)
    ):
        out.setdefault(page, set()).add(code)
    return out


def read_json(cli, *args) -> dict:
    result = cli("read", *args, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def total_page_text(db) -> int:
    return db.execute("SELECT count(*) FROM page_text").fetchone()[0]


@pytest.fixture
def contract(cli, tmp_path):
    ids = add_files(cli, tmp_path / "in", [lambda p: mk.make_contract_ru(p, pages=3)])
    assert ids == ["D-0001"]
    return ids[0]


@pytest.fixture
def four_docs(cli, db, tmp_path):
    ids = add_files(cli, tmp_path / "in", [digital(s) for s in "ABCD"])
    assert ids == ["D-0001", "D-0002", "D-0003", "D-0004"]
    return ids


# --- US1-1: lines, boxes, rotation --------------------------------------------------


def test_read_stores_lines_per_page_equal_to_generator(cli, db, contract):
    result = cli("read", contract)

    assert result.exit_code == 0, result.stderr
    rows = page_rows(db, contract)
    assert [r[0] for r in rows] == [1, 2, 3]
    for (page, rotation, width, height, lines, _table), expected in zip(
        rows, mk.CONTRACT_RU_PAGES, strict=True
    ):
        assert [ln["text"] for ln in lines] == list(expected), f"page {page}"
        assert rotation == 0
        for ln in lines:
            x0, y0, x1, y1 = ln["bbox"]
            assert -1 <= x0 < x1 <= width + 1
            assert -1 <= y0 < y1 <= height + 1
    assert stage(db, contract)[0] == "done"


# --- US1-2: text command ------------------------------------------------------------


def test_text_whole_document_has_page_separators(cli, contract):
    cli("read", contract)

    result = cli("text", contract)

    assert result.exit_code == 0, result.stderr
    out = result.stdout
    for n in (1, 2, 3):
        assert f"── стр. {n} ──" in out
    assert out.index("── стр. 1 ──") < out.index("── стр. 2 ──") < out.index("── стр. 3 ──")
    assert "Договор подряда № 123/45-У" in out
    assert "6.1. Договор составлен в двух экземплярах." in out


def test_text_page_prints_lines_of_that_page_only(cli, contract):
    cli("read", contract)

    result = cli("text", contract, "--page", "2")

    assert result.exit_code == 0, result.stderr
    for line in mk.CONTRACT_RU_PAGES[1]:
        assert line in result.stdout
    assert mk.CONTRACT_RU_PAGES[0][0] not in result.stdout
    assert mk.CONTRACT_RU_PAGES[2][0] not in result.stdout


def test_text_page_json_shape(cli, contract):
    cli("read", contract)

    result = cli("text", contract, "--page", "2", "--json")

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"] == contract
    (page,) = data["pages"]
    assert page["page"] == 2
    assert page["rotation"] == 0
    assert page["has_table"] is False
    assert page["flags"] == []
    assert [ln["text"] for ln in page["lines"]] == list(mk.CONTRACT_RU_PAGES[1])
    for key in ("i", "text", "bbox", "role"):
        assert key in page["lines"][0]
    assert page["lines"][0]["role"] == "body"


def test_text_document_json_shape(cli, contract):
    cli("read", contract)

    result = cli("text", contract, "--json")

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["id"] == contract
    assert data["read_pages"] == 3
    assert [p["page"] for p in data["pages"]] == [1, 2, 3]
    for page, expected in zip(data["pages"], mk.CONTRACT_RU_PAGES, strict=True):
        assert page["flags"] == []
        for line in expected:
            assert line in page["text"]


def test_text_of_unread_document_is_user_error(cli, contract):
    result = cli("text", contract)

    assert result.exit_code == 1
    assert UNREAD_MSG in result.stderr + result.stdout


def test_text_page_out_of_range_is_user_error(cli, contract):
    cli("read", contract)

    for page in ("0", "4"):
        result = cli("text", contract, "--page", page)
        assert result.exit_code == 1, page
        assert result.stderr.strip() != ""


# --- US1-3: re-read is idempotent ---------------------------------------------------


def test_reread_gives_same_hash_rows_and_keeps_later_stages(cli, db, contract):
    cli("read", contract)
    for name in LATER_STAGES:
        set_stage(db, contract, name, "done")
    before = {
        "sha": db.execute(
            "SELECT text_sha256 FROM document_text WHERE document_id = %s", (contract,)
        ).fetchone(),
        "page_text": count(db, "page_text", contract),
        "text_span": count(db, "text_span", contract),
        "stages": {n: stage(db, contract, n)[:2] for n in LATER_STAGES},
    }
    assert before["text_span"] > 0

    result = cli("read", contract)

    assert result.exit_code == 0, result.stderr
    after_sha = db.execute(
        "SELECT text_sha256 FROM document_text WHERE document_id = %s", (contract,)
    ).fetchone()
    assert after_sha == before["sha"]
    assert count(db, "page_text", contract) == before["page_text"] == 3
    assert count(db, "text_span", contract) == before["text_span"]
    assert {n: stage(db, contract, n)[:2] for n in LATER_STAGES} == before["stages"]


# --- US1-4: choosing documents ------------------------------------------------------


def test_read_without_arguments_takes_pending_and_failed_only(cli, db, four_docs):
    set_stage(db, "D-0002", "reading", "failed", "synthetic failure")
    set_stage(db, "D-0003", "reading", "done")
    set_stage(db, "D-0004", "reading", "needs_review", "synthetic review")

    result = cli("read")

    assert result.exit_code == 0, result.stderr
    assert count(db, "page_text", "D-0001") == 2
    assert count(db, "page_text", "D-0002") == 2
    assert count(db, "page_text", "D-0003") == 0
    assert count(db, "page_text", "D-0004") == 0
    assert stage(db, "D-0001")[0] == "done"
    assert stage(db, "D-0002")[0] == "done"
    assert stage(db, "D-0003") [:2] == ("done", None)
    assert stage(db, "D-0004")[:2] == ("needs_review", "synthetic review")


def test_read_explicit_id_reads_in_any_state(cli, db, four_docs):
    set_stage(db, "D-0003", "reading", "done")
    set_stage(db, "D-0004", "reading", "needs_review", "synthetic review")

    data = read_json(cli, "D-0003", "D-0004")

    assert [d["id"] for d in data["documents"]] == ["D-0003", "D-0004"]
    assert count(db, "page_text", "D-0003") == 2
    assert count(db, "page_text", "D-0004") == 2
    assert count(db, "page_text", "D-0001") == 0
    assert stage(db, "D-0004")[:2] == ("done", None)


def test_read_all_reads_every_document(cli, db, four_docs):
    set_stage(db, "D-0003", "reading", "done")

    data = read_json(cli, "--all")

    assert {d["id"] for d in data["documents"]} == set(four_docs)
    for doc_id in four_docs:
        assert count(db, "page_text", doc_id) == 2


def test_read_all_with_ids_is_user_error(cli, db, four_docs):
    result = cli("read", "D-0001", "--all")

    assert result.exit_code == 1
    assert total_page_text(db) == 0


def test_read_unknown_id_reads_nothing(cli, db, four_docs):
    result = cli("read", "D-0001", "D-0099")

    assert result.exit_code == 1
    assert "D-0099" in result.stderr + result.stdout
    assert total_page_text(db) == 0


def test_read_with_nothing_to_read(cli, db, four_docs):
    assert cli("read").exit_code == 0
    runs = db.execute("SELECT count(*) FROM run WHERE stage = 'reading'").fetchone()[0]

    result = cli("read")

    assert result.exit_code == 0, result.stderr
    assert NOTHING_MSG in result.stdout
    assert db.execute("SELECT count(*) FROM run WHERE stage = 'reading'").fetchone()[0] == runs


# --- US2: flags and states ----------------------------------------------------------


def test_mixed_document_flags_scan_page_and_needs_review(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [lambda p: mk.make_mixed(p, pages=4)])

    result = cli("read", doc)

    assert result.exit_code == 0, result.stderr
    assert flags_of(db, doc) == {4: {"scan_unread"}}
    state, reason, _ = stage(db, doc)
    assert state == "needs_review"
    assert "скан, не прочитана" in reason
    assert "4" in reason
    rows = page_rows(db, doc)
    assert [r[0] for r in rows] == [1, 2, 3, 4]
    assert rows[3][4] == []  # SC-002: flagged page still has a row, with no lines
    for row in rows[:3]:
        assert row[4]
    assert db.execute(
        "SELECT read_pages FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone() == (3,)


def test_blank_page_in_text_document_is_flagged_empty_and_done(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [make_text_and_blank])

    result = cli("read", doc)

    assert result.exit_code == 0, result.stderr
    assert flags_of(db, doc) == {2: {"empty"}}
    assert stage(db, doc)[:2] == ("done", None)
    assert page_rows(db, doc)[1][4] == []


def test_blank_only_document_has_empty_flag_and_no_scan_flag(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_blank_page])

    result = cli("read", doc)

    assert result.exit_code == 0, result.stderr
    assert flags_of(db, doc) == {1: {"empty"}}
    assert len(page_rows(db, doc)) == 1


def test_image_only_document_needs_review_with_no_text(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [lambda p: mk.make_image_only(p, pages=2)])

    data = read_json(cli, doc)

    state, reason, _ = stage(db, doc)
    assert state == "needs_review"
    assert reason.startswith("нет прочитанного текста")
    text, read_pages = db.execute(
        "SELECT text, read_pages FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()
    assert (text, read_pages) == ("", 0)
    assert flags_of(db, doc) == {1: {"scan_unread"}, 2: {"scan_unread"}}
    (entry,) = data["documents"]
    assert entry["state"] == "needs_review"
    assert entry["flags"] == {"scan_unread": [1, 2]}


def test_every_page_has_a_row_in_every_document(cli, db, tmp_path):
    ids = add_files(
        cli,
        tmp_path / "in",
        [
            lambda p: mk.make_contract_ru(p, pages=2),
            lambda p: mk.make_mixed(p, pages=3),
            make_text_and_blank,
            lambda p: mk.make_image_only(p, pages=2),
        ],
    )

    assert cli("read", "--all").exit_code == 0

    for doc_id in ids:
        (pages,) = db.execute(
            "SELECT page_count FROM document WHERE id = %s", (doc_id,)
        ).fetchone()
        assert [r[0] for r in page_rows(db, doc_id)] == list(range(1, pages + 1))
        for page, code in db.execute(
            "SELECT page_number, code FROM page_flag WHERE document_id = %s", (doc_id,)
        ):
            if code in ("scan_unread", "empty"):
                assert page_rows(db, doc_id)[page - 1][4] == []


def test_missing_copy_fails_that_document_only(cli, db, data_dir, four_docs):
    copy_of(db, data_dir, "D-0002").unlink()

    data = read_json(cli)

    state, reason, _ = stage(db, "D-0002")
    assert state == "failed"
    assert reason and reason.strip()
    for doc_id in ("D-0001", "D-0003", "D-0004"):
        assert stage(db, doc_id)[0] == "done"
        assert count(db, "page_text", doc_id) == 2
    assert count(db, "page_text", "D-0002") == 0
    by_id = {d["id"]: d for d in data["documents"]}
    assert by_id["D-0002"]["state"] == "failed"
    assert by_id["D-0002"]["reason"]
    assert data["totals"] == {"done": 3, "needs_review": 0, "failed": 1}


# --- FR-013, FR-014, JSON result ----------------------------------------------------


def test_read_records_one_run_with_settings_and_label(cli, db, four_docs):
    result = cli("read", "--label", "first pass")

    assert result.exit_code == 0, result.stderr
    rows = db.execute(
        "SELECT id, code_version, settings ? 'reading', label, finished_at IS NOT NULL "
        "FROM run WHERE stage = 'reading'"
    ).fetchall()
    assert len(rows) == 1
    run_id, code_version, has_settings, label, finished = rows[0]
    assert code_version and code_version.strip()
    assert has_settings is True
    assert label == "first pass"
    assert finished is True
    for doc_id in four_docs:
        assert stage(db, doc_id)[2] == run_id


def test_read_does_not_change_the_copy(cli, db, data_dir, contract):
    path = copy_of(db, data_dir, contract)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    (registered,) = db.execute("SELECT sha256 FROM document WHERE id = %s", (contract,)).fetchone()
    assert before == registered

    assert cli("read", contract).exit_code == 0
    assert cli("read", contract).exit_code == 0

    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_read_json_result_shape(cli, db, tmp_path):
    ids = add_files(
        cli,
        tmp_path / "in",
        [lambda p: mk.make_contract_ru(p, pages=2), lambda p: mk.make_mixed(p, pages=3)],
    )

    data = read_json(cli)

    (run_id,) = db.execute("SELECT id FROM run WHERE stage = 'reading'").fetchone()
    assert data["run_id"] == run_id
    assert set(data) >= {"run_id", "documents", "totals"}
    assert [d["id"] for d in data["documents"]] == ids
    for entry in data["documents"]:
        assert set(entry) >= {"id", "pages", "state", "reason", "text_changed", "flags"}
    first, second = data["documents"]
    assert first["pages"] == 2
    assert first["state"] == "done"
    assert first["reason"] is None
    assert first["text_changed"] is False
    assert first["flags"] == {}
    assert second["pages"] == 3
    assert second["state"] == "needs_review"
    assert "скан, не прочитана" in second["reason"]
    assert second["flags"] == {"scan_unread": [3]}
    assert data["totals"] == {"done": 1, "needs_review": 1, "failed": 0}


def test_read_text_output_lists_documents_and_totals(cli, tmp_path):
    add_files(cli, tmp_path / "in", [lambda p: mk.make_mixed(p, pages=3)])

    result = cli("read")

    assert result.exit_code == 0, result.stderr
    assert "D-0001" in result.stdout
    assert "требует просмотра" in result.stdout
    assert "Итого:" in result.stdout


# --- US2: content flags (T025) -------------------------------------------------------


def stored_lines(db, doc_id: str) -> list[list[str]]:
    return [[ln["text"] for ln in row[4]] for row in page_rows(db, doc_id)]


def flag_reasons(db, doc_id: str) -> dict[tuple[int, str], str]:
    return {
        (page, code): reason
        for page, code, reason in db.execute(
            "SELECT page_number, code, reason FROM page_flag WHERE document_id = %s", (doc_id,)
        )
    }


def test_invisible_text_over_image_is_flagged_ocr_text_and_stored(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_image_with_invisible_text])

    assert cli("read", doc).exit_code == 0

    assert flags_of(db, doc) == {1: {"ocr_text"}, 2: {"ocr_text"}}
    for lines in stored_lines(db, doc):
        assert lines


def test_garbage_page_is_flagged_unreadable(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_unreadable_ru])

    assert cli("read", doc).exit_code == 0

    flags = flags_of(db, doc)
    assert flags
    assert all("unreadable" in codes for codes in flags.values())


def test_three_kazakh_letters_flag_maybe_not_russian(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [lambda p: mk.make_kazakh_ru(p, 3)])

    assert cli("read", doc).exit_code == 0

    assert flags_of(db, doc) == {1: {"maybe_not_russian"}}
    reason = flag_reasons(db, doc)[(1, "maybe_not_russian")]
    assert reason.startswith("3 буквы не русского алфавита")


def test_single_kazakh_letter_gives_no_not_russian_flag(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_kazakh_one_ru])

    assert cli("read", doc).exit_code == 0

    assert all("maybe_not_russian" not in codes for codes in flags_of(db, doc).values())


def test_latin_in_russian_text_gives_no_flags_and_is_stored_as_is(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_latin_ru])

    assert cli("read", doc).exit_code == 0

    assert flags_of(db, doc) == {}
    assert stage(db, doc)[:2] == ("done", None)
    assert any("CKAВ" in line for line in stored_lines(db, doc)[0])


def test_flagged_pages_make_needs_review_with_page_list(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_image_with_invisible_text])

    data = read_json(cli, doc)

    state, reason, _ = stage(db, doc)
    assert state == "needs_review"
    assert "стр. 1, 2: " in reason
    assert reason == data["documents"][0]["reason"]
    assert data["documents"][0]["flags"] == {"ocr_text": [1, 2]}


def test_typography_is_normalized_in_stored_lines(cli, db, tmp_path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_typography_ru])

    assert cli("read", doc).exit_code == 0

    assert stored_lines(db, doc) == [list(page) for page in mk.TYPOGRAPHY_RU_CLEAN]
    joined = "\n".join(stored_lines(db, doc)[0])
    for kept in ("—", "–", "«", "»", "ё"):
        assert kept in joined
