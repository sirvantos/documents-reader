"""The output guard of `ask-table` (feature 10, T006; every outcome — T023).

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx2
import pytest

from tests.fakes.llm import ScriptedModel
from tests.integration.table_fixtures import add_checked_contracts, reply
from tests.table_guard import assert_table_output_clean, run_clean, table_secrets


class _Result:
    def __init__(self, stdout: str, stderr: str = "") -> None:
        self.exit_code, self.stdout, self.stderr = 0, stdout, stderr


@pytest.fixture
def checked(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return add_checked_contracts(cli, use_model, tmp_path / "in")


def test_help_is_clean(cli, db) -> None:  # type: ignore[no-untyped-def]
    result = run_clean(cli, db, "--help")
    assert result.exit_code == 0
    assert "--include-unreviewed" in result.stdout and "--json" in result.stdout


def test_guard_catches_values_in_the_first_line_and_stderr(db, checked) -> None:  # type: ignore[no-untyped-def]
    secrets = table_secrets(db)
    for leaked in ("1 200 000,00", "К-21/2026", "Альфа", 'ООО "Бета"', "2027-12-31"):
        assert leaked in secrets or any(leaked in s for s in secrets), leaked
        with pytest.raises(AssertionError):
            assert_table_output_clean(db, _Result(f"По таблице — ответ: {leaked}\n"))
        with pytest.raises(AssertionError):
            assert_table_output_clean(db, _Result("По таблице — ответ: 1 договор\n", leaked))
    with pytest.raises(AssertionError):
        assert_table_output_clean(db, _Result("Сколько договоров подряда\n"),
                                  question="Сколько договоров подряда")


def test_guard_lets_values_below_the_first_line_pass(db, checked) -> None:  # type: ignore[no-untyped-def]
    out = "По таблице — ответ: 2 договора; учтено 8 из 9, не учтено 1; повторов 0; 4,2 с\n" \
          "\nУсловие: подрядчик — ООО \"Бета\"\n"
    assert_table_output_clean(db, _Result(out))
    assert_table_output_clean(db, _Result('{"value": "ООО \\"Бета\\""}'), json_output=True)


# --- every outcome, text and --json (T023, FR-013, FR-014) ---------------------------


QUESTION = "Сколько договоров с ООО «Бета» по договору К-21/2026 на 1 200 000?"
MODEL_SECRET = "подписант договора К-21/2026 от ООО «Бета»"
TABLES = ("document", "field_value", "field_status", "field_decision", "run", "gold_field")

ANSWERS = {
    "answered": [reply(action="list", field="contractor_name_short", op="eq",
                       value="ООО «Бета»", other=MODEL_SECRET)],
    "answered_count": [reply(action="count", field="amount_with_vat", op="gt",
                             value="1000000")],
    "zero": [reply(action="list", field="contract_number", op="eq", value="К-99/2099")],
    "refused": [reply(kind="refuse", reason=MODEL_SECRET)],
    "clarify": [reply(kind="clarify", reason=MODEL_SECRET)],
    "unsupported": [reply(kind="unsupported", reason=MODEL_SECRET)],
    "retried": [reply(action="list", field=MODEL_SECRET, op="eq", value="ООО «Бета»"),
                reply(action="list", field="contractor_name_short", op="eq",
                      value="ООО «Бета»")],
    "rejected": [reply(action="list", field=MODEL_SECRET, op="eq", value="ООО «Бета»"),
                 reply(action="list", field="contractor_name_short", op=MODEL_SECRET,
                       value="ООО «Бета»")],
    "failed_form": ["не JSON " + MODEL_SECRET] * 3,
}


def _counts(db) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}


@pytest.mark.parametrize("json_output", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("case", list(ANSWERS))
def test_every_outcome_is_clean_and_writes_nothing(  # type: ignore[no-untyped-def]
    cli, db, use_model, checked, case, json_output
) -> None:
    before = _counts(db)
    use_model(ScriptedModel(*ANSWERS[case]))
    args = (QUESTION, "--json") if json_output else (QUESTION,)
    result = run_clean(cli, db, *args, extra=[MODEL_SECRET])
    assert result.exit_code in (0, 1), result.stderr
    if json_output:
        json.loads(result.stdout)
    assert _counts(db) == before


@pytest.mark.parametrize("json_output", [False, True], ids=["text", "json"])
def test_include_unreviewed_is_clean(cli, db, use_model, checked, json_output) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(reply(action="list", field="amount_with_vat", op="ge", value="0")))
    args = [QUESTION, "--include-unreviewed"] + (["--json"] if json_output else [])
    assert run_clean(cli, db, *args).exit_code == 0


@pytest.mark.parametrize(
    "answers",
    [
        [httpx2.Response(400, json={"error": MODEL_SECRET})],
        [httpx2.ConnectError(MODEL_SECRET)],
        [httpx2.ReadTimeout(MODEL_SECRET)],
    ],
    ids=["http", "drop", "timeout"],
)
@pytest.mark.parametrize("json_output", [False, True], ids=["text", "json"])
def test_model_errors_are_clean(cli, db, use_model, checked, answers, json_output) -> None:  # type: ignore[no-untyped-def]
    before = _counts(db)
    use_model(ScriptedModel(*answers))
    args = (QUESTION, "--json") if json_output else (QUESTION,)
    result = run_clean(cli, db, *args, extra=[MODEL_SECRET])
    assert result.exit_code in (1, 2)
    assert _counts(db) == before


def test_user_errors_are_clean(cli, db, use_model, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from tests.integration.check_fixtures import add_check_contracts

    add_check_contracts(cli, tmp_path / "in")
    use_model(ScriptedModel())
    for args in ((QUESTION,), (QUESTION, "--json"), ("  ",), ("  ", "--json")):
        result = run_clean(cli, db, *args)
        assert result.exit_code == 1, args
