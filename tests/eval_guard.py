"""The output guard of the `eval` commands (feature 02, T013, FR-026).

Terminal output of `docreader eval …` may be sent to the agent, so it must hold no gold
value, no system or rules value, no question text and no quote. Tests collect those
«secrets» from the synthetic test database and check every command's stdout and stderr.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

import psycopg

from docreader.textnorm import compare_form

# Short strings (years, «да», «RUB», small numbers) would match counts and labels by
# chance; a secret must be long enough to identify contract content.
MIN_SECRET = 5
_ALLOWED = re.compile(r"^(?:D-\d{4,}(?:/\S+)?|Q-[0-9a-f]{10}|[a-z_]+)$")


def _fold(text: str) -> str:
    return compare_form(unicodedata.normalize("NFC", text))[0].casefold()


def _usable(secret: str) -> bool:
    s = secret.strip()
    return len(s) >= MIN_SECRET and not _ALLOWED.match(s)


def assert_no_values(text: str, secrets: Iterable[str]) -> None:
    """Fail when any secret (or its comparison form) appears in `text`."""
    folded = _fold(text)
    leaked = sorted({s for s in secrets if _usable(s) and _fold(s.strip()) in folded})
    assert not leaked, f"output holds contract content: {leaked[:5]}"


def synthetic_secrets(conn: psycopg.Connection, extra: Iterable[str] = ()) -> set[str]:
    """Gold values, blind values, extraction values and quotes, question texts and expected
    values of the test database, plus `extra` (e.g. values found by the rules)."""
    secrets: set[str] = set(extra)
    queries = (
        "SELECT unnest(values_text || values_normalized) FROM gold_field",
        "SELECT unnest(values_text || values_normalized) FROM gold_blind",
        "SELECT value_text FROM field_value WHERE value_text IS NOT NULL",
        "SELECT value_normalized FROM field_value WHERE value_normalized IS NOT NULL",
        "SELECT quote FROM field_value WHERE quote IS NOT NULL",
        "SELECT proposed_value FROM field_value WHERE proposed_value IS NOT NULL",
        "SELECT proposed_quote FROM field_value WHERE proposed_quote IS NOT NULL",
        "SELECT text FROM gold_question",
        "SELECT unnest(expected) FROM gold_question",
    )
    for query in queries:
        secrets.update(row[0] for row in conn.execute(query).fetchall() if row[0])
    return secrets
