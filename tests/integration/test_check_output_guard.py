"""The `check` commands print no contract content (feature 06, T007, T022, FR-013)."""

from __future__ import annotations

from tests.check_guard import assert_check_output_clean, contract_secrets


def test_secrets_cover_the_synthetic_contracts() -> None:
    secrets = contract_secrets()
    assert "ООО «Альфа»" in secrets
    assert any("1 000 000" in s for s in secrets)


def test_check_help_is_clean(cli, db) -> None:  # type: ignore[no-untyped-def]
    result = cli("check", "--help")
    assert result.exit_code == 0
    assert "check" in result.stdout
    assert_check_output_clean(db, result.stdout + result.stderr)
