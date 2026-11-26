"""Loading the gold set into the database (feature 02, T012, T014; research R-5, R-6)."""

from __future__ import annotations

import psycopg

from docreader import gold
from docreader.gold import CellValue, GoldPath, GoldState, LoadKind, ParsedGold
from tests.integration.gold_fixtures import insert_documents

A = ("D-0001", "contract_number")
B = ("D-0001", "amount_with_vat")
C = ("D-0002", "contract_number")


def value(v: str, n: str | None = None, path: GoldPath = GoldPath.TEMPLATE) -> CellValue:
    return CellValue(GoldState.VALUE, (v,), (n or v,), path)


def parsed(values: dict, coverage: set, kind: LoadKind = LoadKind.TEMPLATE) -> ParsedGold:  # type: ignore[type-arg]
    return ParsedGold(kind, frozenset(coverage), values, [], [])


def rows(db: psycopg.Connection, table: str = "gold_field") -> dict:  # type: ignore[type-arg]
    return {
        (r[0], r[1]): (r[2], tuple(r[3]))
        for r in db.execute(
            f"SELECT document_id, field, state, values_normalized FROM {table}"
        ).fetchall()
    }


def test_first_load_writes_rows_and_a_load(db: psycopg.Connection) -> None:
    insert_documents(db, 2)
    report = gold.load(db, parsed({A: value("ДП-1"), C: value("ДП-2")}, {A, B, C}),
                       file_name="eval/t.csv", file_bytes=b"x", yes=False)
    assert report.load_id is not None
    assert not report.needs_confirmation
    assert rows(db) == {A: ("value", ("ДП-1",)), C: ("value", ("ДП-2",))}
    load = db.execute("SELECT kind, file_name, gold_sha256, counts FROM gold_load").fetchone()
    assert load[0] == "template" and load[1] == "eval/t.csv"
    assert load[2] == report.gold_sha256
    assert load[3]["added"] == 2


def test_removal_without_yes_changes_nothing(db: psycopg.Connection) -> None:
    insert_documents(db, 2)
    gold.load(db, parsed({A: value("1"), C: value("2")}, {A, C}), file_name="a", file_bytes=b"a",
              yes=False)
    before = rows(db)
    loads = db.execute("SELECT count(*) FROM gold_load").fetchone()[0]

    report = gold.load(db, parsed({A: value("1")}, {A, C}), file_name="b", file_bytes=b"b",
                       yes=False)

    assert report.needs_confirmation
    assert report.load_id is None
    assert report.diff.removed == [C]
    assert rows(db) == before
    assert db.execute("SELECT count(*) FROM gold_load").fetchone()[0] == loads


def test_removal_with_yes_replaces_the_coverage(db: psycopg.Connection) -> None:
    insert_documents(db, 3)
    gold.load(db, parsed({A: value("1"), C: value("2"), ("D-0003", "contract_number"): value("3")},
                         {A, C, ("D-0003", "contract_number")}),
              file_name="a", file_bytes=b"a", yes=False)

    report = gold.load(db, parsed({A: value("11")}, {A, C}), file_name="b", file_bytes=b"b",
                       yes=True)

    assert report.load_id is not None
    assert rows(db) == {A: ("value", ("11",)), ("D-0003", "contract_number"): ("value", ("3",))}


def test_same_content_twice_keeps_the_version(db: psycopg.Connection) -> None:
    insert_documents(db, 1)
    p = parsed({A: value("1")}, {A})
    first = gold.load(db, p, file_name="a", file_bytes=b"a", yes=False)
    second = gold.load(db, p, file_name="a2", file_bytes=b"a2", yes=False)
    assert first.gold_sha256 == second.gold_sha256
    assert second.diff.same == [A]


def test_version_covers_the_whole_gold_not_the_file(db: psycopg.Connection) -> None:
    insert_documents(db, 2)
    first = gold.load(db, parsed({A: value("1")}, {A}), file_name="a", file_bytes=b"a", yes=False)
    second = gold.load(db, parsed({C: value("2")}, {C}), file_name="b", file_bytes=b"b", yes=False)
    assert first.gold_sha256 != second.gold_sha256
    assert gold.current_sha256(db) == second.gold_sha256


def test_review_load_keeps_path_clause_and_system_value(db: psycopg.Connection) -> None:
    insert_documents(db, 1)
    cell = CellValue(GoldState.VALUE, ("1 000 руб.",), ("1000.00",), GoldPath.CHOSEN, "2.1",
                     "1200.00")
    gold.load(db, parsed({B: cell}, {B}, LoadKind.REVIEW), file_name="r.json", file_bytes=b"r",
              yes=False)
    row = db.execute(
        "SELECT path, clause_key, system_normalized, values_text FROM gold_field"
    ).fetchone()
    assert row == ("chosen", "2.1", "1200.00", ["1 000 руб."])


def test_other_kind_pairs_are_reported(db: psycopg.Connection) -> None:
    insert_documents(db, 1)
    gold.load(db, parsed({A: value("1", path=GoldPath.AGREE)}, {A}, LoadKind.REVIEW),
              file_name="r", file_bytes=b"r", yes=False)
    report = gold.load(db, parsed({A: value("1")}, {A}), file_name="t", file_bytes=b"t",
                       yes=False)
    assert report.diff.other_kind == [A]
    assert db.execute("SELECT path FROM gold_field").fetchone()[0] == "template"


def test_blind_load_goes_to_gold_blind(db: psycopg.Connection) -> None:
    insert_documents(db, 1)
    gold.load(db, parsed({A: value("1")}, {A}, LoadKind.BLIND), file_name="b", file_bytes=b"b",
              yes=False)
    assert rows(db) == {}
    assert rows(db, "gold_blind") == {A: ("value", ("1",))}
    assert db.execute("SELECT kind FROM gold_load").fetchone()[0] == "blind"


def test_absent_is_stored_with_empty_arrays(db: psycopg.Connection) -> None:
    insert_documents(db, 1)
    absent = CellValue(GoldState.ABSENT, (), (), GoldPath.ABSENT_MARKED)
    gold.load(db, parsed({A: absent}, {A}, LoadKind.REVIEW), file_name="r", file_bytes=b"r",
              yes=False)
    assert rows(db) == {A: ("absent", ())}
