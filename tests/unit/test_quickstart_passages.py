"""Pure helpers of scripts/quickstart_passages.py (feature 07, quickstart Б4; task T023).

The script prints counts and shares only — never text, labels, names or file names.
Written by the main session; the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_passages", ROOT / "scripts" / "quickstart_passages.py"
)
assert _spec is not None and _spec.loader is not None
qs = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = qs  # @dataclass looks its module up there
_spec.loader.exec_module(qs)

# text_span rows (start, page): page 1 from 0, page 2 from 100, page 3 from 250
SPANS = [(0, 1), (40, 1), (100, 2), (180, 2), (250, 3)]


# --- SC-002: pages and bounds --------------------------------------------------------------


def test_pages_of_a_passage() -> None:
    assert qs.pages_of(SPANS, 10, 50) == (1, 1)
    assert qs.pages_of(SPANS, 90, 120) == (1, 2)
    assert qs.pages_of(SPANS, 260, 300) == (3, 3)


def test_passage_traceable() -> None:
    # (start, end, first_page, last_page)
    assert qs.traceable((10, 50, 1, 1), SPANS, text_len=400) is True
    assert qs.traceable((90, 120, 1, 1), SPANS, text_len=400) is False  # last page wrong
    assert qs.traceable((90, 120, 1, 2), SPANS, text_len=400) is True
    assert qs.traceable((390, 410, 3, 3), SPANS, text_len=400) is False  # past the text


# --- time ------------------------------------------------------------------------------------


def test_seconds_summary() -> None:
    assert qs.seconds_summary([2.0, 4.0, 9.0]) == {"total": 15.0, "median": 4.0, "max": 9.0}
    assert qs.seconds_summary([]) == {"total": 0.0, "median": None, "max": None}


# --- SC-003: compare two reports -------------------------------------------------------------


def _report(*docs: tuple[str, int, int, int]) -> dict:
    return {"documents": [
        {"document_id": d, "passages": p, "word_entries": w, "vectors": v} for d, p, w, v in docs
    ]}


def test_compare_same_counts() -> None:
    a = _report(("D-0001", 10, 10, 10), ("D-0002", 5, 5, 5))
    assert qs.compare(a, _report(("D-0002", 5, 5, 5), ("D-0001", 10, 10, 10))) == []


def test_compare_lists_changed_and_missing_documents() -> None:
    a = _report(("D-0001", 10, 10, 10), ("D-0002", 5, 5, 5), ("D-0003", 1, 1, 1))
    b = _report(("D-0001", 10, 10, 9), ("D-0002", 5, 5, 5), ("D-0004", 2, 2, 2))
    assert qs.compare(a, b) == ["D-0001", "D-0003", "D-0004"]


# --- render ----------------------------------------------------------------------------------


def _full_report():
    return qs.Report(
        states=Counter({"done": 54, "needs_review": 2}),
        parts=Counter({"preamble": 56, "main": 6917, "tail": 56}),
        word_entries=7029,
        vectors=7029,
        uncovered_chars=0,
        doubled_chars=0,
        coverage_docs=[],
        traceable=7029,
        passages=7029,
        truncated=0,
        seconds={"total": 600.0, "median": 10.5, "max": 30.0},
        changed=None,
    )


def test_render_prints_the_numbers() -> None:
    lines = qs.render(_full_report())
    text = "\n".join(lines)
    assert "Б4. Нарезка и индексы" in lines[0]
    assert "документов: 56; готово 54, требует просмотра 2, ошибка 0" in text
    assert "отрывков: 7029 (преамбула 56, основной текст 6917, реквизиты 56)" in text
    assert "по словам 7029, по смыслу 7029" in text
    assert "SC-001: непокрытых знаков 0, в двух отрывках 0 — выполнен" in text
    assert "SC-002: 7029 из 7029 отрывков прослеживаются до страниц — выполнен" in text
    assert "всего 600.0 с, медиана 10.5 с, наибольшее 30.0 с" in text
    assert "SC-003" not in text  # no --compare


def test_render_failures_and_compare() -> None:
    r = _full_report()
    r = qs.Report(**{**r.__dict__, "uncovered_chars": 12, "coverage_docs": ["D-0007"],
                     "traceable": 7028, "truncated": 3, "changed": ["D-0002"]})
    text = "\n".join(qs.render(r))
    assert "SC-001: непокрытых знаков 12, в двух отрывках 0 — не выполнен (D-0007)" in text
    assert "SC-002: 7028 из 7029 отрывков прослеживаются до страниц — не выполнен" in text
    assert "обрезанных входов модели: 3" in text
    assert "SC-003: числа изменились у D-0002 — не выполнен" in text
    r2 = qs.Report(**{**r.__dict__, "changed": []})
    assert "SC-003: числа отрывков и записей не изменились — выполнен" in "\n".join(qs.render(r2))
