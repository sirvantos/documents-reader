"""Pure helpers of scripts/make_search_questions.py (feature 08, quickstart Б3; task T026).

The question set comes from the extracted fields of feature 05 without a model; the
script prints counts by field only — never values, quotes or question texts. Written by
the main session.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

import pytest

from docreader.fields import FIELD_NAMES

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_search_questions", ROOT / "scripts" / "make_search_questions.py"
)
assert _spec is not None and _spec.loader is not None
mq = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mq  # @dataclass looks its module up there
_spec.loader.exec_module(mq)


def cand(doc: str, key: str, field: str) -> object:
    return mq.Candidate(document_id=doc, clause_key=key, field=field)


def test_a_template_for_every_prototype_field() -> None:
    assert set(mq.TEMPLATES) == set(FIELD_NAMES)
    assert all(t.endswith("?") and t[0].isupper() for t in mq.TEMPLATES.values())


def _pool() -> list:
    return [
        cand(doc, key, field)
        for doc in ("D-0001", "D-0002", "D-0003", "D-0004")
        for field, key in (
            ("contract_number", "преамбула"),
            ("amount_with_vat", "2.1"),
            ("contract_end_date", "10.1"),
        )
    ]


def test_choice_is_deterministic_and_sized() -> None:
    first = mq.choose(_pool(), 5, seed=0)
    assert len(first) == 5
    assert mq.choose(list(reversed(_pool())), 5, seed=0) == first
    assert len({(c.document_id, c.field) for c in first}) == 5


def test_choice_takes_fields_in_turn() -> None:
    chosen = mq.choose(_pool(), 6, seed=3)
    counts = {f: sum(1 for c in chosen if c.field == f) for f in ("contract_number",
              "amount_with_vat", "contract_end_date")}
    assert sorted(counts.values()) == [2, 2, 2]


def test_choice_spreads_documents_first() -> None:
    chosen = mq.choose(_pool(), 4, seed=1)
    assert len({c.document_id for c in chosen}) == 4


def test_choice_reuses_documents_when_needed() -> None:
    chosen = mq.choose(_pool(), 12, seed=0)
    assert len(chosen) == 12 and len(set(chosen)) == 12


def test_choice_fewer_candidates_than_count() -> None:
    assert len(mq.choose(_pool()[:2], 20, seed=0)) == 2
    assert mq.choose([], 20, seed=0) == []


def test_seed_changes_the_choice() -> None:
    assert mq.choose(_pool(), 4, seed=0) != mq.choose(_pool(), 4, seed=7)


def test_toml_reads_back() -> None:
    chosen = [cand("D-0002", "2.1", "amount_with_vat"), cand("D-0001", "преамбула",
                                                             "contract_number")]
    text = mq.to_toml(chosen)
    data = tomllib.loads(text)
    assert data["question"] == [
        {"text": mq.TEMPLATES["amount_with_vat"], "answer": "D-0002/2.1",
         "source": "field:amount_with_vat"},
        {"text": mq.TEMPLATES["contract_number"], "answer": "D-0001/преамбула",
         "source": "field:contract_number"},
    ]
    # the commented example for the analyst's own questions
    assert 'source = "analyst"' in text
    assert all(line.startswith("#") for line in text.splitlines()
               if 'source = "analyst"' in line)


def test_summary_lines_name_counts_only() -> None:
    chosen = [cand("D-0002", "2.1", "amount_with_vat"), cand("D-0003", "2.1", "amount_with_vat"),
              cand("D-0001", "преамбула", "contract_number")]
    lines = mq.summary_lines(chosen, skipped=4, out=Path("/x/q.toml"))
    text = "\n".join(lines)
    assert "Записано 3 вопроса в /x/q.toml" in text
    assert "amount_with_vat 2" in text and "contract_number 1" in text
    assert "без актуального отрывка: 4" in text


def test_no_overwrite_without_force(tmp_path: Path) -> None:
    out = tmp_path / "q.toml"
    out.write_text("# свои вопросы\n", encoding="utf-8")
    with pytest.raises(mq.OutputExists):
        mq.write_set(out, "новое", force=False)
    assert out.read_text(encoding="utf-8") == "# свои вопросы\n"
    mq.write_set(out, "новое", force=True)
    assert out.read_text(encoding="utf-8") == "новое"


def test_write_creates_the_folder(tmp_path: Path) -> None:
    out = tmp_path / "questions" / "q.toml"
    mq.write_set(out, "x", force=False)
    assert out.read_text(encoding="utf-8") == "x"
