"""Extraction on recordings of the real model (level 2, research R-2, R-14; task T026, SC-005).

Every variant of `make_extraction_contracts` goes through `add`, `read`, `parse` and
`extract` with `RecordedModel(variant)`: the answers the real model gave on the same
synthetic contract (`python -m tests.synthetic.record_extraction`, quickstart Б2). The
checks are the result and the normalized value of each field, the quote check of every
`found` row, and the party mark; clause and page are checked only at level 1 (finding U2).

A missing or out-of-date recording fails with `StaleRecording`; it is never skipped. A
variant the real model gets wrong is a finding: never edit the recording or loosen the
test — fix the prompt (`PROMPT_VERSION`) or the variant (`GENERATOR_VERSION`) and
re-record. Written by the main session; the implementer must not edit, weaken, skip or
delete these tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import json

import pytest

from tests.fakes.llm import RecordedModel
from tests.integration.extraction_fixtures import add_variants, field_rows
from tests.integration.test_read import stage
from tests.synthetic import make_pdfs as mk

PARTY_REASON = "состав сторон не соответствует допущению"


def extract_recorded(cli, db, tmp_path, use_model, variant: str) -> str:
    (doc,) = add_variants(cli, tmp_path / "in", variant)
    model = use_model(RecordedModel(variant))
    result = cli("extract", doc, "--json")
    model.assert_fresh()
    assert result.exit_code == 0, result.stderr
    (report,) = json.loads(result.stdout)["documents"]
    assert report["state"] in ("done", "needs_review"), report
    return doc


def values(db, doc: str) -> dict[str, tuple[str, str | None]]:
    return {
        name: (row["result"], row["value_normalized"])
        for name, row in field_rows(db, doc).items()
    }


@pytest.mark.parametrize("variant", mk.EXTRACTION_VARIANTS)
def test_recorded_answers_give_the_truth(cli, db, tmp_path, use_model, variant: str) -> None:
    doc = extract_recorded(cli, db, tmp_path, use_model, variant)
    truth = mk.extraction_truth(variant)
    expected = {
        name: (f["result"], f["value_normalized"])
        for name, f in truth["fields"].items()  # type: ignore[attr-defined]
    }
    assert values(db, doc) == expected

    text = db.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()[0]
    for name, row in field_rows(db, doc).items():
        if row["result"] == "found":
            assert row["quote"] == text[row["quote_start"]:row["quote_end"]], name

    state, reason = stage(db, doc, "extraction")[:2]
    party_found = truth["other_party"]["found"]  # type: ignore[index]
    assert (reason is not None and PARTY_REASON in reason) == party_found, (state, reason)
    if not party_found:
        assert (state, reason) == ("done", None)


def test_injection_gives_the_values_of_base(cli, db, tmp_path, use_model) -> None:
    base = extract_recorded(cli, db, tmp_path / "base", use_model, "base")
    injection = extract_recorded(cli, db, tmp_path / "injection", use_model, "injection")
    assert values(db, injection) == values(db, base)


def test_missing_recording_fails_loudly(tmp_path) -> None:
    from tests.fakes.llm import StaleRecording

    with pytest.raises(StaleRecording, match="перезапишите ответы"):
        RecordedModel("base", recordings_dir=tmp_path)


def test_stale_prompt_version_fails_loudly() -> None:
    from tests.fakes.llm import StaleRecording

    with pytest.raises(StaleRecording, match="prompt_version"):
        RecordedModel("base", prompt_version="00.0")
