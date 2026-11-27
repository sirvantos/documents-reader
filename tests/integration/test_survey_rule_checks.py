"""The rule-checks survey reads an extracted synthetic contract from the database (feature 06)."""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import add_variants, answer

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_rule_checks.py"
spec = importlib.util.spec_from_file_location("survey_rule_checks_db", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey
spec.loader.exec_module(survey)


def test_reads_an_extracted_contract(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "base")
    use_model(ScriptedModel(answer()))
    assert cli("extract", doc).exit_code == 0

    (got,) = survey.load_documents(db)
    result = survey.survey_documents([got], date(2026, 11, 27))
    assert result.documents == 1
    assert result.results["amount_with_vat"]["found"] == 1
    assert result.words["amount_without_vat"]["equal"] == 1
    assert result.words["amount_with_vat"]["equal"] == 1
    assert result.vat["exact"] == 1 and result.ratio["1.20"] == 1
    assert result.names["разные"] == 1
    assert result.end_year["2027"] == 1
    text = "\n".join(survey.summary_lines(result))
    for secret in ("Альфа", "Бета", "1 200 000", "ДП-17"):
        assert secret not in text
