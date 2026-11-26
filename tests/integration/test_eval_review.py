"""`docreader eval review`: the review page of the gold set (feature 02, T018, research R-9).

Synthetic contracts go through add → read → parse → extract with a `ScriptedModel`
whose answers make cards of every mark; the rules run on the stored text.
"""

from __future__ import annotations

import json
import re
from functools import partial
from pathlib import Path

import pytest

from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import NOT_FOUND, answer, field
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk

PROTOTYPE = (
    "contract_number", "customer_name_short", "contractor_name_short",
    "amount_without_vat", "amount_with_vat", "contract_end_date",
)
NO_PARTY = {"found": False, "quote": None, "clause": None}


def _all_not_found() -> str:
    data = {name: NOT_FOUND for name in PROTOTYPE}
    data["other_party"] = NO_PARTY
    return json.dumps(data, ensure_ascii=False)


def _rules_d(path: Path) -> Path:
    made = mk.make_rules_contracts(path.parent.parent / "rules-src")[3]
    return made.rename(path)


@pytest.fixture
def setup(cli, db, tmp_path: Path, use_model):  # type: ignore[no-untyped-def]
    """D-0001 — `base` extraction contract, D-0002 — `rules-d` (no term, no VAT-free price)."""
    folder = tmp_path / "in"
    makers = [partial(mk.make_extraction_contract, variant="base"), _rules_d]
    ids = add_files(cli, folder, makers)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    model = use_model(ScriptedModel(
        # D-0001: number and names agree with the rules; the price without VAT is the
        # security amount (disagree); the price with VAT is rejected (quote not in the
        # text, the rules find it: rules_only); the end date is not found by the model
        answer(
            amount_without_vat=field(
                "60 000 рублей", "Обеспечение исполнения — 60 000 рублей.", "2.2"
            ),
            amount_with_vat=field("1 440 000 рублей", "этой цитаты нет в договоре", "2.1"),
            contract_end_date=NOT_FOUND,
        ),
        # D-0002: the model finds nothing
        _all_not_found(),
    ))
    assert cli("extract", "--all").exit_code == 0, model.requests
    return ids


def review(cli, *args: object, code: int = 0) -> dict:  # type: ignore[no-untyped-def,type-arg]
    result = cli("eval", "review", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout) if code == 0 else {}


def build_dir(data_dir: Path, report: dict) -> Path:  # type: ignore[type-arg]
    path = data_dir / report["path"]
    assert path.name == "index.html"
    return path.parent


def cards_of(folder: Path) -> dict[str, dict]:  # type: ignore[type-arg]
    data = json.loads((folder / "cards.json").read_text(encoding="utf-8"))
    assert data["format"] == "docreader-gold-cards/1"
    return {c["key"]: c for c in data["cards"]}


def sources(card: dict) -> list[dict]:  # type: ignore[type-arg]
    return ([card["model"]] if card["model"] else []) + card["rules"]


def test_cards_of_every_mark(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    d1, d2 = setup
    report = review(cli)
    folder = build_dir(data_dir, report)
    assert folder.parent == data_dir / "eval"
    assert folder.name.startswith("review-")
    cards = cards_of(folder)
    assert len(cards) == 12
    marks = {k: c["mark"] for k, c in cards.items()}
    assert marks[f"{d1}/contract_number"] == "agree"
    assert marks[f"{d1}/customer_name_short"] == "agree"
    assert marks[f"{d1}/amount_without_vat"] == "disagree"
    assert marks[f"{d1}/amount_with_vat"] == "rules_only"
    assert marks[f"{d1}/contract_end_date"] == "rules_only"
    assert marks[f"{d2}/contract_number"] == "rules_only"
    assert marks[f"{d2}/contract_end_date"] == "none"
    assert marks[f"{d2}/amount_without_vat"] == "none"
    assert report["cards"] == 12
    assert report["marks"]["agree"] == sum(1 for m in marks.values() if m == "agree")
    assert report["carried"] == 0
    assert report["blind_waiting"] == []
    data = json.loads((folder / "cards.json").read_text(encoding="utf-8"))
    assert report["build"] == data["build"]


def test_cards_follow_the_mark_order(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    folder = build_dir(data_dir, review(cli))
    data = json.loads((folder / "cards.json").read_text(encoding="utf-8"))
    order = ["changed", "disagree", "rules_only", "none", "model_only", "agree"]
    ranks = [order.index(c["mark"]) for c in data["cards"]]
    assert ranks == sorted(ranks)


def test_card_shape_for_the_answers_file(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    d1, _ = setup
    folder = build_dir(data_dir, review(cli))
    cards = cards_of(folder)
    disagree = cards[f"{d1}/amount_without_vat"]
    assert disagree["model"]["normalized"] == "60000.00"
    assert disagree["model"]["clause"] == "2.2"
    assert [r["normalized"] for r in disagree["rules"]] == ["1200000.00"]
    rejected = cards[f"{d1}/amount_with_vat"]
    assert rejected["model"] is None
    assert rejected["system"]["result"] == "rejected"
    assert rejected["system"]["reason"]
    for card in cards.values():
        for source in sources(card):
            assert source["quote"] and source["pages"]
            assert (folder / source["image"]).is_file()


def test_places_for_cards_without_a_value(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    d1, d2 = setup
    folder = build_dir(data_dir, review(cli))
    cards = cards_of(folder)
    for key in (f"{d2}/contract_end_date", f"{d2}/amount_without_vat", f"{d1}/amount_with_vat"):
        places = cards[key]["places"]
        assert 1 <= len(places) <= 3, key
        for place in places:
            assert re.fullmatch(r"D-\d{4}/\S+", place["clause_id"])
            assert (folder / place["image"]).is_file()
    assert cards[f"{d1}/contract_number"]["places"] == []


def test_page_is_self_contained(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    folder = build_dir(data_dir, review(cli))
    assert list(folder.glob("*.png"))
    html = (folder / "index.html").read_text(encoding="utf-8")
    for ref in ("http:", "https:", "@import", "<link", 'src="//', "src='//"):
        assert ref not in html, ref
    assert not re.search(r"""(?:src|href)\s*=\s*["'](?!data:|#|[\w./-]+\.png)""", html)
    assert "Скачать ответы" in html
    assert "localStorage" in html
    assert "docreader-gold-review/1" in html


def test_second_build_carries_the_loaded_answers(cli, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    d1, _ = setup
    first = review(cli)
    folder = build_dir(data_dir, first)
    answers = {
        "format": "docreader-gold-review/1",
        "build": first["build"],
        "cards": [
            {"key": f"{d1}/contract_number", "answer": "agree"},
            {"key": f"{d1}/amount_without_vat", "answer": "chosen", "choice": "rules"},
            {"key": f"{d1}/contract_end_date", "answer": "absent"},
        ],
    }
    path = data_dir / "eval" / "answers.json"
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    loaded = cli("eval", "load", path)
    assert loaded.exit_code == 0, loaded.stderr
    second = review(cli)
    assert second["build"] != first["build"]
    assert second["carried"] == 3
    cards = cards_of(build_dir(data_dir, second))
    assert cards[f"{d1}/contract_number"]["carried"] == {"answer": "agree"}
    assert cards[f"{d1}/amount_without_vat"]["carried"] == {"answer": "chosen",
                                                            "choice": "rules:1"}
    assert cards[f"{d1}/contract_end_date"]["carried"] == {"answer": "absent"}
    assert cards[f"{d1}/amount_with_vat"]["carried"] is None
    assert folder.exists()  # the first build stays


def test_blind_waiting_documents_are_hidden_and_named(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    _, d2 = setup
    db.execute("INSERT INTO blind_pick (document_id) VALUES (%s)", (d2,))
    report = review(cli)
    assert report["blind_waiting"] == [d2]
    assert report["cards"] == 6
    assert all(not k.startswith(d2) for k in cards_of(build_dir(data_dir, report)))
    text = cli("eval", "review")
    assert d2 in text.stdout


def test_ids_select_documents(cli, setup) -> None:  # type: ignore[no-untyped-def]
    d1, _ = setup
    assert review(cli, d1)["cards"] == 6


def test_document_without_extraction_is_a_user_error(cli, tmp_path, setup) -> None:  # type: ignore[no-untyped-def]
    ids = add_files(cli, tmp_path / "more", [mk.make_contract_ru])
    result = cli("eval", "review", ids[0])
    assert result.exit_code == 1
    assert ids[0] in result.stderr


def test_output_holds_no_values(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    plain = cli("eval", "review")
    as_json = cli("eval", "review", "--json")
    folder = build_dir(data_dir, json.loads(as_json.stdout))
    shown = [
        s[k] for c in cards_of(folder).values() for s in sources(c) for k in ("value", "quote")
    ]
    secrets = synthetic_secrets(db, extra=shown)
    for result in (plain, as_json):
        assert result.exit_code == 0
        assert_no_values(result.stdout + result.stderr, secrets)
    assert "только поиск по словам" in plain.stdout


def test_out_outside_the_data_dir_is_refused(cli, tmp_path, setup) -> None:  # type: ignore[no-untyped-def]
    result = cli("eval", "review", "--out", tmp_path / "elsewhere")
    assert result.exit_code == 1
    assert not (tmp_path / "elsewhere").exists()


# --- end to end: review → answers → load → gold (T021) --------------------------------------


def _gold_rows(db) -> dict[tuple[str, str], tuple]:  # type: ignore[no-untyped-def,type-arg]
    return {
        (r[0], r[1]): r[2:]
        for r in db.execute(
            "SELECT document_id, field, state, path, values_text, system_normalized, "
            "clause_key FROM gold_field"
        ).fetchall()
    }


def test_review_answers_become_the_gold(cli, db, data_dir, setup) -> None:  # type: ignore[no-untyped-def]
    d1, d2 = setup
    first = review(cli)
    answers = {
        "format": "docreader-gold-review/1",
        "build": first["build"],
        "cards": [
            {"key": f"{d1}/contract_number", "answer": "agree"},
            {"key": f"{d1}/amount_with_vat", "answer": "agree"},  # rules_only → confirmed
            {"key": f"{d1}/amount_without_vat", "answer": "chosen", "choice": "rules",
             "value": "подмена"},  # the value comes from the build, not from here
            {"key": f"{d2}/contract_end_date", "answer": "typed", "value": "30.06.2028",
             "clause": f"{d2}/5.1"},
            {"key": f"{d2}/amount_without_vat", "answer": "typed", "value": "дорого"},
            {"key": f"{d1}/contract_end_date", "answer": "absent"},
            {"key": f"{d2}/contract_number", "answer": "skip"},
        ],
    }
    path = data_dir / "eval" / "a.json"
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    loaded = cli("eval", "load", path)
    assert loaded.exit_code == 0, loaded.stderr
    assert f"карточка {d2}/amount_without_vat" in loaded.stdout
    rows = _gold_rows(db)
    assert rows[(d1, "contract_number")][:2] == ("value", "agree")
    assert rows[(d1, "contract_number")][3] == "ДП-17/2026"
    assert rows[(d1, "amount_with_vat")][:2] == ("value", "confirmed")
    assert rows[(d1, "amount_with_vat")][3] is None  # feature 05 gave no value there
    chosen = rows[(d1, "amount_without_vat")]
    assert chosen[:2] == ("value", "chosen") and "подмена" not in chosen[2]
    assert chosen[3] == "60000.00"  # the model value shown on the card
    assert rows[(d2, "contract_end_date")][:2] == ("value", "typed")
    assert rows[(d2, "contract_end_date")][4] == "5.1"
    assert (d2, "amount_without_vat") not in rows  # wrong kind: unlabeled
    assert rows[(d1, "contract_end_date")][:2] == ("absent", "absent_marked")
    assert (d2, "contract_number") not in rows
    again = cli("eval", "load", path)
    assert again.exit_code == 0
    versions = [r[0] for r in db.execute("SELECT gold_sha256 FROM gold_load ORDER BY id")]
    assert versions[-1] == versions[-2]

    # a rebuild marks nothing as changed while the system shows what the analyst saw
    second = review(cli)
    assert second["marks"]["changed"] == 0
    # a changed feature 05 value makes exactly that card «changed»
    db.execute(
        "UPDATE field_value SET value_normalized = 'ДП-99/2026' "
        "WHERE document_id = %s AND field = 'contract_number'",
        (d1,),
    )
    third = review(cli)
    assert third["marks"]["changed"] == 1
    cards = cards_of(build_dir(data_dir, third))
    assert cards[f"{d1}/contract_number"]["mark"] == "changed"
