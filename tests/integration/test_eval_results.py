"""`docreader eval results|show|compare|export` (feature 02, T030, research R-13)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from docreader import gold
from docreader.gold import CellValue, GoldPath, GoldState, LoadKind, ParsedGold
from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.integration.test_eval_fields import setup  # noqa: F401 — the fixture of the fields tests


def run(cli, *args: object, code: int = 0) -> dict:  # type: ignore[no-untyped-def,type-arg]
    result = cli("eval", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout) if code == 0 else {}


def results_file(data_dir: Path, values: list[dict]) -> Path:  # type: ignore[type-arg]
    path = data_dir / "eval" / f"r{len(list((data_dir / 'eval').glob('r*.json')))}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"format": "docreader-field-results/1", "source": "t",
                                "values": values}, ensure_ascii=False), encoding="utf-8")
    return path


def two_records(cli, data_dir: Path, d1: str) -> tuple[int, int]:  # type: ignore[no-untyped-def]
    a = results_file(data_dir, [
        {"document": d1, "field": "contract_number", "result": "not_found"},
        {"document": d1, "field": "customer_name_short", "result": "found",
         "value": "ООО «Гамма»"},
    ])
    b = results_file(data_dir, [
        {"document": d1, "field": "contract_number", "result": "found", "value": "ДП-17/2026"},
        {"document": d1, "field": "customer_name_short", "result": "found",
         "value": "ООО «Дельта»"},
    ])
    first = run(cli, "fields", "--from", a, "--label", "до")["record"]
    second = run(cli, "fields", "--from", b, "--label", "после")["record"]
    return first, second


def test_results_lists_every_record(cli, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    run(cli, "fields", "--label", "a")
    run(cli, "fields", "--source", "rules", "--label", "b")
    report = run(cli, "results")
    assert [(r["label"], r["stage"]) for r in report["records"]] == [("a", "fields"),
                                                                     ("b", "rules")]
    assert all(r["current_gold"] for r in report["records"])
    assert [r["stage"] for r in run(cli, "results", "--stage", "rules")["records"]] == ["rules"]


def test_old_gold_version_is_marked(cli, db, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    d1 = setup[0]
    record = run(cli, "fields")["record"]
    cell = CellValue(GoldState.VALUE, ("ДП-1",), ("ДП-1",), GoldPath.TEMPLATE)
    gold.load(db, ParsedGold(LoadKind.TEMPLATE, frozenset({(d1, "contract_number")}),
                             {(d1, "contract_number"): cell}, [], []),
              file_name="t", file_bytes=b"t", yes=True)
    [row] = [r for r in run(cli, "results")["records"] if r["id"] == record]
    assert row["current_gold"] is False


def test_show_lists_exactly_the_cases_of_a_number(cli, db, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    d1 = setup[0]
    record = run(cli, "fields")["record"]
    shown = run(cli, "show", record, "--outcome", "missed")
    keys = {c["case_key"] for c in shown["cases"]}
    assert keys == {f"{d1}/amount_with_vat", f"{d1}/amount_without_vat"}
    counts = shown["record"]["metrics"]["overall"]["counts"]
    assert counts["missed"] == len(keys)  # SC-004
    by_field = run(cli, "show", record, "--field", "contract_number")
    assert {c["field"] for c in by_field["cases"]} == {"contract_number"}
    assert len(by_field["cases"]) == 3
    assert run(cli, "show", 999, code=1) == {}


def test_compare_groups(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    d1 = setup[0]
    a, b = two_records(cli, data_dir, d1)
    report = run(cli, "compare", a, b)
    assert report["stage"] == "fields" and report["gold_differs"] is False
    assert {"case_key": f"{d1}/contract_number", "before": "missed", "after": "correct"} in (
        report["better"]
    )
    # «Гамма» equals the gold in the first record, «Дельта» does not in the second
    assert report["worse"] == [{"case_key": f"{d1}/customer_name_short", "before": "correct",
                                "after": "wrong"}]
    assert all(c["before"] != c["after"] for g in ("better", "worse", "outside", "by_gold")
               for c in report[g])
    assert "overall.counts.correct" in report["metrics"]


def test_compare_with_another_gold_version(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    d1 = setup[0]
    first = run(cli, "fields")["record"]
    cell = CellValue(GoldState.VALUE, ("ООО «Альфа»",), ('ООО "Альфа"',), GoldPath.TEMPLATE)
    gold.load(db, ParsedGold(LoadKind.TEMPLATE, frozenset({(d1, "customer_name_short")}),
                             {(d1, "customer_name_short"): cell}, [], []),
              file_name="t", file_bytes=b"t", yes=True)
    second = run(cli, "fields")["record"]
    report = run(cli, "compare", first, second)
    assert report["gold_differs"] is True
    assert report["by_gold"] == [{"case_key": f"{d1}/customer_name_short", "before": "wrong",
                                  "after": "correct"}]
    assert report["better"] == []
    text = cli("eval", "compare", first, second).stdout
    assert "разные версии эталона" in text


def test_compare_of_different_stages_is_refused(cli, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    a = run(cli, "fields")["record"]
    b = run(cli, "fields", "--source", "rules")["record"]
    result = cli("eval", "compare", a, b)
    assert result.exit_code == 1
    assert "этап" in result.stderr


def test_export_round_trips_cyrillic(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    run(cli, "fields", "--label", "подсказка 05.1")
    report = run(cli, "export")
    path = data_dir / report["path"]
    raw = path.read_bytes()
    assert raw.startswith("﻿".encode())
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert rows[0]["label"] == "подсказка 05.1"
    assert {"id", "created_at", "label", "stage", "gold_version", "current_gold"} <= set(rows[0])
    assert report["records"] == 1


def test_outputs_hold_no_values(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    a, b = two_records(cli, data_dir, setup[0])
    secrets = synthetic_secrets(db, extra=["ООО «Гамма»", "ООО «Дельта»"])
    for args in (("results",), ("show", a), ("compare", a, b), ("export",)):
        for extra in ((), ("--json",)):
            result = cli("eval", *args, *extra)
            assert result.exit_code == 0, (args, result.stderr)
            assert_no_values(result.stdout + result.stderr, secrets)
