"""The output guard of `docreader ask-table` (feature 10, T006, FR-014).

The first line of the text output of `ask-table` may be sent to the agent, so it holds
no question text and no contract value; neither do error messages and warnings (stderr).
The rest of the output (the condition, the list, the reason of the model) holds values by
design and is not checked. The secrets are those of the `check` guard (values, quotes and
decisions of the synthetic check contracts), the question, the values as `ask-table`
prints them (amounts «1 000 000,00») and the names of the parties without their legal form.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from decimal import Decimal

import psycopg

from tests.check_guard import check_secrets
from tests.eval_guard import assert_no_values
from tests.integration.check_fixtures import CHECK_ANSWERS

_QUOTED = re.compile(r"[«\"]([^»\"]+)[»\"]")


def _printed_amount(normalized: str) -> set[str]:
    value = Decimal(normalized)
    grouped = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return {grouped, grouped.replace(" ", " "), f"{value:.2f}".replace(".", ",")}


def table_secrets(conn: psycopg.Connection, extra: Iterable[str] = ()) -> set[str]:
    """Everything the first line and stderr of `ask-table` must not hold."""
    secrets = check_secrets(conn, extra)
    for normalized in list(secrets):
        if re.fullmatch(r"\d+\.\d{2}", normalized) and Decimal(normalized) >= 1000:
            secrets |= _printed_amount(normalized)
    for text in CHECK_ANSWERS.values():
        for item in json.loads(text).values():
            if isinstance(item, dict) and isinstance(item.get("value"), str):
                secrets.update(_QUOTED.findall(item["value"]))
    return secrets


def assert_table_output_clean(
    conn: psycopg.Connection,
    result,  # type: ignore[no-untyped-def]  # tests.conftest.CliResult
    *,
    question: str | None = None,
    extra: Iterable[str] = (),
    json_output: bool = False,
) -> None:
    """Fail when the first line of stdout (text output) or stderr holds content.

    With `json_output` the whole stdout is data for the analyst; only stderr is checked.
    """
    secrets = table_secrets(conn, [*extra, *([question] if question else [])])
    assert_no_values(result.stderr, secrets)
    if not json_output:
        first = result.stdout.splitlines()[0] if result.stdout.strip() else ""
        assert_no_values(first, secrets)


def run_clean(  # type: ignore[no-untyped-def]
    cli: Callable[..., object], conn: psycopg.Connection, *args: str, extra: Iterable[str] = ()
):
    """Run `docreader ask-table <args>` and apply the guard; returns the CliResult.

    The question is the first argument that is not an option.
    """
    result = cli("ask-table", *args)
    question = next((a for a in args if not a.startswith("--")), None)
    assert_table_output_clean(conn, result, question=question, extra=extra,
                              json_output="--json" in args)
    return result
