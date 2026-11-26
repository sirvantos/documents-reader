"""The gold diversity survey reads extracted synthetic contracts from the database (feature 09)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.fakes.llm import ScriptedModel
from tests.integration.extraction_fixtures import add_variants
from tests.integration.test_extract_corrections import wrong_answer

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_gold_diversity.py"
spec = importlib.util.spec_from_file_location("survey_gold_diversity_db", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey
spec.loader.exec_module(survey)


def test_reads_extracted_contracts(cli, db, tmp_path, use_model) -> None:
    (doc,) = add_variants(cli, tmp_path / "in", "full_names")
    use_model(ScriptedModel(wrong_answer()))
    assert cli("extract", doc).exit_code == 0

    (got,) = survey.load_documents(db)
    assert got.id == doc
    assert not got.in_gold
    assert got.number == "А-9/9"  # ДП-17/2026 after the letter code is cut
    assert got.contractor == survey.name_key('АО "Бета"')
    assert got.results.split()[0] == "found"
    text = "\n".join(survey.summary_lines([got], 1))
    assert f"Предлагаю добавить в эталон (1):\n  {doc}" in text
