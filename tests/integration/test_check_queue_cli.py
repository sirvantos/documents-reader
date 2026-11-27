"""`check summary` and `check queue` on the synthetic contracts (feature 06, T015).

`check summary --json`: {"checks_version", "documents", "stale", "fields": {field: {status: n}},
"total": {status: n}, "decisions": {"confirm", "correct", "absent"}, "system_changed"}.
`check queue --json`: {"path" (relative to the data dir), "cards", "by_status": {status: n},
"by_field": {field: n}, "system_changed", "stale"}; the folder `checks/queue-<build>/` holds
`cards.json` (contracts/files.md), `index.html` and `img/`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.check_guard import assert_check_output_clean
from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts

STATUSES = ("accepted", "needs_review", "rejected", "not_found")


@pytest.fixture
def checked(cli, use_model, tmp_path: Path) -> dict[str, str]:  # type: ignore[no-untyped-def]
    ids = add_check_contracts(cli, tmp_path / "in")
    for name, doc in ids.items():
        use_model(ScriptedModel(CHECK_ANSWERS[name]))
        assert cli("extract", doc).exit_code == 0
    assert cli("check").exit_code == 0
    return ids


def _json(cli, *args: str) -> dict:  # type: ignore[no-untyped-def]
    result = cli("check", *args, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


# --- summary --------------------------------------------------------------------------------


def test_summary_counts_per_field_and_total(cli, db, checked) -> None:  # type: ignore[no-untyped-def]
    report = _json(cli, "summary")
    assert report["documents"] == 9 and report["stale"] == 0
    assert sum(report["total"].values()) == 54
    assert report["total"]["needs_review"] == 10  # the EXPECTED table of test_check_cli
    assert report["fields"]["amount_with_vat"]["needs_review"] == 4
    assert report["fields"]["contract_end_date"] == {
        "accepted": 8, "needs_review": 1, "rejected": 0, "not_found": 0,
    }
    assert report["decisions"] == {"confirm": 0, "correct": 0, "absent": 0}
    assert report["system_changed"] == 0


def test_summary_counts_stale_documents_and_leaves_their_statuses_out(
    cli, db, checked, use_model
) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(CHECK_ANSWERS["check-words"]))
    assert cli("extract", checked["check-words"]).exit_code == 0
    report = _json(cli, "summary")
    assert report["stale"] == 1 and report["documents"] == 9
    assert sum(report["total"].values()) == 48


def test_summary_text_is_clean(cli, db, checked) -> None:  # type: ignore[no-untyped-def]
    result = cli("check", "summary")
    assert result.exit_code == 0, result.stderr
    assert "Статусы полей (правила 06.1)" in result.stdout
    assert "всего" in result.stdout
    assert_check_output_clean(db, result.stdout + result.stderr)


# --- queue ----------------------------------------------------------------------------------


def _folder(data_dir: Path, report: dict) -> Path:  # type: ignore[type-arg]
    page = data_dir / report["path"]
    assert page.name == "index.html"
    return page.parent


def test_queue_page_and_cards(cli, db, data_dir, checked) -> None:  # type: ignore[no-untyped-def]
    report = _json(cli, "queue")
    folder = _folder(data_dir, report)
    assert folder.parent == data_dir / "checks" and folder.name.startswith("queue-")
    assert report["cards"] == 10 and report["by_status"]["needs_review"] == 10
    cards = json.loads((folder / "cards.json").read_text(encoding="utf-8"))
    assert cards["format"] == "docreader-check-cards/1" and cards["checks_version"] == "06.1"
    keys = [c["key"] for c in cards["cards"]]
    assert len(keys) == 10 and len(set(keys)) == 10
    # required fields first, the end date last (research R-9)
    assert cards["cards"][-1]["field"] == "contract_end_date"
    first = next(c for c in cards["cards"] if c["document_id"] == checked["check-words"])
    assert first["reasons"] == ["amount_words:words_differ"]
    assert first["system"]["result"] == "found" and first["system"]["quote"]
    assert (folder / "img").is_dir()


def test_queue_page_has_no_external_references(cli, data_dir, checked) -> None:  # type: ignore[no-untyped-def]
    html = (_folder(data_dir, _json(cli, "queue")) / "index.html").read_text(encoding="utf-8")
    assert "docreader-check-review/1" in html
    for ref in ("http:", "https:", "@import", "<link", 'src="//', "src='//"):
        assert ref not in html


def test_queue_of_named_documents(cli, data_dir, checked) -> None:  # type: ignore[no-untyped-def]
    report = _json(cli, "queue", checked["check-vat"])
    assert report["cards"] == 2
    assert report["by_field"] == {"amount_without_vat": 1, "amount_with_vat": 1}


def test_queue_names_stale_documents_and_leaves_them_out(
    cli, data_dir, checked, use_model
) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(CHECK_ANSWERS["check-vat"]))
    assert cli("extract", checked["check-vat"]).exit_code == 0
    report = _json(cli, "queue")
    assert report["stale"] == 1 and report["cards"] == 8


def test_queue_out_outside_the_data_dir_is_refused(cli, tmp_path, checked) -> None:  # type: ignore[no-untyped-def]
    result = cli("check", "queue", "--out", tmp_path / "elsewhere")
    assert result.exit_code == 1
    assert not (tmp_path / "elsewhere").exists()


def test_queue_text_is_clean(cli, db, checked) -> None:  # type: ignore[no-untyped-def]
    result = cli("check", "queue")
    assert result.exit_code == 0, result.stderr
    assert "Очередь: checks/queue-" in result.stdout
    assert_check_output_clean(db, result.stdout + result.stderr)
