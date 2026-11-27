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


# --- every command, text and --json, after the whole flow (T022) ----------------------------

import json  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from tests.fakes.llm import ScriptedModel  # noqa: E402
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts  # noqa: E402

TYPED = "1 200 000,00"


def _flow(cli, db, use_model, data_dir: Path, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    for name, doc in ids.items():
        use_model(ScriptedModel(CHECK_ANSWERS[name]))
        assert cli("extract", doc).exit_code == 0
    assert cli("check").exit_code == 0
    queue = json.loads(cli("check", "queue", "--json").stdout)
    folder = (data_dir / queue["path"]).parent
    build = json.loads((folder / "cards.json").read_text(encoding="utf-8"))["build"]
    answers = data_dir / f"check-review-{build}.json"
    answers.write_text(json.dumps({
        "format": "docreader-check-review/1", "build": build,
        "cards": [{"key": f"{ids['check-vat']}/amount_with_vat", "answer": "typed",
                   "value": TYPED}],
    }, ensure_ascii=False), encoding="utf-8")
    assert cli("check", "load", answers).exit_code == 0
    lines = ["document_id;contract_number"]
    lines += [f"{ids['check-clean']};К-21/2026"]
    gold = data_dir / "gold.csv"
    gold.write_bytes(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"))
    assert cli("eval", "load", gold).exit_code == 0
    return ids


def test_every_check_command_prints_no_contract_content(
    cli, db, use_model, data_dir, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    ids = _flow(cli, db, use_model, data_dir, tmp_path)
    answers = next(data_dir.glob("check-review-*.json"))
    commands = [
        ("check", "--again"),
        ("check", ids["check-vat"], "--again"),
        ("check", "summary"),
        ("check", "queue"),
        ("check", "queue", ids["check-words"]),
        ("check", "load", str(answers)),
        ("check", "report", "--label", "проверка вывода"),
    ]
    for command in commands:
        for extra in ((), ("--json",)):
            result = cli(*command, *extra)
            assert result.exit_code == 0, (command, extra, result.stderr)
            assert_check_output_clean(db, result.stdout + result.stderr,
                                      extra=[TYPED, "К-21/2026"])


def test_errors_print_no_contract_content(cli, db, use_model, data_dir, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _flow(cli, db, use_model, data_dir, tmp_path)
    bad = data_dir / "bad.json"
    bad.write_text(json.dumps({"format": "docreader-check-review/1", "build": "nope",
                               "cards": []}), encoding="utf-8")
    for command in (("check", "load", str(bad)), ("check", "D-9999"),
                    ("check", "queue", "--out", str(tmp_path / "x"))):
        result = cli(*command)
        assert result.exit_code == 1, command
        assert_check_output_clean(db, result.stdout + result.stderr, extra=[TYPED])


def test_checks_of_a_working_set_size_take_under_a_minute(cli, use_model, tmp_path) -> None:  # type: ignore[no-untyped-def]
    # SC-004: 56 documents; here 9 synthetic documents checked 7 times over = 63 document checks
    ids = add_check_contracts(cli, tmp_path / "in")
    for name, doc in ids.items():
        use_model(ScriptedModel(CHECK_ANSWERS[name]))
        assert cli("extract", doc).exit_code == 0
    started = time.monotonic()
    for _ in range(7):
        assert cli("check", "--all", "--again").exit_code == 0
    assert time.monotonic() - started < 60
