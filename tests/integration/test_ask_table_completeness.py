"""Completeness of a table answer: every contract not counted is named with its reason
(feature 10, T014, SC-006, spec US2; research R-5, R-7, R-8; contracts/cli.md).

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).

The condition field is `amount_with_vat` (`ge 0`: every counted value meets it), and each
contract carries one state of research R-5 in that field:

- check-clean   effective (1 200 000,00)
- check-vat     effective by the analyst's correction to 1 200 000,00 (flag human_corrected)
- check-zero    unreviewed (0,00: rule `amount_positive`)
- check-noamount needs_review (required, no value)
- check-rate10  rejected (extracted again with a quote that is not in the text)
- check-exempt  not_found by the analyst («в договоре нет», flag human_absent)
- check-date    no_extraction (added and parsed, never extracted)
- check-words   checks_stale (extracted, never checked)
- check-same    checks_stale (extracted again after the check)

Text: the block «Не учтено (J): <reason> <n> — <ids>; …» after the list, reasons in the
order of the states above, words of contracts/cli.md; a corrected value is shown with
«(исправлено аналитиком)»; with `--include-unreviewed` the first line holds «включает
непроверенные значения» and the unreviewed contracts are marked «(непроверенное)».
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS
from tests.integration.extraction_fixtures import NOT_FOUND
from tests.integration.table_fixtures import add_checked_contracts, extract_contract, reply
from tests.table_guard import run_clean

QUESTION = "Какие договоры с ценой с НДС от нуля?"
QUERY = reply(action="list", field="amount_with_vat", op="ge", value="0")
REJECTED_WITH_VAT = {"found": True, "value": "1 100 000 (один миллион сто тысяч) рублей",
                     "quote": "цитата, которой в тексте договора нет совсем", "clause": "2.1"}


def _queue(cli, data_dir: Path) -> str:  # type: ignore[no-untyped-def]
    result = cli("check", "queue", "--json")
    assert result.exit_code == 0, result.stderr
    folder = (data_dir / json.loads(result.stdout)["path"]).parent
    return json.loads((folder / "cards.json").read_text(encoding="utf-8"))["build"]


def _load(cli, data_dir: Path, *cards: dict) -> None:  # type: ignore[no-untyped-def]
    build = _queue(cli, data_dir)
    path = data_dir / f"check-review-{build}.json"
    path.write_text(json.dumps({"format": "docreader-check-review/1", "build": build,
                                "cards": list(cards)}, ensure_ascii=False), encoding="utf-8")
    result = cli("check", "load", path, "--json")
    assert result.exit_code == 0, result.stderr


def _answer_with(name: str, **fields: dict) -> str:
    data = json.loads(CHECK_ANSWERS[name])
    data.update(fields)
    return json.dumps(data, ensure_ascii=False)


@pytest.fixture
def states(cli, use_model, db, data_dir, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = add_checked_contracts(cli, use_model, tmp_path / "in",
                                skip=("check-date", "check-words"))
    use_model(ScriptedModel(_answer_with("check-rate10", amount_with_vat=REJECTED_WITH_VAT)))
    assert cli("extract", ids["check-rate10"]).exit_code == 0
    assert cli("check", ids["check-rate10"]).exit_code == 0
    _load(cli, data_dir,
          {"key": f"{ids['check-vat']}/amount_with_vat", "answer": "typed",
           "value": "1 200 000,00"},
          {"key": f"{ids['check-exempt']}/amount_with_vat", "answer": "absent"})
    extract_contract(cli, use_model, ids["check-words"], "check-words")
    extract_contract(cli, use_model, ids["check-same"], "check-same")
    rows = dict(db.execute(
        "SELECT document_id, status FROM field_status WHERE field = 'amount_with_vat'"
    ).fetchall())
    assert rows[ids["check-rate10"]] == "rejected", "the fixture must reject the value"
    return ids


def _json(cli, db, use_model, *extra: str) -> dict:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(QUERY))
    result = run_clean(cli, db, QUESTION, "--json", *extra)
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def _text(cli, db, use_model, *extra: str) -> list[str]:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(QUERY))
    result = run_clean(cli, db, QUESTION, *extra)
    assert result.exit_code == 0, result.stderr
    return result.stdout.splitlines()


def test_every_reason_counted_with_its_ids(cli, db, use_model, states) -> None:  # type: ignore[no-untyped-def]
    res = _json(cli, db, use_model)["result"]
    assert [r["document_id"] for r in res["rows"]] == sorted(
        [states["check-clean"], states["check-vat"]])
    assert res["considered"] == 2 and res["total"] == 9
    assert res["excluded"] == {
        "unreviewed": [states["check-zero"]],
        "needs_review": [states["check-noamount"]],
        "rejected": [states["check-rate10"]],
        "not_found": [states["check-exempt"]],
        "no_extraction": [states["check-date"]],
        "checks_stale": sorted([states["check-words"], states["check-same"]]),
    }


def test_corrected_value_is_used_and_flagged(cli, db, use_model, states) -> None:  # type: ignore[no-untyped-def]
    res = _json(cli, db, use_model)["result"]
    vat = next(r for r in res["rows"] if r["document_id"] == states["check-vat"])
    cell = vat["cells"]["amount_with_vat"]
    assert (cell["state"], cell["value"]) == ("effective", "1200000.00")
    assert "human_corrected" in cell["flags"]
    assert cell["clause_id"] == f"{states['check-vat']}/2.1"
    line = next(x for x in _text(cli, db, use_model) if x.startswith(f"  {states['check-vat']}"))
    assert "с НДС 1 200 000,00 (исправлено аналитиком)" in line


def test_text_names_every_reason(cli, db, use_model, states) -> None:  # type: ignore[no-untyped-def]
    lines = _text(cli, db, use_model)
    assert lines[0].startswith("По таблице — ответ: 2 договора; учтено 2 из 9, не учтено 7; ")
    stale = ", ".join(sorted([states["check-words"], states["check-same"]]))
    expected = (
        "Не учтено (7): "
        f"требует просмотра 1 — {states['check-zero']}; "
        f"требует просмотра, значения нет 1 — {states['check-noamount']}; "
        f"отклонено 1 — {states['check-rate10']}; "
        f"не найдено 1 — {states['check-exempt']}; "
        f"поля не извлечены 1 — {states['check-date']}; "
        f"проверки не выполнены или устарели 2 — {stale}"
    )
    assert expected in lines
    assert lines.index(expected) > max(i for i, x in enumerate(lines) if x.startswith("  D-"))


def test_no_block_when_every_contract_is_counted(cli, db, use_model, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    add_checked_contracts(cli, use_model, tmp_path / "in")
    use_model(ScriptedModel(reply(action="list", field="contract_number", op="eq",
                                  value="К-21/2026")))
    lines = run_clean(cli, db, "Какой договор К-21/2026?").stdout.splitlines()
    assert lines[0].startswith("По таблице — ответ: 1 договор; учтено 9 из 9, не учтено 0; ")
    assert not any(x.startswith("Не учтено") for x in lines)


def test_include_unreviewed(cli, db, use_model, states) -> None:  # type: ignore[no-untyped-def]
    res = _json(cli, db, use_model, "--include-unreviewed")["result"]
    assert res["include_unreviewed"] is True
    got = {r["document_id"]: r["unreviewed"] for r in res["rows"]}
    assert got == {states["check-clean"]: False, states["check-vat"]: False,
                   states["check-zero"]: True}
    assert "unreviewed" not in res["excluded"]
    assert res["excluded"]["rejected"] == [states["check-rate10"]]
    assert res["excluded"]["needs_review"] == [states["check-noamount"]]
    assert res["considered"] == 3

    lines = _text(cli, db, use_model, "--include-unreviewed")
    assert lines[0].startswith("По таблице — ответ: 3 договора, включает непроверенные значения; "
                               "учтено 3 из 9, не учтено 6; ")
    zero = next(x for x in lines if x.startswith(f"  {states['check-zero']}"))
    assert zero.endswith("(непроверенное)")
    assert "с НДС 0,00, требует просмотра" in zero
    clean = next(x for x in lines if x.startswith(f"  {states['check-clean']}"))
    assert "(непроверенное)" not in clean


def test_plain_not_found(cli, db, use_model, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    ids = add_checked_contracts(cli, use_model, tmp_path / "in")
    use_model(ScriptedModel(_answer_with("check-clean", contract_end_date=NOT_FOUND)))
    assert cli("extract", ids["check-clean"]).exit_code == 0
    assert cli("check", ids["check-clean"]).exit_code == 0
    use_model(ScriptedModel(reply(action="count", field="contract_end_date", op="before",
                                  value="2100-01-01")))
    result = run_clean(cli, db, "Сколько договоров заканчивается до 2100 года?", "--json")
    excluded = json.loads(result.stdout)["result"]["excluded"]
    assert excluded["not_found"] == [ids["check-clean"]]
    assert excluded["unreviewed"] == [ids["check-date"]]
