"""Integration tests for `docreader read-report` (tasks T049, T052, feature 03).

Everything goes through the CLI; expected numbers are counted straight from the
tables `page_text` and `page_flag` in the test.
"""

from __future__ import annotations

import csv
import json
import re

import pytest

from tests.integration.test_read import add_files, set_stage
from tests.synthetic import make_pdfs as mk

CODES = (
    "scan_unread",
    "ocr_text",
    "unreadable",
    "maybe_not_russian",
    "empty",
    "reading_order_unknown",
    "low_recognition_quality",
    "scan_no_text",
)
HEADERS = [
    "ID", "Имя", "Стр.", "Прочит.", "Скан", "Распозн.", "Нечит.", "Не рус.",
    "Пустые", "Порядок", "Низк. кач.", "Без текста", "Таблицы", "Состояние",
]
NOTHING = "Нет прочитанных документов — выполните docreader read"
STATE_WORDS = {"done": "готово", "needs_review": "требует просмотра", "failed": "ошибка"}


@pytest.fixture
def read_docs(cli, db, tmp_path):
    """Four read documents with different flags, then a pending one and a failed one."""
    ids = add_files(
        cli,
        tmp_path / "in",
        [
            lambda p: mk.make_contract_ru(p, pages=3),
            lambda p: mk.make_mixed(p, pages=4),
            mk.make_blank_page,
            mk.make_image_with_invisible_text,
            lambda p: mk.make_kazakh_ru(p, 3),
        ],
    )
    assert cli("read").exit_code == 0
    (pending,) = add_files(cli, tmp_path / "more", [lambda p: mk.make_digital(p, pages=1)])
    (failed,) = add_files(
        cli, tmp_path / "more2", [lambda p: mk.make_digital(p, pages=2, text_seed="Z")]
    )
    assert (pending, failed) == ("D-0006", "D-0007")
    set_stage(db, failed, "reading", "failed", "не удалось прочитать")
    return {"read": ids, "pending": pending, "failed": failed}


def expected(db, doc_id: str) -> dict:
    name, pages, state = db.execute(
        "SELECT d.original_name, d.page_count, s.state FROM document d"
        " JOIN stage_status s ON s.document_id = d.id AND s.stage = 'reading'"
        " WHERE d.id = %s",
        (doc_id,),
    ).fetchone()
    lines = db.execute(
        "SELECT lines, has_table FROM page_text WHERE document_id = %s", (doc_id,)
    ).fetchall()
    flags = {c: 0 for c in CODES}
    for (code,) in db.execute("SELECT code FROM page_flag WHERE document_id = %s", (doc_id,)):
        flags[code] += 1
    return {
        "id": doc_id,
        "name": name,
        "pages": pages,
        "read": sum(1 for ls, _ in lines if len(ls) > 0),
        "flags": flags,
        "tables": sum(1 for _, t in lines if t),
        "state": state,
    }


def all_expected(db, ids) -> list[dict]:
    return [expected(db, i) for i in ids]


def totals_of(rows: list[dict]) -> dict:
    return {
        "pages": sum(r["pages"] for r in rows),
        "read": sum(r["read"] for r in rows),
        "flags": {c: sum(r["flags"][c] for r in rows) for c in CODES},
        "tables": sum(r["tables"] for r in rows),
    }


def report_json(cli) -> dict:
    result = cli("read-report", "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_json_matches_independent_counts(cli, db, read_docs):
    ids = read_docs["read"] + [read_docs["failed"]]
    exp = all_expected(db, ids)
    report = report_json(cli)
    assert report["documents"] == exp
    assert report["totals"] == totals_of(exp)
    # the data really exercise several flags
    assert totals_of(exp)["flags"]["scan_unread"] > 0
    assert totals_of(exp)["flags"]["empty"] > 0
    assert totals_of(exp)["flags"]["maybe_not_russian"] > 0


def test_pending_document_absent_and_failed_has_zero_counts(cli, db, read_docs):
    report = report_json(cli)
    by_id = {d["id"]: d for d in report["documents"]}
    assert read_docs["pending"] not in by_id
    failed = by_id[read_docs["failed"]]
    assert failed["state"] == "failed"
    assert failed["read"] == 0
    assert failed["tables"] == 0
    assert set(failed["flags"].values()) == {0}
    assert failed["pages"] == 2
    assert [d["id"] for d in report["documents"]] == sorted(by_id)


def test_text_table_layout_and_totals_row(cli, db, read_docs):
    ids = read_docs["read"] + [read_docs["failed"]]
    exp = all_expected(db, ids)
    result = cli("read-report")
    assert result.exit_code == 0, result.stderr
    lines = result.stdout.rstrip("\n").split("\n")
    for h in HEADERS:
        assert h in lines[0]
    assert len(lines) == 1 + len(exp) + 1
    for row, line in zip(exp, lines[1:-1], strict=True):
        cells = line.split()
        assert cells[0] == row["id"]
        word = STATE_WORDS[row["state"]]
        assert line.endswith(word)
        nums = [row["pages"], row["read"], *row["flags"].values(), row["tables"]]
        tail = line[: -len(word)].split()[-len(nums):]
        assert [int(x) for x in tail] == nums
    total = totals_of(exp)
    last = lines[-1]
    assert last.startswith("Итого")
    assert [int(x) for x in last.split()[1:]] == [
        total["pages"], total["read"], *total["flags"].values(), total["tables"]
    ]
    assert read_docs["pending"] not in result.stdout


def test_csv_default_path(cli, db, read_docs, data_dir):
    result = cli("read-report", "--csv")
    assert result.exit_code == 0, result.stderr
    files = list((data_dir / "reports").glob("reading-*.csv"))
    assert len(files) == 1
    assert re.fullmatch(r"reading-\d{8}-\d{6}\.csv", files[0].name)
    assert f"Отчёт сохранён: {files[0]}" in result.stdout


def test_csv_explicit_path_content(cli, db, read_docs, tmp_path):
    target = tmp_path / "out" / "r.csv"
    target.parent.mkdir()
    result = cli("read-report", "--csv", target)
    assert result.exit_code == 0, result.stderr
    assert f"Отчёт сохранён: {target}" in result.stdout
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert text.split("\n")[0].rstrip("\r") == ";".join(HEADERS)
    rows = list(csv.reader(text.splitlines(), delimiter=";"))
    ids = read_docs["read"] + [read_docs["failed"]]
    exp = all_expected(db, ids)
    assert len(rows) == 1 + len(exp) + 1
    for row, got in zip(exp, rows[1:-1], strict=True):
        assert got == [
            row["id"], row["name"], str(row["pages"]), str(row["read"]),
            *(str(row["flags"][c]) for c in CODES), str(row["tables"]), STATE_WORDS[row["state"]],
        ]
    total = totals_of(exp)
    assert rows[-1][0] == "Итого"
    assert rows[-1][2:-1] == [
        str(total["pages"]), str(total["read"]),
        *(str(total["flags"][c]) for c in CODES), str(total["tables"]),
    ]


def test_csv_has_no_contract_text(cli, db, read_docs, tmp_path):
    target = tmp_path / "r.csv"
    assert cli("read-report", "--csv", target).exit_code == 0
    text = target.read_text(encoding="utf-8-sig")
    allowed = {"Итого", *HEADERS, *STATE_WORDS.values()}
    for row in csv.reader(text.splitlines(), delimiter=";"):
        for cell in row:
            assert cell in allowed or re.fullmatch(r"D-\d{4}|\d+|f\d+\.pdf|", cell), cell
    # no stored line text appears in the file
    for (lines,) in db.execute("SELECT lines FROM page_text"):
        for line in lines:
            assert line["text"] not in text


def test_nothing_read_yet(cli, tmp_path):
    add_files(cli, tmp_path / "in", [lambda p: mk.make_digital(p, pages=1)])
    result = cli("read-report")
    assert result.exit_code == 0
    assert NOTHING in result.stdout
    assert cli("read-report", "--json").exit_code == 0
