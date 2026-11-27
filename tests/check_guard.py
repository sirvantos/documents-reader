"""The output guard of the `check` commands (feature 06, T007, FR-013).

Terminal output of `docreader check …` may be sent to the agent: no system value, no
decision value, no gold value, no quote. The secrets are those of the feature 02 guard plus
the analyst's decisions and every value and quote the synthetic check contracts carry.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

import psycopg

from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.integration.check_fixtures import CHECK_ANSWERS


def contract_secrets() -> set[str]:
    """Values and quotes of every scripted answer of the synthetic check contracts."""
    out: set[str] = set()
    for text in CHECK_ANSWERS.values():
        for name, item in json.loads(text).items():
            if not isinstance(item, dict) or name == "other_party":
                continue
            for key in ("value", "quote"):
                if isinstance(item.get(key), str):
                    out.add(item[key])
    return out


def check_secrets(conn: psycopg.Connection, extra: Iterable[str] = ()) -> set[str]:
    secrets = synthetic_secrets(conn, extra) | contract_secrets()
    for query in (
        "SELECT value_text FROM field_decision WHERE value_text IS NOT NULL",
        "SELECT value_normalized FROM field_decision WHERE value_normalized IS NOT NULL",
        "SELECT system_normalized FROM field_decision WHERE system_normalized IS NOT NULL",
    ):
        secrets.update(row[0] for row in conn.execute(query).fetchall() if row[0])
    return secrets


def assert_check_output_clean(
    conn: psycopg.Connection, output: str, extra: Iterable[str] = ()
) -> None:
    """Fail when the output of a `check` command holds any contract content."""
    assert_no_values(output, check_secrets(conn, extra))
