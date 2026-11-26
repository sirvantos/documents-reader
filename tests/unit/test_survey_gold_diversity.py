"""The gold diversity survey groups synthetic contracts and prints no values (feature 09)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_gold_diversity.py"
spec = importlib.util.spec_from_file_location("survey_gold_diversity", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey  # @dataclass looks its module up there
spec.loader.exec_module(survey)

FOUND = "found"


def values(number: str | None, contractor: str | None, *, date: bool = True) -> dict:
    v = {f: (FOUND, "x") for f in survey.FIELDS}
    v["contract_number"] = (FOUND, number) if number else ("not_found", None)
    v["contractor_name_short"] = (FOUND, contractor) if contractor else ("not_found", None)
    if not date:
        v["contract_end_date"] = ("not_found", None)
    return v


def test_number_shape_hides_letters_and_digits() -> None:
    assert survey.number_shape("ДП-17/2026") == "А-9/9"
    assert survey.number_shape("08.0352-1369/ОКЭ-ЦУКС/22/4/1") == "9.9-9/А-А/9/9/9"
    assert survey.number_shape("Б1/КТСМ-2025-17") == "А9/А-9-9"
    assert survey.number_shape(None) == survey.NO_VALUE


def test_name_key_ignores_the_written_form_and_case() -> None:
    a = survey.name_key('акционерное общество "Бета"')
    assert a == survey.name_key('АО "бета"')
    assert a != survey.name_key('ООО "Бета"')
    assert "Бета" not in a and len(a) == 12


def test_pages_bucket() -> None:
    assert [survey.pages_bucket(p) for p in (1, 5, 6, 20, 21)] == [
        "1–5", "1–5", "6–10", "11–20", "21+"
    ]


def _docs() -> list:
    same = values("А-9/9", 'АО "Бета"')
    return [
        survey.make_doc("D-0001", same, 8, True),
        survey.make_doc("D-0002", same, 8, False),
        survey.make_doc("D-0003", same, 8, False),
        survey.make_doc("D-0004", values("99-А", 'ООО "Гамма"'), 8, False),
        survey.make_doc("D-0005", values("А-9/9", 'АО "Бета"', date=False), 30, False),
        survey.make_doc("D-0006", values("А-9/9", 'ООО "Гамма"'), 8, False),
    ]


def test_pick_brings_in_new_groups_first() -> None:
    chosen = [d.id for d in survey.pick(_docs(), 3)]
    # D-0005: other results and size (2 new, groups of 1 and 1); D-0004: other number shape
    # and contractor (2 new, groups of 1 and 2): the rarer comes first; then nothing new
    assert chosen[:2] == ["D-0005", "D-0004"]
    assert "D-0001" not in chosen  # already in the gold set
    assert len(chosen) == 3


def test_pick_never_returns_more_than_there_is() -> None:
    assert len(survey.pick(_docs(), 50)) == 5


def test_summary_prints_ids_and_counts_only() -> None:
    text = "\n".join(survey.summary_lines(_docs(), 2))
    assert "D-0001*" in text
    assert "нет в эталоне" in text
    assert "Предлагаю добавить в эталон (2):" in text
    for value in ("Бета", "Гамма", "А-9/9", "99-А"):
        assert value not in text
