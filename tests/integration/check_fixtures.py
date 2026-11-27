"""Model answers and the add step for the synthetic check contracts (feature 06, T006).

The contracts of `make_check_contracts` are written here from the truth of each variant:
the answers are what the model would give (values as printed, quotes copied from the
generated text, clauses as printed), built with `answer`, `field` and `NOT_FOUND` of
`extraction_fixtures`. The quote check of feature 05 must confirm every found field.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.integration.extraction_fixtures import NOT_FOUND, answer, field
from tests.synthetic import make_pdfs as mk

CUSTOMER = field("ООО «Альфа»", "(ООО «Альфа»), именуемое в дальнейшем «Заказчик»", "преамбула")
CONTRACTOR = field("ООО «Бета»", "(ООО «Бета»), именуемое в дальнейшем «Подрядчик»", "преамбула")
END_2027 = field("31 декабря 2027 г.", "действует до «31» декабря 2027 г.", "5.1")
END_2045 = field("31 декабря 2045 г.", "действует до «31» декабря 2045 г.", "5.1")


def _number(number: str) -> dict:
    return field(f"№ {number}", f"ДОГОВОР ПОДРЯДА № {number}", "преамбула")


def _answer(
    number: str,
    *,
    without: dict,
    with_vat: dict,
    end: dict = END_2027,
    customer: dict = CUSTOMER,
    contractor: dict = CONTRACTOR,
) -> str:
    return answer(
        contract_number=_number(number),
        customer_name_short=customer,
        contractor_name_short=contractor,
        amount_without_vat=without,
        amount_with_vat=with_vat,
        contract_end_date=end,
    )


WITHOUT_1M = field(
    "1 000 000 (один миллион) рублей 00 копеек",
    "Цена Договора составляет 1 000 000 (один миллион) рублей 00 копеек без учёта НДС",
    "2.1",
)
WITH_1_2M = field(
    "1 200 000 (один миллион двести тысяч) рублей 00 копеек",
    "всего с учётом НДС 1 200 000 (один миллион двести тысяч) рублей 00 копеек",
    "2.1",
)

CHECK_ANSWERS: dict[str, str] = {
    "check-clean": _answer("К-21/2026", without=WITHOUT_1M, with_vat=WITH_1_2M),
    "check-words": _answer(
        "К-22/2026",
        without=field(
            "1 000 000 (один миллион сто тысяч) рублей 00 копеек",
            "Цена Договора составляет 1 000 000 (один миллион сто тысяч) рублей 00 копеек "
            "без учёта НДС",
            "2.1",
        ),
        with_vat=WITH_1_2M,
    ),
    "check-vat": _answer(
        "К-23/2026",
        without=WITHOUT_1M,
        with_vat=field(
            "1 250 000 (один миллион двести пятьдесят тысяч) рублей 00 копеек",
            "всего с учётом НДС 1 250 000 (один миллион двести пятьдесят тысяч) рублей 00 копеек",
            "2.1",
        ),
    ),
    "check-rate10": _answer(
        "К-24/2026",
        without=WITHOUT_1M,
        with_vat=field(
            "1 100 000 (один миллион сто тысяч) рублей 00 копеек",
            "всего с учётом НДС 1 100 000 (один миллион сто тысяч) рублей 00 копеек",
            "2.1",
        ),
    ),
    "check-exempt": _answer(
        "К-25/2026",
        without=field(
            "900 000 (девятьсот тысяч) рублей 00 копеек",
            "Цена Договора составляет 900 000 (девятьсот тысяч) рублей 00 копеек",
            "2.1",
        ),
        with_vat=NOT_FOUND,
    ),
    "check-zero": _answer(
        "К-26/2026",
        without=field(
            "0 (ноль) рублей 00 копеек",
            "Цена Договора составляет 0 (ноль) рублей 00 копеек без учёта НДС",
            "2.1",
        ),
        with_vat=field(
            "0 (ноль) рублей 00 копеек",
            "всего с учётом НДС 0 (ноль) рублей 00 копеек",
            "2.1",
        ),
    ),
    "check-date": _answer("К-27/2026", without=WITHOUT_1M, with_vat=WITH_1_2M, end=END_2045),
    "check-same": _answer(
        "К-28/2026",
        without=WITHOUT_1M,
        with_vat=WITH_1_2M,
        customer=CUSTOMER,
        contractor=field(
            "ООО «Альфа»", "(ООО «Альфа»), именуемое в дальнейшем «Подрядчик»", "преамбула"
        ),
    ),
    "check-noamount": _answer("К-29/2026", without=WITHOUT_1M, with_vat=NOT_FOUND),
}


def add_check_contracts(cli, folder: Path) -> dict[str, str]:
    """Writes the check contracts into the folder, adds, reads and parses them.

    Returns the document id of each contract by its file name without the extension.
    """
    mk.make_check_contracts(folder)
    added = cli("add", folder, "--json")
    assert added.exit_code == 0, added.stderr
    report = json.loads(added.stdout)
    assert report["totals"]["added"] == len(CHECK_ANSWERS)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    return {Path(f["path"]).stem: f["document_id"] for f in report["files"]}
