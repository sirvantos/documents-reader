"""The checked synthetic contracts and model replies of the table answer (feature 10, T005).

The nine contracts of `make_check_contracts` (feature 06) go through add, read, parse,
`extract` with their scripted answers (`CHECK_ANSWERS`) and `check`. `EXPECTED_CELLS` is
the table the answer must read from them: per contract and field the cell state of
research R-5, the effective (or unreviewed) value as stored, normalized, and the clause key
of the value. It follows from `CHECK_ANSWERS` and the statuses of `test_check_cli.py`:
a field that needs review with a found value is `unreviewed`, without one `needs_review`.

`reply(**query)` builds the JSON of a `TableReply` for `ScriptedModel`.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.fakes.llm import ScriptedModel
from tests.integration.check_fixtures import CHECK_ANSWERS, add_check_contracts

FIELDS = (
    "contract_number",
    "customer_name_short",
    "contractor_name_short",
    "amount_without_vat",
    "amount_with_vat",
    "contract_end_date",
)

ALPHA = 'ООО "Альфа"'
BETA = 'ООО "Бета"'

Cell = tuple[str, str | None, str | None]  # state, value, clause key


def _row(number: str, **over: Cell) -> dict[str, Cell]:
    base: dict[str, Cell] = {
        "contract_number": ("effective", number, "преамбула"),
        "customer_name_short": ("effective", ALPHA, "преамбула"),
        "contractor_name_short": ("effective", BETA, "преамбула"),
        "amount_without_vat": ("effective", "1000000.00", "2.1"),
        "amount_with_vat": ("effective", "1200000.00", "2.1"),
        "contract_end_date": ("effective", "2027-12-31", "5.1"),
    }
    base.update(over)
    return base


EXPECTED_CELLS: dict[str, dict[str, Cell]] = {
    "check-clean": _row("К-21/2026"),
    "check-words": _row(
        "К-22/2026", amount_without_vat=("unreviewed", "1000000.00", "2.1")),
    "check-vat": _row(
        "К-23/2026",
        amount_without_vat=("unreviewed", "1000000.00", "2.1"),
        amount_with_vat=("unreviewed", "1250000.00", "2.1"),
    ),
    "check-rate10": _row("К-24/2026", amount_with_vat=("effective", "1100000.00", "2.1")),
    "check-exempt": _row(
        "К-25/2026",
        amount_without_vat=("effective", "900000.00", "2.1"),
        amount_with_vat=("needs_review", None, None),
    ),
    "check-zero": _row(
        "К-26/2026",
        amount_without_vat=("unreviewed", "0.00", "2.1"),
        amount_with_vat=("unreviewed", "0.00", "2.1"),
    ),
    "check-date": _row("К-27/2026", contract_end_date=("unreviewed", "2045-12-31", "5.1")),
    "check-same": _row(
        "К-28/2026",
        customer_name_short=("unreviewed", ALPHA, "преамбула"),
        contractor_name_short=("unreviewed", ALPHA, "преамбула"),
    ),
    "check-noamount": _row("К-29/2026", amount_with_vat=("needs_review", None, None)),
}
assert set(EXPECTED_CELLS) == set(CHECK_ANSWERS)


def extract_contract(cli, use_model, doc: str, name: str) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(CHECK_ANSWERS[name]))
    result = cli("extract", doc)
    assert result.exit_code == 0, result.stderr


def run_check(cli, *args: str) -> None:  # type: ignore[no-untyped-def]
    result = cli("check", *args)
    assert result.exit_code == 0, result.stderr


def add_checked_contracts(  # type: ignore[no-untyped-def]
    cli, use_model, folder: Path, *, skip: tuple[str, ...] = ()
) -> dict[str, str]:
    """Adds, reads, parses, extracts and checks the nine contracts; returns name → id.

    The contracts named in `skip` are added and parsed but neither extracted nor checked.
    """
    ids = add_check_contracts(cli, folder)
    for name, doc in ids.items():
        if name not in skip:
            extract_contract(cli, use_model, doc, name)
    run_check(cli)
    return ids


def expected_value(name: str, field: str, *, include_unreviewed: bool = False) -> str | None:
    """The value of the cell the answer counts, or None when it is not counted."""
    state, value, _ = EXPECTED_CELLS[name][field]
    if state == "effective" or (include_unreviewed and state == "unreviewed"):
        return value
    return None


def reply(**query: str | None) -> str:
    """JSON of a `TableReply`: `kind` defaults to `query`, missing keys are null."""
    keys = ("kind", "action", "field", "op", "value", "value_to", "reason", "other")
    unknown = set(query) - set(keys)
    assert not unknown, unknown
    data: dict[str, str | None] = {k: None for k in keys}
    data["kind"] = "query"
    data.update(query)
    return json.dumps(data, ensure_ascii=False)
