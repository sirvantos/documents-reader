"""`docreader eval blind report` (feature 02, T025, research R-10)."""

from __future__ import annotations

import csv
import io
import json

from docreader import gold
from docreader.gold import CellValue, GoldPath, GoldState, LoadKind, ParsedGold
from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.integration.gold_fixtures import insert_documents


def cell(norm: str, path: GoldPath = GoldPath.TEMPLATE) -> CellValue:
    return CellValue(GoldState.VALUE, (norm,), (norm,), path)


def put(db, kind: LoadKind, cells: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    gold.load(db, ParsedGold(kind, frozenset(cells), cells, [], []), file_name=kind.value,
              file_bytes=kind.value.encode(), yes=True)


def report(cli, *args: object, code: int = 0) -> dict:  # type: ignore[no-untyped-def,type-arg]
    result = cli("eval", "blind", "report", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout) if code == 0 else {}


def setup(db) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 2)
    db.execute("INSERT INTO blind_pick (document_id) VALUES ('D-0001')")
    put(db, LoadKind.REVIEW, {("D-0001", "contract_number"): cell("Х-0", GoldPath.AGREE)})
    put(db, LoadKind.BLIND, {
        ("D-0001", "contract_number"): cell("Х-1"),
        ("D-0001", "amount_with_vat"): cell("100.00"),
        ("D-0001", "contract_end_date"): cell("2027-01-01"),
    })
    put(db, LoadKind.REVIEW, {
        ("D-0001", "amount_with_vat"): cell("200.00", GoldPath.AGREE),
        ("D-0001", "contract_end_date"): cell("2027-01-01", GoldPath.TYPED),
        ("D-0002", "contract_number"): cell("Х-2", GoldPath.AGREE),  # not a blind document
    })


def test_report_counts_and_record(cli, db) -> None:  # type: ignore[no-untyped-def]
    setup(db)
    got = report(cli, "--label", "первый эталон")
    # contract_number was reviewed before the blind load: not counted
    assert got["pairs"] == 2 and got["not_reviewed"] == 1
    assert (got["same"], got["differs"]) == (1, 1)
    assert (got["confirmed_pairs"], got["confirmed_differs"]) == (1, 1)
    row = db.execute(
        "SELECT stage, label, metrics FROM eval_result WHERE id = %s", (got["record"],)
    ).fetchone()
    assert row[:2] == ("gold_blind", "первый эталон")
    assert row[2]["differs"] == 1
    outcomes = dict(db.execute(
        "SELECT case_key, outcome FROM eval_case WHERE result_id = %s", (got["record"],)
    ).fetchall())
    assert outcomes == {"D-0001/amount_with_vat": "differs",
                        "D-0001/contract_end_date": "same"}


def test_review_file_has_both_values(cli, db, data_dir) -> None:  # type: ignore[no-untyped-def]
    setup(db)
    got = report(cli)
    raw = (data_dir / got["review_file"]).read_bytes()
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    differs = next(r for r in rows if r["field"] == "amount_with_vat")
    assert (differs["outcome"], differs["blind"], differs["reviewed"], differs["path"]) == (
        "differs", "100.00", "200.00", "agree")


def test_second_report_keeps_the_first(cli, db) -> None:  # type: ignore[no-untyped-def]
    setup(db)
    first = report(cli)["record"]
    put(db, LoadKind.REVIEW, {("D-0001", "amount_with_vat"): cell("100.00", GoldPath.TYPED)})
    second = report(cli)
    assert second["record"] != first and second["differs"] == 0
    assert db.execute("SELECT count(*) FROM eval_result WHERE stage = 'gold_blind'"
                      ).fetchone()[0] == 2


def test_summary_goes_into_later_records(cli, db) -> None:  # type: ignore[no-untyped-def]
    setup(db)
    record = report(cli)["record"]
    summary = db.execute("SELECT metrics FROM eval_result WHERE id = %s", (record,)).fetchone()[0]
    assert summary["confirmed_differs"] == 1


def test_no_blind_marking_is_a_user_error(cli, db) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 1)
    result = cli("eval", "blind", "report")
    assert result.exit_code == 1
    assert "слеп" in result.stderr


def test_output_holds_no_values(cli, db) -> None:  # type: ignore[no-untyped-def]
    setup(db)
    secrets = synthetic_secrets(db)
    for extra in ((), ("--json",)):
        result = cli("eval", "blind", "report", *extra)
        assert result.exit_code == 0, result.stderr
        assert_no_values(result.stdout + result.stderr, secrets)
