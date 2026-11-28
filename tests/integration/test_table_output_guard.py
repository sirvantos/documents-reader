"""The output guard of `ask-table` (feature 10, T006; every outcome — T023).

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.table_fixtures import add_checked_contracts
from tests.table_guard import assert_table_output_clean, run_clean, table_secrets


class _Result:
    def __init__(self, stdout: str, stderr: str = "") -> None:
        self.exit_code, self.stdout, self.stderr = 0, stdout, stderr


@pytest.fixture
def checked(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return add_checked_contracts(cli, use_model, tmp_path / "in")


@pytest.mark.xfail(strict=True, reason="ask-table comes with T013; remove this mark there")
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
