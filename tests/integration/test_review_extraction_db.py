"""scripts/review_extraction.py on a synthetic database (feature 05, quickstart Б5).

`build_review` makes the local page for the manual check: one card per field, the page
image with the quote lines marked, everything offline. Written by the main session; the
implementer must not edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

from PIL import Image

from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import add_variants, answer, missing_answer

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "review_extraction_db", ROOT / "scripts" / "review_extraction.py"
)
assert _spec is not None and _spec.loader is not None
rv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rv)


def _extracted(cli, tmp_path, use_model) -> tuple[str, str]:
    a, b = add_variants(cli, tmp_path / "in", "base", "missing")
    use_model(ScriptedModel(answer(), missing_answer()))
    assert cli("extract").exit_code == 0
    return a, b


def test_build_review(cli, db, tmp_path, use_model, data_dir) -> None:
    a, b = _extracted(cli, tmp_path, use_model)
    out = tmp_path / "review"
    built = rv.build_review(db, data_dir / "originals", [a, b], out)
    assert built.cards == 12
    html = (out / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"https?://", html)  # offline: no external resource

    cards = rv.load_cards(html)
    assert [(c["document_id"], c["field"]) for c in cards][:2] == [
        (a, "contract_number"), (a, "customer_name_short")
    ]
    by_key = {(c["document_id"], c["field"]): c for c in cards}

    found = by_key[(a, "amount_without_vat")]
    assert found["result"] == "found" and found["choices"][0][0] == "correct"
    assert found["images"], "a found value shows its page"
    image = out / found["images"][0]["file"]
    assert image.is_file()
    with Image.open(image) as im:
        w, h = im.size
    assert found["images"][0]["boxes"], "the quote lines are marked"
    for x0, y0, x1, y1 in found["images"][0]["boxes"]:
        assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
    assert found["pdf"].startswith("file://")
    assert found["pdf"].endswith(f"#page={found['page']}")

    absent = by_key[(b, "amount_with_vat")]
    assert absent["result"] == "not_found"
    assert [c for c, _ in absent["choices"]] == ["correct_absent", "missed"]
    assert absent["images"] == []


def test_answers_of_the_page_make_the_summary(cli, db, tmp_path, use_model, data_dir) -> None:
    a, b = _extracted(cli, tmp_path, use_model)
    out = tmp_path / "review"
    rv.build_review(db, data_dir / "originals", [a, b], out)
    cards = rv.load_cards((out / "index.html").read_text(encoding="utf-8"))

    # what the page downloads: the card keys and the chosen answer, nothing else
    answers = {
        "version": 1,
        "items": [
            {"document_id": c["document_id"], "field": c["field"], "result": c["result"],
             "answer": c["choices"][0][0]}
            for c in cards
        ],
    }
    path = tmp_path / "answers.json"
    path.write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")
    out_text = "\n".join(rv.summarize(json.loads(path.read_text(encoding="utf-8"))))
    assert "договоров: 2, полей: 12, отмечено: 12" in out_text
    assert "SC-002: верных результатов 12 из 12 (100%)" in out_text
    for value in ("Альфа", "Бета", "ДП-17/2026", "1 200 000"):
        assert value not in out_text
