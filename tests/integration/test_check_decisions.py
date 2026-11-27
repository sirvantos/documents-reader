"""Analyst decisions from the queue page (feature 06, T018; research R-6 rows 1–2, R-8, R-9).

`check load FILE --json`: {"cards", "accepted": {"confirm", "correct", "absent"}, "skipped",
"errors": [{"key", "reason"}], "not_applied", "recomputed"}. A decision keeps the system
value shown on the card (`cards.json` of the build); it never writes field_value or the
feature 02 gold set.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from docreader import checks
from tests.check_guard import assert_check_output_clean
from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts


@pytest.fixture
def docs(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    for name, doc in ids.items():
        use_model(ScriptedModel(CHECK_ANSWERS[name]))
        assert cli("extract", doc).exit_code == 0
    assert cli("check").exit_code == 0
    return ids


def _queue(cli, data_dir: Path) -> tuple[str, Path]:  # type: ignore[no-untyped-def]
    result = cli("check", "queue", "--json")
    assert result.exit_code == 0, result.stderr
    folder = (data_dir / json.loads(result.stdout)["path"]).parent
    build = json.loads((folder / "cards.json").read_text(encoding="utf-8"))["build"]
    return build, folder


def _answers(path: Path, build: str, *items: dict) -> Path:
    path.write_text(json.dumps({"format": "docreader-check-review/1", "build": build,
                                "cards": list(items)}, ensure_ascii=False), encoding="utf-8")
    return path


def _load(cli, path: Path) -> dict:  # type: ignore[no-untyped-def]
    result = cli("check", "load", path, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def _status(db, doc: str, field: str) -> tuple[str, list[str]]:  # type: ignore[no-untyped-def]
    return db.execute(
        "SELECT status, flags FROM field_status WHERE document_id = %s AND field = %s",
        (doc, field),
    ).fetchone()


def test_three_kinds_of_decisions(cli, db, data_dir, docs) -> None:  # type: ignore[no-untyped-def]
    build, _ = _queue(cli, data_dir)
    before = db.execute("SELECT * FROM field_value ORDER BY document_id, field").fetchall()
    path = _answers(
        data_dir / f"check-review-{build}.json", build,
        {"key": f"{docs['check-words']}/amount_without_vat", "answer": "agree"},
        {"key": f"{docs['check-vat']}/amount_with_vat", "answer": "typed",
         "value": "1 200 000,00"},
        {"key": f"{docs['check-date']}/contract_end_date", "answer": "absent"},
        {"key": f"{docs['check-same']}/customer_name_short", "answer": "skip"},
        {"key": f"{docs['check-noamount']}/amount_with_vat", "answer": "agree"},
        {"key": f"{docs['check-zero']}/amount_without_vat", "answer": "typed", "value": "ноль"},
    )
    report = _load(cli, path)
    assert report["accepted"] == {"confirm": 1, "correct": 1, "absent": 1}
    assert report["skipped"] == 1
    assert report["errors"] == [
        {"key": f"{docs['check-noamount']}/amount_with_vat", "reason": "agree_without_value"},
        {"key": f"{docs['check-zero']}/amount_without_vat", "reason": "kind_invalid"},
    ]
    assert _status(db, docs["check-words"], "amount_without_vat") == (
        "accepted", ["human_confirmed"])
    assert _status(db, docs["check-vat"], "amount_with_vat") == ("accepted", ["human_corrected"])
    assert _status(db, docs["check-date"], "contract_end_date") == ("not_found", ["human_absent"])
    row = db.execute(
        "SELECT kind, value_normalized, system_result, system_normalized FROM field_decision "
        "WHERE document_id = %s AND field = 'amount_with_vat'", (docs["check-vat"],),
    ).fetchone()
    assert row == ("correct", "1200000.00", "found", "1250000.00")
    after = db.execute("SELECT * FROM field_value ORDER BY document_id, field").fetchall()
    assert before == after
    assert db.execute("SELECT count(*) FROM gold_field").fetchone()[0] == 0


def test_effective_value(cli, db, data_dir, docs) -> None:  # type: ignore[no-untyped-def]
    build, _ = _queue(cli, data_dir)
    _load(cli, _answers(
        data_dir / "a.json", build,
        {"key": f"{docs['check-vat']}/amount_with_vat", "answer": "typed",
         "value": "1 200 000,00"},
        {"key": f"{docs['check-words']}/amount_without_vat", "answer": "agree"},
    ))
    assert checks.effective_value(db, docs["check-vat"], "amount_with_vat") == "1200000.00"
    assert checks.effective_value(db, docs["check-words"], "amount_without_vat") == "1000000.00"
    assert checks.effective_value(db, docs["check-clean"], "contract_end_date") == "2027-12-31"
    assert checks.effective_value(db, docs["check-zero"], "amount_with_vat") is None  # in queue


def test_decision_survives_a_new_extraction_and_marks_a_changed_value(
    cli, db, data_dir, docs, use_model
) -> None:  # type: ignore[no-untyped-def]
    build, _ = _queue(cli, data_dir)
    key = f"{docs['check-vat']}/amount_with_vat"
    _load(cli, _answers(data_dir / "a.json", build,
                        {"key": key, "answer": "typed", "value": "1 200 000,00"}))
    # the same answer again: the system value is the same, the decision holds
    use_model(ScriptedModel(CHECK_ANSWERS["check-vat"]))
    assert cli("extract", docs["check-vat"]).exit_code == 0
    assert cli("check").exit_code == 0
    assert _status(db, docs["check-vat"], "amount_with_vat") == ("accepted", ["human_corrected"])
    # now the model does not find the amount: the decision stays, the change is flagged
    changed = json.loads(CHECK_ANSWERS["check-vat"])
    changed["amount_with_vat"] = {"found": False, "value": None, "quote": None, "clause": None}
    use_model(ScriptedModel(json.dumps(changed, ensure_ascii=False)))
    assert cli("extract", docs["check-vat"]).exit_code == 0
    assert cli("check").exit_code == 0
    status, flags = _status(db, docs["check-vat"], "amount_with_vat")
    assert status == "needs_review" and "system_changed" in flags
    assert db.execute("SELECT count(*) FROM field_decision").fetchone()[0] == 1  # SC-006
    _, folder = _queue(cli, data_dir)
    cards = json.loads((folder / "cards.json").read_text(encoding="utf-8"))["cards"]
    card = next(c for c in cards if c["key"] == key)
    assert card["decision"]["kind"] == "correct"
    assert "system_changed" in card["flags"]
    summary = json.loads(cli("check", "summary", "--json").stdout)
    assert summary["system_changed"] == 1 and summary["decisions"]["correct"] == 1


def test_a_later_answer_replaces_the_decision(cli, db, data_dir, docs) -> None:  # type: ignore[no-untyped-def]
    build, _ = _queue(cli, data_dir)
    key = f"{docs['check-date']}/contract_end_date"
    _load(cli, _answers(data_dir / "a.json", build, {"key": key, "answer": "agree"}))
    _load(cli, _answers(data_dir / "b.json", build, {"key": key, "answer": "absent"}))
    kinds = db.execute("SELECT kind FROM field_decision").fetchall()
    assert kinds == [("absent",)]


def test_decision_for_a_removed_document_is_not_applied(cli, db, data_dir, docs) -> None:  # type: ignore[no-untyped-def]
    build, _ = _queue(cli, data_dir)
    db.execute("DELETE FROM document WHERE id = %s", (docs["check-date"],))
    report = _load(cli, _answers(
        data_dir / "a.json", build,
        {"key": f"{docs['check-date']}/contract_end_date", "answer": "absent"},
        {"key": f"{docs['check-words']}/amount_without_vat", "answer": "agree"},
    ))
    assert report["not_applied"] == 1
    assert report["accepted"]["confirm"] == 1


def test_unknown_build_is_refused(cli, db, data_dir, docs) -> None:  # type: ignore[no-untyped-def]
    path = _answers(data_dir / "x.json", "nope",
                    {"key": "D-0001/contract_number", "answer": "agree"})
    result = cli("check", "load", path)
    assert result.exit_code == 1
    assert db.execute("SELECT count(*) FROM field_decision").fetchone()[0] == 0


def test_load_output_is_clean(cli, db, data_dir, docs) -> None:  # type: ignore[no-untyped-def]
    build, _ = _queue(cli, data_dir)
    path = _answers(data_dir / "a.json", build,
                    {"key": f"{docs['check-vat']}/amount_with_vat", "answer": "typed",
                     "value": "1 200 000,00"})
    result = cli("check", "load", path)
    assert result.exit_code == 0, result.stderr
    assert "Решения: ответы страницы очереди" in result.stdout
    assert_check_output_clean(db, result.stdout + result.stderr, extra=["1 200 000,00"])
