"""`check report` — usefulness of the rules by the feature 02 gold set (feature 06, T019).

`--json`: {"record", "label", "checks_version", "gold_version", "metrics": <outcomes.check_metrics>,
"outside": {"no_gold", "stale"}, "review_file"} (path relative to the data dir).
Gold: four check contracts labelled from a feature 02 template written in the test; the
system value is wrong in two pairs (words ≠ digits: the gold has the amount in words; VAT
mismatch: the gold has the consistent amount).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.check_guard import assert_check_output_clean
from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts

FIELDS = ("contract_number", "customer_name_short", "contractor_name_short",
          "amount_without_vat", "amount_with_vat", "contract_end_date")
LABELLED = ("check-clean", "check-words", "check-vat", "check-rate10")
# the true values where the system is wrong
TRUE = {("check-words", "amount_without_vat"): "1 100 000,00",
        ("check-vat", "amount_with_vat"): "1 200 000,00"}


@pytest.fixture
def setup(cli, db, use_model, data_dir: Path, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    for name, doc in ids.items():
        use_model(ScriptedModel(CHECK_ANSWERS[name]))
        assert cli("extract", doc).exit_code == 0
    assert cli("check").exit_code == 0
    lines = ["document_id;" + ";".join(FIELDS)]
    for name in LABELLED:
        doc = ids[name]
        values = dict(db.execute(
            "SELECT field, value_text FROM field_value WHERE document_id = %s", (doc,)
        ).fetchall())
        # value_text keeps the PDF line breaks: one line per CSV row
        cells = [" ".join(TRUE.get((name, f), values[f]).split()).replace(";", ",")
                 for f in FIELDS]
        lines.append(doc + ";" + ";".join(cells))
    path = data_dir / "gold.csv"
    path.write_bytes(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"))
    loaded = cli("eval", "load", path)
    assert loaded.exit_code == 0, loaded.stderr
    return ids


def _report(cli, *args: str) -> dict:  # type: ignore[no-untyped-def]
    result = cli("check", "report", *args, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_report_numbers(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    report = _report(cli, "--label", "правила 06.1")
    m = report["metrics"]
    assert m["overall"] == {"pairs": 24, "wrong": 2, "wrong_in_queue": 2, "right": 22,
                            "right_in_queue": 1}
    assert m["rules"]["amount_words"] == {"fired": 1, "fired_on_wrong": 1}
    assert m["rules"]["vat_consistent"] == {"fired": 2, "fired_on_wrong": 1}
    assert report["outside"] == {"no_gold": 5, "stale": 0}
    assert report["checks_version"] == "06.1" and len(report["gold_version"]) == 12


def test_record_and_cases_in_the_results_table(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    report = _report(cli, "--label", "правила 06.1")
    stage, label, provenance = db.execute(
        "SELECT stage, label, provenance FROM eval_result WHERE id = %s", (report["record"],)
    ).fetchone()
    assert (stage, label) == ("checks", "правила 06.1")
    assert provenance["checks_version"] == "06.1"
    assert provenance["settings"]["vat_rate"] == 20.0
    assert provenance["extraction_runs"] and provenance["check_runs"]
    outcomes = dict(db.execute(
        "SELECT outcome, count(*) FROM eval_case WHERE result_id = %s GROUP BY outcome",
        (report["record"],),
    ).fetchall())
    assert outcomes == {"queued_wrong": 2, "queued_right": 1, "accepted_right": 21}
    flags = db.execute(
        "SELECT flags FROM eval_case WHERE result_id = %s AND case_key = %s",
        (report["record"], f"{setup['check-vat']}/amount_with_vat"),
    ).fetchone()[0]
    assert flags == ["vat_consistent"]
    review = data_dir / report["review_file"]
    assert review.parent.name == "eval" and review.name.startswith(f"checks-{report['record']}-")


def test_feature_02_commands_work_on_the_record(cli, setup) -> None:  # type: ignore[no-untyped-def]
    first = _report(cli)["record"]
    second = _report(cli)["record"]
    for args in (("show", str(first)), ("compare", str(first), str(second)), ("export",)):
        result = cli("eval", *args)
        assert result.exit_code == 0, (args, result.stderr)


def test_decisions_do_not_change_the_report(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    before = _report(cli)["metrics"]
    db.execute(
        "INSERT INTO field_decision (document_id, field, kind, system_result, system_normalized, "
        "answers_sha256) VALUES (%s, 'amount_with_vat', 'confirm', 'found', '1250000.00', %s)",
        (setup["check-vat"], "c" * 64),
    )
    assert _report(cli)["metrics"] == before  # FR-010: the system value is measured


def test_stale_documents_are_left_out(cli, db, setup, use_model) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(CHECK_ANSWERS["check-clean"]))
    assert cli("extract", setup["check-clean"]).exit_code == 0
    report = _report(cli)
    assert report["outside"]["stale"] == 1
    assert report["metrics"]["overall"]["pairs"] == 18


def test_text_output_is_clean(cli, db, setup) -> None:  # type: ignore[no-untyped-def]
    result = cli("check", "report", "--label", "правила 06.1")
    assert result.exit_code == 0, result.stderr
    assert "Польза правил: запись" in result.stdout
    assert_check_output_clean(db, result.stdout + result.stderr, extra=TRUE.values())


def test_no_gold_is_a_user_error(cli, use_model, tmp_path) -> None:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    use_model(ScriptedModel(CHECK_ANSWERS["check-clean"]))
    assert cli("extract", ids["check-clean"]).exit_code == 0
    assert cli("check").exit_code == 0
    result = cli("check", "report")
    assert result.exit_code == 1
    assert "эталон" in result.stderr
