"""`docreader extract` corrects two kinds of model answers (feature 05; feature 09 findings).

The `full_names` synthetic contract reproduces, in abstract form, what the first
measurement on the gold set found (analyst, 2026-11-26): a letter code after the number
in the title, and full names of the parties with their abbreviations in brackets. The
scripted model answers the way the real model did — the number with the code, the full
names for the short ones — and the stored values must still be the truth. Written by the
main session; the implementer must not edit, weaken, skip or delete these tests
(CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import json

from docreader import verify
from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import add_variants, answer, field, field_rows
from tests.synthetic import make_pdfs as mk

PREAMBLE = "преамбула"


def wrong_answer(*, contractor_quote: str) -> str:
    return answer(
        contract_number=field(
            "Nº ДП-17/2026 АБ-ВГД", "ДОГОВОР ПОДРЯДА Nº ДП-17/2026 АБ-ВГД", PREAMBLE
        ),
        customer_name_short=field(
            "Открытое акционерное общество «Альфа Дельта Строй»",
            "Открытое акционерное общество «Альфа Дельта Строй» (ОАО «АДС»), именуемое "
            "в дальнейшем Заказчик",
            PREAMBLE,
        ),
        contractor_name_short=field("Акционерное общество «Бета»", contractor_quote, PREAMBLE),
    )


def test_full_names_variant_is_not_recorded_yet() -> None:
    assert "full_names" in mk.CHECK_VARIANTS
    assert "full_names" not in mk.EXTRACTION_VARIANTS


def test_wrong_answers_are_corrected_to_the_truth(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "full_names")
    use_model(ScriptedModel(wrong_answer(
        contractor_quote="Акционерное общество «Бета» (АО «Бета»), именуемое в дальнейшем "
                         "Подрядчик",
    )))
    result = cli("extract", doc, "--json")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["documents"][0]["state"] == "done"

    rows = field_rows(db, doc)
    truth = mk.extraction_truth("full_names")["fields"]
    for name, expected in truth.items():  # type: ignore[attr-defined]
        row = rows[name]
        got = {k: row[k] for k in ("result", "value_normalized", "clause_key", "page")}
        assert got == expected, name

    def text(name: str) -> str:  # as in the contract; the PDF may wrap a line inside it
        return " ".join(rows[name]["value_text"].split())

    assert text("contract_number") == "ДП-17/2026"
    assert text("customer_name_short") == "ОАО «АДС»"
    assert text("contractor_name_short") == "АО «Бета»"
    assert rows["customer_name_short"]["proposed_value"].startswith("Открытое")


def test_full_name_without_brackets_in_the_quote_is_rejected(
    cli, db, tmp_path, use_model
) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "full_names")
    use_model(ScriptedModel(wrong_answer(
        contractor_quote="Акционерное общество «Бета»",  # the quote stops before the brackets
    )))
    assert cli("extract", doc, "--json").exit_code == 0
    row = field_rows(db, doc)["contractor_name_short"]
    assert (row["result"], row["reason"]) == ("rejected", verify.FULL_NAME)
    assert row["value_normalized"] is None
