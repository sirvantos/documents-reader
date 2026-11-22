"""Shared helpers for the integration tests of feature 05 (extraction).

Synthetic contracts of `make_extraction_contract` go through `add`, `read` and `parse`;
the model is a `ScriptedModel` installed with the `use_model` fixture (tests/conftest.py)
and its answers are built here from the truth of the variant (R-14).
"""

from __future__ import annotations

import json
from functools import partial
from pathlib import Path
from typing import Any

from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk

# What the model would write for `base`: value as written, quote, clause as printed.
BASE_ANSWERS: dict[str, tuple[str, str, str]] = {
    "contract_number": ("№ ДП-17/2026", "ДОГОВОР ПОДРЯДА № ДП-17/2026", "преамбула"),
    "customer_name_short": (
        "ООО «Альфа»", "(ООО «Альфа»), именуемое в дальнейшем Заказчик", "преамбула",
    ),
    "contractor_name_short": (
        "ООО «Бета»", "и ООО «Бета», именуемое в дальнейшем Подрядчик", "преамбула",
    ),
    "amount_without_vat": (
        "1 200 000 рублей 00 копеек",
        "Цена договора составляет 1 200 000 (один миллион двести тысяч) рублей 00 копеек "
        "без НДС",
        "2.1",
    ),
    "amount_with_vat": (
        "1 440 000 рублей 00 копеек",
        "всего с НДС 1 440 000 (один миллион четыреста сорок тысяч) рублей 00 копеек",
        "2.1",
    ),
    "contract_end_date": ("25 марта 2027 г.", "Договор действует по 25 марта 2027 г.", "4.1"),
}
NOT_FOUND = {"found": False, "value": None, "quote": None, "clause": None}
NO_PARTY = {"found": False, "quote": None, "clause": None}


def field(value: str, quote: str | None, clause: str | None = None) -> dict[str, Any]:
    return {"found": True, "value": value, "quote": quote, "clause": clause}


def answer(**overrides: Any) -> str:
    """The JSON content of a model answer: `base` answers, with fields replaced."""
    data: dict[str, Any] = {name: field(*parts) for name, parts in BASE_ANSWERS.items()}
    data["other_party"] = NO_PARTY
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def missing_answer() -> str:
    """A right answer for `missing`: no price with VAT, no end date."""
    return answer(
        amount_without_vat=field(
            "1 200 000 рублей", "Цена договора составляет 1 200 000 рублей без НДС", "2.1"
        ),
        amount_with_vat=NOT_FOUND,
        contract_end_date=NOT_FOUND,
    )


def add_variants(cli, folder: Path, *variants: str) -> list[str]:
    """Add the variants (in order), read and parse them; the document ids."""
    makers = [partial(mk.make_extraction_contract, variant=v) for v in variants]
    ids = add_files(cli, folder, makers)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    return ids


def field_rows(db, doc_id: str) -> dict[str, dict[str, Any]]:
    cur = db.execute(
        "SELECT field, result, value_text, value_normalized, quote, quote_start, quote_end,"
        " clause_key, page, pages, reason, proposed_value, proposed_quote, proposed_clause,"
        " source_text_sha256, run_id FROM field_value WHERE document_id = %s ORDER BY field",
        (doc_id,),
    )
    names = [c.name for c in cur.description]
    return {r[0]: dict(zip(names, r, strict=True)) for r in cur.fetchall()}


def text_sha(db, doc_id: str) -> str:
    return db.execute(
        "SELECT text_sha256 FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]
