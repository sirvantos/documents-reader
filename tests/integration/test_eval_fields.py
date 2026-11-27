"""`docreader eval fields`: comparing fields with the gold set (feature 02, T026).

research.md R-7, R-13; contracts/cli.md «docreader eval fields»; contracts/files.md
«Результаты из файла». The gold set is written with `gold.load` directly: the
comparison does not depend on how the gold was made.
"""

from __future__ import annotations

import csv
import io
import json
from functools import partial
from pathlib import Path

import pytest

from docreader import gold
from docreader.gold import CellValue, GoldPath, GoldState, LoadKind, ParsedGold
from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import NOT_FOUND, answer, field
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk

PROTOTYPE = (
    "contract_number", "customer_name_short", "contractor_name_short",
    "amount_without_vat", "amount_with_vat", "contract_end_date",
)


def value(text: str, normalized: str) -> CellValue:
    return CellValue(GoldState.VALUE, (text,), (normalized,), GoldPath.AGREE)


ABSENT = CellValue(GoldState.ABSENT, (), (), GoldPath.ABSENT_MARKED)


@pytest.fixture
def setup(cli, db, tmp_path: Path, use_model):  # type: ignore[no-untyped-def]
    """D-0001 extracted (base answers with changes), D-0002 extracted then made stale,
    D-0003 not extracted; a gold set with one pair of every outcome."""
    makers = [
        partial(mk.make_extraction_contract, variant="base"),
        partial(mk.make_extraction_contract, variant="missing"),
        mk.make_contract_ru,
    ]
    ids = add_files(cli, tmp_path / "in", makers)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    use_model(ScriptedModel(
        answer(
            amount_with_vat=field("1 440 000 рублей", "этой цитаты нет в договоре", "2.1"),
            amount_without_vat=NOT_FOUND,
        ),
        answer(),
    ))
    assert cli("extract", ids[0], ids[1]).exit_code == 0
    d1, d2, d3 = ids
    cells = {
        (d1, "contract_number"): value("ДП-17/2026", "ДП-17/2026"),  # correct
        (d1, "customer_name_short"): value("ООО «Гамма»", 'ООО "Гамма"'),  # wrong
        (d1, "contractor_name_short"): ABSENT,  # invented
        (d1, "amount_with_vat"): value("1 440 000", "1440000.00"),  # missed, rejected
        (d1, "amount_without_vat"): value("1 200 000", "1200000.00"),  # missed
        (d1, "vat_rate"): value("20", "20"),  # no_result: not extracted
        (d2, "contract_number"): value("ДП-17/2026", "ДП-17/2026"),  # no_result: stale
        (d3, "contract_number"): value("Х-1", "Х-1"),  # no_result: not run
    }
    coverage = frozenset(cells)
    gold.load(db, ParsedGold(LoadKind.REVIEW, coverage, cells, [], []),
              file_name="eval/g.json", file_bytes=b"g", yes=True)
    db.execute(
        "UPDATE document_text SET text_sha256 = %s WHERE document_id = %s", ("f" * 64, d2)
    )
    return ids


def run_fields(cli, *args: object, code: int = 0) -> dict:  # type: ignore[no-untyped-def,type-arg]
    result = cli("eval", "fields", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout) if code == 0 else {}


def cases(db, record: int) -> dict[str, tuple[str, list[str]]]:  # type: ignore[no-untyped-def]
    return {
        k: (o, f)
        for k, o, f in db.execute(
            "SELECT case_key, outcome, flags FROM eval_case WHERE result_id = %s", (record,)
        ).fetchall()
    }


def test_one_case_of_every_outcome(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    d1, d2, d3 = setup
    report = run_fields(cli, "--label", "проверка")
    got = cases(db, report["record"])
    assert got[f"{d1}/contract_number"] == ("correct", [])
    assert got[f"{d1}/customer_name_short"] == ("wrong", [])
    assert got[f"{d1}/contractor_name_short"] == ("invented", [])
    assert got[f"{d1}/amount_with_vat"] == ("missed", ["rejected"])
    assert got[f"{d1}/amount_without_vat"] == ("missed", [])
    # customer_name_short is marked for D-0001 only: D-0002 has no gold row for it
    assert got[f"{d2}/customer_name_short"] == ("unlabeled", [])
    assert f"{d1}/contract_end_date" not in got  # no gold row at all: not in the default set
    assert got[f"{d1}/vat_rate"] == ("no_result", ["not_extracted"])
    assert got[f"{d2}/contract_number"] == ("no_result", ["stale"])
    assert got[f"{d3}/contract_number"] == ("no_result", ["not_run"])


def test_pairs_are_all_documents_times_the_marked_fields(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    report = run_fields(cli)
    marked = {"contract_number", "customer_name_short", "contractor_name_short",
              "amount_with_vat", "amount_without_vat", "vat_rate"}
    assert report["pairs"] == 3 * len(marked)
    assert len(cases(db, report["record"])) == report["pairs"]
    assert sum(report["counts"].values()) == report["pairs"]  # SC-002


def test_fields_option_selects_the_set(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    report = run_fields(cli, "--fields", "prototype")
    keys = cases(db, report["record"])
    assert report["pairs"] == 3 * 6
    assert {k.split("/", 1)[1] for k in keys} == set(PROTOTYPE)


def test_record_holds_provenance_versions_and_metrics(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    report = run_fields(cli, "--label", "подсказка 05.1")
    row = db.execute(
        "SELECT label, stage, provenance, gold_sha256, reviewed_share, metrics, review_file, "
        "from_file FROM eval_result WHERE id = %s",
        (report["record"],),
    ).fetchone()
    label, stage, provenance, gold_sha, reviewed, metrics, review_file, from_file = row
    assert (label, stage, from_file) == ("подсказка 05.1", "fields", None)
    assert provenance["code_version"]
    [run] = provenance["runs"]
    assert run["model"] == "qwen3.6-27b-4bit" and run["prompt_version"] == "05.1"
    assert gold_sha == gold.current_sha256(db)
    assert float(reviewed) == pytest.approx(1.0)
    assert metrics["overall"]["counts"]["correct"] == 1
    assert review_file.startswith("eval/") and review_file.endswith(".csv")


def test_stored_metrics_equal_a_recount_from_the_cases(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    report = run_fields(cli)
    metrics = db.execute(
        "SELECT metrics FROM eval_result WHERE id = %s", (report["record"],)
    ).fetchone()[0]
    recount: dict[str, int] = {}
    for outcome, _ in cases(db, report["record"]).values():
        recount[outcome] = recount.get(outcome, 0) + 1
    stored = {k: v for k, v in metrics["overall"]["counts"].items() if v}
    assert stored == recount


def test_review_file_holds_gold_and_system_values(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    d1, _, _ = setup
    report = run_fields(cli)
    path = data_dir / report["review_file"]
    raw = path.read_bytes()
    assert raw.startswith("﻿".encode())
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert {"document_id", "field", "outcome", "flags", "gold", "system", "clause",
            "quote"} <= set(rows[0])
    wrong = next(r for r in rows if r["document_id"] == d1 and r["field"] == "customer_name_short")
    assert wrong["outcome"] == "wrong"
    assert wrong["gold"] == "ООО «Гамма»"
    assert "Альфа" in wrong["system"]
    assert wrong["clause"] and wrong["quote"]


def test_same_comparison_twice_gives_two_identical_records(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    first = run_fields(cli, "--label", "x")
    second = run_fields(cli, "--label", "x")
    assert first["record"] != second["record"]
    assert cases(db, first["record"]) == cases(db, second["record"])  # SC-003


def test_rules_source(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    d1, _, _ = setup
    report = run_fields(cli, "--source", "rules", "--fields", "prototype")
    row = db.execute(
        "SELECT stage, provenance FROM eval_result WHERE id = %s", (report["record"],)
    ).fetchone()
    assert row[0] == "rules"
    assert row[1]["rules_version"] == "02.4"
    got = cases(db, report["record"])
    assert got[f"{d1}/contract_number"] == ("correct", [])
    # the rules find exactly the gold prices, where feature 05 missed both
    assert got[f"{d1}/amount_without_vat"] == ("correct", [])
    assert got[f"{d1}/amount_with_vat"] == ("correct", [])


def test_results_from_a_file(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    d1, _, _ = setup
    path = data_dir / "eval" / "results.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "format": "docreader-field-results/1",
        "source": "синтетика",
        "values": [
            {"document": d1, "field": "contract_number", "result": "found",
             "value": "№ ДП-17/2026"},
            {"document": d1, "field": "customer_name_short", "result": "found",
             "value": "ООО «Гамма»"},
            {"document": d1, "field": "amount_with_vat", "result": "rejected"},
            {"document": d1, "field": "contractor_name_short", "result": "not_found"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    report = run_fields(cli, "--from", path)
    row = db.execute(
        "SELECT stage, from_file, provenance FROM eval_result WHERE id = %s",
        (report["record"],),
    ).fetchone()
    assert row[0] == "fields" and row[1] == "eval/results.json"
    assert row[2]["source"] == "синтетика"
    got = cases(db, report["record"])
    assert got[f"{d1}/contract_number"] == ("correct", [])
    assert got[f"{d1}/customer_name_short"] == ("correct", [])
    assert got[f"{d1}/amount_with_vat"] == ("missed", ["rejected"])
    assert got[f"{d1}/contractor_name_short"] == ("correct", [])
    assert got[f"{d1}/amount_without_vat"] == ("no_result", ["not_run"])


def test_empty_gold_is_a_user_error_and_writes_nothing(cli, db, tmp_path) -> None:  # type: ignore[no-untyped-def]
    add_files(cli, tmp_path / "in", [mk.make_contract_ru])
    result = cli("eval", "fields")
    assert result.exit_code == 1
    assert "эталон" in result.stderr
    assert db.execute("SELECT count(*) FROM eval_result").fetchone()[0] == 0


def test_output_holds_no_values(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    secrets = synthetic_secrets(db, extra=["ООО «Гамма»"])
    for args in ((), ("--json",), ("--source", "rules")):
        result = cli("eval", "fields", *args)
        assert result.exit_code == 0, result.stderr
        assert_no_values(result.stdout + result.stderr, secrets)
    text = cli("eval", "fields").stdout
    assert "разбор: eval/" in text
    assert "customer_name_short" in text


def test_provenance_holds_the_settings_of_the_extraction_runs(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    # converge T053 (research R-13)
    report = run_fields(cli)
    [prov] = db.execute(
        "SELECT provenance FROM eval_result WHERE id = %s", (report["record"],)
    ).fetchone()
    [run] = prov["runs"]
    stored = db.execute("SELECT settings FROM run WHERE id = %s", (run["id"],)).fetchone()[0]
    assert run["settings"] == stored and stored
