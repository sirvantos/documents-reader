"""Integration tests for docreader.textview (task T017); rows are inserted directly."""

from __future__ import annotations

import pytest

from docreader.errors import UserError
import json

from docreader.textview import find_phrase, load_document_text, load_page

SHA = "a" * 64
TEXT = "Первая строка\nВторая строка\n\f"


def _seed(db, page_count: int = 2) -> int:
    run_id = db.execute(
        "INSERT INTO run (stage, code_version, settings) VALUES ('reading', 'test', '{}') "
        "RETURNING id"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO document (id, seq, sha256, original_name, source_path, copy_path, "
        "size_bytes, page_count, intake_run_id) "
        "VALUES ('D-0001', 1, %s, 'a.pdf', '/x/a.pdf', 'originals/a.pdf', 10, %s, %s)",
        (SHA, page_count, run_id),
    )
    for n in range(1, page_count + 1):
        db.execute(
            "INSERT INTO page (document_id, page_number, kind, char_count, image_coverage, "
            "kind_run_id) VALUES ('D-0001', %s, 'text', 100, 0, %s)",
            (n, run_id),
        )
    return run_id


def _add_page_text(db, run_id: int, page: int, lines: str = "[]") -> None:
    db.execute(
        "INSERT INTO page_text (document_id, page_number, rotation, width, height, lines, "
        "has_table, run_id) VALUES ('D-0001', %s, 90, 595, 842, %s::jsonb, true, %s)",
        (page, lines, run_id),
    )


def _add_text(db, run_id: int, text: str = TEXT) -> None:
    db.execute(
        "INSERT INTO document_text (document_id, text, text_sha256, read_pages, run_id) "
        "VALUES ('D-0001', %s, %s, 2, %s)",
        (text, SHA, run_id),
    )


def _span(db, start: int, end: int, page: int, line: int) -> None:
    db.execute(
        "INSERT INTO text_span (document_id, start, end_, page_number, line_index) "
        "VALUES ('D-0001', %s, %s, %s, %s)",
        (start, end, page, line),
    )


def _flag(db, page: int, code: str) -> None:
    db.execute(
        "INSERT INTO page_flag (document_id, page_number, code, reason) "
        "VALUES ('D-0001', %s, %s, %s)",
        (page, code, f"причина {code}"),
    )


def test_unknown_document(db) -> None:
    with pytest.raises(UserError, match="D-0007 не найден"):
        load_document_text(db, 7)
    with pytest.raises(UserError, match="D-0007 не найден"):
        load_page(db, 7, 1)


def test_not_read_document(db) -> None:
    _seed(db)
    message = "Документ D-0001 ещё не прочитан — выполните docreader read D-0001"
    with pytest.raises(UserError) as exc:
        load_document_text(db, 1)
    assert str(exc.value) == message
    with pytest.raises(UserError) as exc:
        load_page(db, 1, 1)
    assert str(exc.value) == message


@pytest.mark.parametrize("page", [0, 3, -1])
def test_page_out_of_range(db, page: int) -> None:
    run_id = _seed(db)
    _add_text(db, run_id)
    with pytest.raises(UserError) as exc:
        load_page(db, 1, page)
    assert str(exc.value) == f"В документе D-0001 нет страницы {page} (страниц: 2)"


def test_page_slices_and_missing_spans(db) -> None:
    run_id = _seed(db, page_count=3)
    for n in (1, 2, 3):
        _add_page_text(db, run_id, n)
    first, second = "Первая строка", "Вторая строка"
    text = f"{first}\n{second}\n\f"
    _add_text(db, run_id, text)
    _span(db, 0, len(first), 1, 0)
    _span(db, len(first) + 1, len(first) + 1 + len(second), 2, 0)

    result = load_document_text(db, 1)

    assert result["id"] == "D-0001"
    assert result["read_pages"] == 2
    assert [p["page"] for p in result["pages"]] == [1, 2, 3]
    assert [p["text"] for p in result["pages"]] == [first, second, ""]


def test_page_slice_covers_all_spans_of_page(db) -> None:
    run_id = _seed(db, page_count=1)
    _add_page_text(db, run_id, 1)
    _add_text(db, run_id, "abc\ndef")
    _span(db, 0, 3, 1, 0)
    _span(db, 4, 7, 1, 1)
    assert load_document_text(db, 1)["pages"][0]["text"] == "abc\ndef"


def test_flags_follow_flag_order(db) -> None:
    from docreader.quality import FLAG_ORDER

    run_id = _seed(db)
    _add_page_text(db, run_id, 1)
    _add_page_text(db, run_id, 2)
    _add_text(db, run_id)
    for code in reversed(FLAG_ORDER):
        _flag(db, 1, code)

    pages = load_document_text(db, 1)["pages"]

    assert [f["code"] for f in pages[0]["flags"]] == list(FLAG_ORDER)
    assert pages[0]["flags"][0] == {"code": FLAG_ORDER[0], "reason": f"причина {FLAG_ORDER[0]}"}
    assert pages[1]["flags"] == []


def test_load_page_returns_stored_values(db) -> None:
    run_id = _seed(db)
    _add_page_text(db, run_id, 1)
    _add_page_text(db, run_id, 2, '[{"i": 0, "text": "Строка"}]')
    _add_text(db, run_id)
    _flag(db, 2, "empty")

    result = load_page(db, 1, 2)

    assert result == {
        "id": "D-0001",
        "pages": [
            {
                "page": 2,
                "rotation": 90,
                "has_table": True,
                "flags": [{"code": "empty", "reason": "причина empty"}],
                "lines": [{"i": 0, "text": "Строка"}],
            }
        ],
    }


# --- find_phrase (T037) ---------------------------------------------------------------

FIND_TEXT = "Договор аренды\nСрок 12 месяцев\nДоговор аренды"
FIND_LINES = (
    '[{"i": 0, "text": "Договор аренды", "role": "body", "bbox": [1, 2, 3, 4]},'
    ' {"i": 1, "text": "Срок 12 месяцев", "role": "body", "bbox": [5, 6, 7, 8]},'
    ' {"i": 2, "text": "Колонтитул Договор", "role": "header", "bbox": [9, 9, 9, 9]}]'
)


def _seed_find(db) -> None:
    run_id = _seed(db)
    _add_page_text(db, run_id, 1, FIND_LINES)
    _add_page_text(db, run_id, 2, '[{"i": 0, "text": "Договор аренды", "role": "body",'
                   ' "bbox": [0, 0, 1, 1]}]')
    _add_text(db, run_id, FIND_TEXT)
    _span(db, 0, 14, 1, 0)
    _span(db, 15, 30, 1, 1)
    _span(db, 31, 45, 2, 0)


def test_find_clean_text_and_header(db) -> None:
    _seed_find(db)

    result = find_phrase(db, 1, "Договор")

    assert result["id"] == "D-0001"
    assert result["phrase"] == "Договор"
    assert result["matches"] == [
        {"start": 0, "end": 7, "page": 1, "line": 0, "bbox": [1, 2, 3, 4], "role": "body"},
        {"start": 31, "end": 38, "page": 2, "line": 0, "bbox": [0, 0, 1, 1], "role": "body"},
        {"start": 11, "end": 18, "page": 1, "line": 2, "bbox": [9, 9, 9, 9], "role": "header"},
    ]


def test_find_normalizes_phrase(db) -> None:
    _seed_find(db)

    result = find_phrase(db, 1, "Срок\u00a012\u2011")

    assert result["phrase"] == "Срок 12-"
    assert result["matches"] == []
    result = find_phrase(db, 1, "  Срок\u00a012  ")
    assert result["phrase"] == "Срок 12"
    assert [(m["page"], m["line"]) for m in result["matches"]] == [(1, 1)]


def test_find_skips_match_on_newline_join(db) -> None:
    _seed_find(db)

    assert find_phrase(db, 1, "\n")["matches"] == []


def test_find_not_found_and_empty_phrase(db) -> None:
    _seed_find(db)

    assert find_phrase(db, 1, "нет такого")["matches"] == []
    with pytest.raises(UserError, match="Пустая фраза для поиска"):
        find_phrase(db, 1, " \u00a0 ")


def test_find_errors_for_unknown_and_unread(db) -> None:
    with pytest.raises(UserError):
        find_phrase(db, 5, "x")
    _seed(db)
    with pytest.raises(UserError, match="ещё не прочитан"):
        find_phrase(db, 1, "x")


def test_cli_find_text_and_json(db, cli) -> None:
    _seed_find(db)

    text = cli("text", "D-0001", "--find", "Срок")
    assert text.exit_code == 0
    assert text.stdout.strip() == "стр. 1, строка 1, body: …Договор аренды Срок 12 месяцев Договор аренды…"

    as_json = cli("text", "D-0001", "--find", "Колонтитул", "--json")
    data = json.loads(as_json.stdout)
    assert data["matches"] == [
        {"start": 0, "end": 10, "page": 1, "line": 2, "bbox": [9, 9, 9, 9], "role": "header"}
    ]

    missing = cli("text", "D-0001", "--find", "нет такого")
    assert missing.exit_code == 0
    assert missing.stdout.strip() == "Не найдено"


def test_cli_find_conflicts_with_page(db, cli) -> None:
    _seed_find(db)

    result = cli("text", "D-0001", "--find", "Срок", "--page", "1")

    assert result.exit_code != 0
    assert "Укажите либо --page, либо --find" in result.stderr
