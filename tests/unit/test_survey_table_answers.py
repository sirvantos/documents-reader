"""The table-answers survey reads synthetic names and numbers, prints counts only (feature 10)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_table_answers.py"
spec = importlib.util.spec_from_file_location("survey_table_answers", SCRIPT)
assert spec is not None and spec.loader is not None
survey = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = survey  # @dataclass looks its module up there
spec.loader.exec_module(survey)

FIELD = "contractor_name_short"


def test_groups_join_spellings_by_the_feature_02_rule() -> None:
    names = [
        'ООО "Альфа"',
        'общество с ограниченной ответственностью "Альфа"',
        'ооо "альфа"',
        'ОАО "Альфа Дельта Строй"',
        'ОАО "АДС"',
        'АО "Бета"',
    ]
    groups = survey.group_names(FIELD, names)
    assert sorted(len(g) for g in groups) == [1, 2, 3]


def test_partial_collisions_same_quoted_name_other_form_and_inside_another() -> None:
    groups = survey.group_names(
        FIELD, ['ООО "Альфа"', 'АО "Альфа"', 'АО "Альфа-Строй"', 'ПАО "Гамма"']
    )
    stats = survey.partial_stats(groups)
    assert stats["same_quoted_other_form"] == 2  # ООО "Альфа", АО "Альфа"
    assert stats["quoted_inside_another"] == 3  # both «Альфа» and «Альфа-Строй»
    assert stats["without_quotes"] == 0


def test_name_without_form_and_quotes_is_counted() -> None:
    stats = survey.partial_stats(survey.group_names(FIELD, ["Иванов И. И.", 'ООО "Альфа"']))
    assert stats["without_quotes"] == 1


def test_sizes_bucket_groups_by_contracts() -> None:
    names = ['ООО "Альфа"'] * 7 + ['АО "Бета"'] * 3 + ['ПАО "Гамма"']
    groups = survey.group_names(FIELD, names)
    assert survey.size_buckets(groups) == {"1": 1, "2–5": 1, "6+": 1}


def test_both_sides_counts_organisations_that_are_customer_and_contractor() -> None:
    customers = survey.group_names("customer_name_short", ['АО "Бета"', 'ООО "Альфа"'])
    contractors = survey.group_names(FIELD, ['акционерное общество "Бета"', 'ПАО "Гамма"'])
    assert survey.on_both_sides(customers, contractors) == 1


def test_forms_count_only_the_legal_form() -> None:
    forms = survey.form_counts(['ООО "Альфа"', 'акционерное общество "Бета"', "Иванов И. И."])
    assert forms == {"ООО": 1, "АО": 1, "без формы": 1}


def test_numbers_repeat() -> None:
    assert survey.number_stats(["1/24", "1/24", "2-П", " 2-П "]) == {
        "values": 4, "distinct": 2, "repeated": 2,
    }


def test_summary_prints_no_names_or_numbers() -> None:
    docs = [
        {"customer_name_short": 'АО "Секретзаказ"', "contractor_name_short": 'ООО "Тайнстрой"',
         "contract_number": "777/СЕКРЕТ"},
        {"customer_name_short": 'акционерное общество "Секретзаказ"',
         "contractor_name_short": 'ООО "Тайнстрой"', "contract_number": "778/СЕКРЕТ"},
    ]
    text = "\n".join(survey.summary_lines(survey.survey_documents(docs)))
    for secret in ("Секретзаказ", "Тайнстрой", "777", "778", "СЕКРЕТ"):
        assert secret not in text
    assert "Договоров с полями: 2" in text
