"""`docreader eval load` in the CLI (feature 02, T014; contracts/cli.md «eval load»).

Template (CSV) and review answers (JSON) go through the CLI into the gold set; the output
and `--json` are checked with the output guard (tests/eval_guard.py, FR-026).
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg

from tests.conftest import CliRunner
from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.integration.gold_fixtures import insert_documents

HEADER = "document_id;contract_number;amount_with_vat"
CONTRACT = "ДП-2026-001"
AMOUNT = "1 000 000,00"
WRONG_AMOUNT = "очень много"
REVIEW_AMOUNT_CARD = "1 000 руб."
REVIEW_AMOUNT_RULE = "1 200 руб."


def _write_lines(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("﻿" + "\r\n".join(lines) + "\r\n").encode("utf-8"))
    return path


def _gold_rows(db: psycopg.Connection) -> dict[tuple[str, str], tuple[str, tuple[str, ...]]]:
    return {
        (doc, field): (state, tuple(norm))
        for doc, field, state, norm in db.execute(
            "SELECT document_id, field, state, values_normalized FROM gold_field"
        ).fetchall()
    }


def test_template_counts_error_and_skipped_row(
    db: psycopg.Connection, cli: CliRunner, data_dir: Path
) -> None:
    insert_documents(db, 3)
    path = _write_lines(
        data_dir / "template.csv",
        [
            HEADER,
            f"D-0001;{CONTRACT};{AMOUNT}",
            f"D-0002;ДП-2026-002;{WRONG_AMOUNT}",
            "D-0099;ДП-2026-099;",
        ],
    )

    result = cli("eval", "load", path)

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "Загрузка: шаблон (2 строки, 2 поля)"
    assert "  принято 3: из шаблона 3; пропущено 1" in lines
    assert any(
        line.startswith("  ошибок вида 1: строка 3, столбец amount_with_vat — ") for line in lines
    )
    assert "  пропущены строки: строка 4 — документ D-0099 не найден в реестре" in lines
    assert "  в пределах файла: добавлено 3, изменено 0, убрано 0" in lines
    assert any(line.startswith("  версия эталона: ") for line in lines)
    assert_no_values(
        result.stdout + result.stderr,
        synthetic_secrets(db, extra=[CONTRACT, "ДП-2026-002", "ДП-2026-099", AMOUNT,
                                     WRONG_AMOUNT]),
    )


def test_template_json_keys(db: psycopg.Connection, cli: CliRunner, data_dir: Path) -> None:
    insert_documents(db, 3)
    path = _write_lines(
        data_dir / "template.csv",
        [HEADER, f"D-0001;{CONTRACT};{AMOUNT}", f"D-0002;ДП-2026-002;{WRONG_AMOUNT}",
         "D-0099;ДП-2026-099;"],
    )

    result = cli("eval", "load", path, "--json")

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data) == {
        "kind", "added", "changed", "removed", "same", "other_kind", "paths", "absent",
        "unlabeled", "errors", "skipped_rows", "needs_confirmation", "load_id", "gold_sha256",
        "fields",
    }
    assert data["kind"] == "template"
    assert data["added"] == 3
    assert data["unlabeled"] == 1
    assert data["errors"] == [{"where": "строка 3, столбец amount_with_vat",
                               "reason": data["errors"][0]["reason"]}]
    assert data["skipped_rows"][0]["where"] == "строка 4"
    assert data["needs_confirmation"] is False
    assert data["load_id"] is not None
    assert len(data["gold_sha256"]) == 64
    assert_no_values(
        result.stdout + result.stderr,
        synthetic_secrets(db, extra=[CONTRACT, "ДП-2026-002", "ДП-2026-099", AMOUNT,
                                     WRONG_AMOUNT]),
    )


def test_clearing_a_value_needs_yes(db: psycopg.Connection, cli: CliRunner,
                                    data_dir: Path) -> None:
    insert_documents(db, 1)
    first = _write_lines(data_dir / "first.csv", [HEADER, f"D-0001;{CONTRACT};{AMOUNT}"])
    assert cli("eval", "load", first).exit_code == 0
    before = _gold_rows(db)
    second = _write_lines(data_dir / "second.csv", [HEADER, f"D-0001;{CONTRACT};"])

    refused = cli("eval", "load", second)

    assert refused.exit_code == 1
    assert "  убирается 1 значение: повторите с --yes, чтобы заменить" in (
        refused.stdout.splitlines()
    )
    assert _gold_rows(db) == before
    assert_no_values(
        refused.stdout + refused.stderr,
        synthetic_secrets(db, extra=[CONTRACT, AMOUNT]),
    )

    confirmed = cli("eval", "load", second, "--yes")

    assert confirmed.exit_code == 0, confirmed.stderr
    assert _gold_rows(db) == {("D-0001", "contract_number"): ("value", (CONTRACT,))}


def _write_review_build(data_dir: Path) -> None:
    cards = {
        "format": "docreader-gold-cards/1",
        "build": "b1",
        "cards": [
            {"key": "D-0001/contract_number", "document_id": "D-0001",
             "field": "contract_number", "mark": "agree",
             "model": {"value": CONTRACT, "normalized": CONTRACT, "clause": "преамбула"},
             "rules": [{"value": CONTRACT, "normalized": CONTRACT, "clause": "преамбула"}]},
            {"key": "D-0001/amount_with_vat", "document_id": "D-0001",
             "field": "amount_with_vat", "mark": "disagree",
             "model": {"value": REVIEW_AMOUNT_CARD, "normalized": "1000.00", "clause": "2.1"},
             "rules": [{"value": REVIEW_AMOUNT_RULE, "normalized": "1200.00", "clause": "2.1"}]},
        ],
    }
    path = data_dir / "eval" / "review-b1" / "cards.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")


def _write_answers(data_dir: Path, build: str) -> Path:
    answers = {
        "format": "docreader-gold-review/1",
        "build": build,
        "cards": [{"key": "D-0001/contract_number", "answer": "agree"}],
    }
    path = data_dir / "answers.json"
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    return path


def test_review_answers_load_with_agree(db: psycopg.Connection, cli: CliRunner,
                                        data_dir: Path) -> None:
    insert_documents(db, 1)
    _write_review_build(data_dir)
    path = _write_answers(data_dir, "b1")

    result = cli("eval", "load", path)

    assert result.exit_code == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == "Загрузка: ответы страницы проверки (2 карточки)"
    assert "  принято 1: совпало 1; пропущено 1" in lines
    assert "  в пределах файла: добавлено 1, изменено 0, убрано 0" in lines
    assert _gold_rows(db) == {("D-0001", "contract_number"): ("value", (CONTRACT,))}
    file_name = db.execute("SELECT file_name FROM gold_load").fetchone()
    assert file_name is not None and file_name[0] == "answers.json"
    assert_no_values(
        result.stdout + result.stderr,
        synthetic_secrets(db, extra=[CONTRACT, REVIEW_AMOUNT_CARD, REVIEW_AMOUNT_RULE,
                                     "1000.00", "1200.00"]),
    )


def test_review_answers_unknown_build_is_refused(db: psycopg.Connection, cli: CliRunner,
                                                 data_dir: Path) -> None:
    insert_documents(db, 1)
    _write_review_build(data_dir)
    path = _write_answers(data_dir, "b2")

    result = cli("eval", "load", path)

    assert result.exit_code == 1
    assert "сборка страницы проверки b2 не найдена в eval/ папки данных" in result.stderr
    assert _gold_rows(db) == {}
    assert_no_values(
        result.stdout + result.stderr,
        synthetic_secrets(db, extra=[CONTRACT, REVIEW_AMOUNT_CARD, REVIEW_AMOUNT_RULE]),
    )


def test_other_extension_is_refused(db: psycopg.Connection, cli: CliRunner,
                                    data_dir: Path) -> None:
    path = _write_lines(data_dir / "notes.txt", [HEADER])

    result = cli("eval", "load", path)

    assert result.exit_code == 1
    assert "ожидается файл .csv (шаблон) или .json (ответы страницы проверки)" in result.stderr


def test_template_counts_per_field(db: psycopg.Connection, cli: CliRunner,
                                   data_dir: Path) -> None:
    # converge T044 (FR-005, US1/AC6): counts per field in text, --json and gold_load.counts
    insert_documents(db, 3)
    path = _write_lines(
        data_dir / "template.csv",
        [HEADER, f"D-0001;{CONTRACT};{AMOUNT}", f"D-0002;отсутствует;{WRONG_AMOUNT}",
         "D-0003;ДП-2026-003;"],
    )

    text = cli("eval", "load", path)
    assert text.exit_code == 0, text.stderr
    line = next(ln for ln in text.stdout.splitlines() if ln.startswith("  по полям: "))
    assert "contract_number 3/3" in line and "отсутствует 1" in line
    assert "amount_with_vat 1/3" in line

    result = cli("eval", "load", path, "--json")
    data = json.loads(result.stdout)
    assert data["fields"]["contract_number"] == {
        "covered": 3, "accepted": 3, "absent": 1, "skipped": 0, "paths": {"template": 3},
    }
    assert data["fields"]["amount_with_vat"]["accepted"] == 1
    assert data["fields"]["amount_with_vat"]["skipped"] == 2
    stored = db.execute("SELECT counts FROM gold_load ORDER BY id DESC LIMIT 1").fetchone()
    assert stored is not None and stored[0]["fields"]["contract_number"]["accepted"] == 3
    assert_no_values(
        text.stdout + result.stdout,
        synthetic_secrets(db, extra=[CONTRACT, "ДП-2026-003", AMOUNT, WRONG_AMOUNT]),
    )
