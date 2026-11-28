"""scripts/survey_party_forms.py — the shapes of party names, counts only (feature 10, Б4).

Written by the main session. Synthetic names only.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "survey_party_forms", ROOT / "scripts" / "survey_party_forms.py")
assert _spec is not None and _spec.loader is not None
sv = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sv
_spec.loader.exec_module(sv)


def test_shapes() -> None:
    cases = {
        'ООО "Альфа"': "form_quoted",
        'общество с ограниченной ответственностью "Альфа"': "spelled_quoted",
        '"Альфа"': "quoted_no_form",
        "ИП Иванов И.И.": "ip_surname_initials",
        "ИП Иванов И. И.": "ip_surname_initials",
        "ИП Иванов Иван Иванович": "ip_full_name",
        "ИП Иванов": "ip_surname",
        "индивидуальный предприниматель Иванов И.И.": "ip_spelled_initials",
        "Индивидуальный предприниматель Иванов Иван Иванович": "ip_spelled_full_name",
        'ИП "Иванов"': "ip_other",
        "Иванов И.И.": "person_initials",
        "Иванов Иван Иванович": "other",
    }
    for name, shape in cases.items():
        assert sv.shape(name) == shape, name


def test_summary_holds_shapes_and_counts_only() -> None:
    values = {"customer_name_short": ['ООО "Альфа"', 'ООО "Бета"'],
              "contractor_name_short": ["ИП Иванов И.И.", "ИП Петров П. П.", 'АО "Гамма"']}
    lines = sv.summary_lines(values)
    text = "\n".join(lines)
    assert "contractor_name_short: 3" in text
    assert "ip_surname_initials 2" in text and "form_quoted 1" in text
    for secret in ("Иванов", "Петров", "Альфа", "Гамма"):
        assert secret not in text
