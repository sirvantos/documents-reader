"""Template and blind control commands (feature 02, T023; research R-10)."""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path

import pytest

from docreader import gold
from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import answer
from tests.integration.gold_fixtures import insert_documents
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk


def as_json(cli, *args: object, code: int = 0) -> dict:  # type: ignore[no-untyped-def,type-arg]
    result = cli("eval", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout) if code == 0 else {}


# --- eval template --------------------------------------------------------------------------


@pytest.mark.parametrize(("fields", "count"), [("prototype", 6), ("queue1", 35), ("all", 68)])
def test_template_columns(cli, db, data_dir, fields: str, count: int) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 3)
    report = as_json(cli, "template", "--fields", fields)
    path = data_dir / report["path"]
    assert path.parent == data_dir / "eval" and path.suffix == ".csv"
    lines = path.read_bytes().decode("utf-8-sig").splitlines()
    header = [c.strip('"') for c in lines[0].split(";")]
    assert header[0] == "document_id" and len(header) == count + 1
    assert header[1:7] == ["contract_number", "customer_name_short", "contractor_name_short",
                           "amount_without_vat", "amount_with_vat", "contract_end_date"]
    assert lines[1].startswith('"#вид"') and lines[2].startswith('"#подсказка"')
    rows = lines[3:]
    assert [r.split(";")[0].strip('"') for r in rows] == ["D-0001", "D-0002", "D-0003"]
    assert all(set(c.strip('"') for c in r.split(";")[1:]) == {""} for r in rows)
    assert (report["documents"], report["fields"]) == (3, count)


def test_template_default_is_queue1(cli, db) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 1)
    assert as_json(cli, "template")["fields"] == 35


def test_template_documents_option(cli, db, data_dir) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 3)
    report = as_json(cli, "template", "--documents", "D-0002", "--fields", "prototype")
    lines = (data_dir / report["path"]).read_bytes().decode("utf-8-sig").splitlines()
    assert [r.split(";")[0].strip('"') for r in lines[3:]] == ["D-0002"]


def test_template_never_overwrites(cli, db, data_dir) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 1)
    target = data_dir / "eval" / "t.csv"
    target.parent.mkdir()
    target.write_text("keep", encoding="utf-8")
    result = cli("eval", "template", "--out", target)
    assert result.exit_code == 1
    assert target.read_text(encoding="utf-8") == "keep"


def test_template_out_outside_the_data_dir(cli, db, tmp_path) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 1)
    result = cli("eval", "template", "--out", tmp_path / "t.csv")
    assert result.exit_code == 1
    assert not (tmp_path / "t.csv").exists()


def test_template_loads_back_with_nothing_marked(cli, db, data_dir) -> None:  # type: ignore[no-untyped-def]
    insert_documents(db, 2)
    report = as_json(cli, "template", "--fields", "prototype")
    loaded = cli("eval", "load", data_dir / report["path"])
    assert loaded.exit_code == 0, loaded.stderr
    assert db.execute("SELECT count(*) FROM gold_field").fetchone()[0] == 0


# --- eval blind -----------------------------------------------------------------------------


def distinct_contracts(count: int, start: int = 0) -> list:  # type: ignore[type-arg]
    """Makers of `base` contracts that differ by a trailing PDF comment (intake keeps one
    copy of identical files; the generator itself is not changed)."""

    def make(path: Path, n: int) -> Path:
        mk.make_extraction_contract(path, "base")
        with path.open("ab") as fh:
            fh.write(f"\n% copy {n}\n".encode())
        return path

    return [partial(make, n=start + i) for i in range(count)]


@pytest.fixture
def extracted(cli, db, tmp_path: Path, use_model) -> list[str]:  # type: ignore[no-untyped-def]
    """Seven extracted synthetic contracts; D-0002…D-0007 look like scans for the pick."""
    ids = add_files(cli, tmp_path / "in", distinct_contracts(7))
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    use_model(ScriptedModel(*[answer() for _ in ids]))
    assert cli("extract", "--all").exit_code == 0
    db.execute("UPDATE page SET kind = 'scan' WHERE document_id <> %s", (ids[0],))
    return ids


def test_blind_pick_and_template(cli, db, data_dir, extracted) -> None:  # type: ignore[no-untyped-def]
    report = as_json(cli, "blind", "pick")
    assert len(report["documents"]) == 5
    assert report["text_layer"] == [extracted[0]]
    assert report["documents"][0] == extracted[0]
    stored = [r[0] for r in db.execute("SELECT document_id FROM blind_pick ORDER BY 1")]
    assert stored == sorted(report["documents"])
    lines = (data_dir / report["template"]).read_bytes().decode("utf-8-sig").splitlines()
    assert len(lines[0].split(";")) == 7
    assert [r.split(";")[0].strip('"') for r in lines[3:]] == sorted(report["documents"])


def test_blind_pick_is_kept_unless_again(cli, db, tmp_path, extracted, use_model) -> None:  # type: ignore[no-untyped-def]
    first = as_json(cli, "blind", "pick")["documents"]
    more = add_files(cli, tmp_path / "more", distinct_contracts(6, start=7))
    assert cli("read").exit_code == 0 and cli("parse").exit_code == 0
    use_model(ScriptedModel(*[answer() for _ in more]))
    assert cli("extract", "--all").exit_code == 0
    db.execute("UPDATE page SET kind = 'scan' WHERE document_id <> %s", (extracted[0],))
    assert as_json(cli, "blind", "pick")["documents"] == first
    again = as_json(cli, "blind", "pick", "--again")["documents"]
    assert again != first
    stored = [r[0] for r in db.execute("SELECT document_id FROM blind_pick ORDER BY 1")]
    assert stored == sorted(again)


def test_blind_load_goes_to_gold_blind_and_shows_the_cards(cli, db, data_dir, extracted) -> None:  # type: ignore[no-untyped-def]
    report = as_json(cli, "blind", "pick")
    review = as_json(cli, "review")
    assert sorted(review["blind_waiting"]) == sorted(report["documents"])
    doc = report["documents"][0]
    path = data_dir / "eval" / "blind-filled.csv"
    path.write_bytes(
        ("﻿" '"document_id";"contract_number";"amount_with_vat"\r\n'
         f'"{doc}";"ДП-17/2026";"сто рублей много"\r\n').encode()
    )
    result = cli("eval", "blind", "load", path)
    assert result.exit_code == 0, result.stderr
    assert "строка 2, столбец amount_with_vat" in result.stdout
    rows = db.execute("SELECT document_id, field FROM gold_blind").fetchall()
    assert rows == [(doc, "contract_number")]
    assert db.execute("SELECT count(*) FROM gold_field").fetchone()[0] == 0
    assert doc not in as_json(cli, "review")["blind_waiting"]
    assert_no_values(result.stdout + result.stderr,
                     synthetic_secrets(db, extra=["сто рублей много"]))


def test_blind_load_of_a_document_not_picked_is_refused(cli, db, data_dir, extracted) -> None:  # type: ignore[no-untyped-def]
    picked = as_json(cli, "blind", "pick")["documents"]
    other = next(d for d in extracted if d not in picked)
    path = data_dir / "eval" / "b.csv"
    path.write_bytes(('"document_id";"contract_number"\r\n' f'"{other}";"Х-1"\r\n')
                     .encode())
    result = cli("eval", "blind", "load", path)
    assert result.exit_code == 0
    assert other in result.stdout  # the row is skipped with a reason naming the document
    assert db.execute("SELECT count(*) FROM gold_blind").fetchone()[0] == 0


def test_blind_template_uses_the_gold_format(cli, db, data_dir, extracted) -> None:  # type: ignore[no-untyped-def]
    report = as_json(cli, "blind", "pick")
    parsed = gold.parse_template((data_dir / report["template"]).read_bytes(),
                                 set(report["documents"]))
    assert parsed.errors == [] and parsed.values == {}
    assert len(parsed.coverage) == 5 * 6
