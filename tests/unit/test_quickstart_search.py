"""Pure helpers of scripts/quickstart_search.py (feature 08, quickstart Б3; task T018).

The script prints numbers and ids only — never the questions or contract text (FR-012).
Written by the main session; the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from docreader.ranking import VariantStats

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_search", ROOT / "scripts" / "quickstart_search.py"
)
assert _spec is not None and _spec.loader is not None
qs = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = qs  # @dataclass looks its module up there
_spec.loader.exec_module(qs)

SECRET = "ВОПРОС-СЕКРЕТ-3318"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "q.toml"
    path.write_text(text, encoding="utf-8")
    return path


# --- reading the set -------------------------------------------------------------------


def test_reads_questions_in_order(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[[question]]\ntext = "один"\nanswer = "D-0002/2.2"\n'
        '[[question]]\ntext = "два"\nanswer = "d-15/2.2.1"\n',
    )
    got = qs.read_questions(path)
    assert [(q.number, q.text, q.answer, q.error) for q in got] == [
        (1, "один", "D-0002/2.2", None),
        (2, "два", "D-0015/2.2.1", None),  # the answer in its standard form
    ]


@pytest.mark.parametrize(
    ("entry", "error"),
    [
        ('answer = "D-0001/1.1"', "нет текста вопроса"),
        ('text = "  "\nanswer = "D-0001/1.1"', "нет текста вопроса"),
        ('text = "вопрос"', "нет ответа"),
        ('text = "вопрос"\nanswer = "1.1"', "неверный идентификатор ответа"),
        ('text = "вопрос"\nanswer = 5', "неверный идентификатор ответа"),
    ],
)
def test_bad_question_is_an_error_in_the_set(tmp_path: Path, entry: str, error: str) -> None:
    path = write(
        tmp_path,
        f'[[question]]\n{entry}\n[[question]]\ntext = "хороший"\nanswer = "D-0001/2.2"\n',
    )
    first, second = qs.read_questions(path)
    assert (first.number, first.error) == (1, error)
    assert (second.number, second.error) == (2, None)


def test_no_file(tmp_path: Path) -> None:
    with pytest.raises(qs.QuestionsFileError, match="нет файла"):
        qs.read_questions(tmp_path / "missing.toml")


def test_not_toml(tmp_path: Path) -> None:
    with pytest.raises(qs.QuestionsFileError, match="не TOML"):
        qs.read_questions(write(tmp_path, "[[question]\ntext ="))


@pytest.mark.parametrize("text", ["", "# пусто\n", "[other]\nx = 1\n", "question = 1\n"])
def test_no_questions(tmp_path: Path, text: str) -> None:
    with pytest.raises(qs.QuestionsFileError, match="нет ни одного вопроса"):
        qs.read_questions(write(tmp_path, text))


def test_error_messages_hold_no_question_text(tmp_path: Path) -> None:
    path = write(tmp_path, f'[[question]]\ntext = "{SECRET}"\nanswer = "плохо"\n')
    (q,) = qs.read_questions(path)
    assert SECRET not in (q.error or "")


# --- places and statistics -------------------------------------------------------------


def test_place_of() -> None:
    hits = ["D-0002/2.3", "D-0002/2.2", "D-0001/1.1"]
    assert qs.place_of(hits, "D-0002/2.2") == 2
    assert qs.place_of(hits, "D-0003/2.2") is None
    assert qs.place_of([], "D-0002/2.2") is None


def test_variant_stats() -> None:
    stats = qs.variant_stats([1, 6, None, 5, 2], [0.5, 0.1, 0.3, 0.2, 0.4])
    assert stats == VariantStats(questions=5, top1=1, top5=3, median_s=0.3, max_s=0.5)


def test_variant_stats_even_count_median() -> None:
    assert qs.variant_stats([1, 2], [1.0, 2.0]).median_s == pytest.approx(1.5)


def test_variant_stats_empty() -> None:
    assert qs.variant_stats([], []) == VariantStats(0, 0, 0, 0.0, 0.0)


# --- the summary -----------------------------------------------------------------------


def _summary():
    rows = [
        qs.Row(1, "D-0015/2.2.1", 1, 1, 0.21, 1.62, None),
        qs.Row(2, "D-0007/4.1", 6, 2, 0.19, 1.48, None),
        qs.Row(3, "D-0031/9.3", None, 4, 0.20, 1.71, None),
        qs.Row(4, None, None, None, None, None, "нет отрывка D-0031/99.1"),
    ]
    return qs.Summary(
        rows=rows,
        code_version="1d241f9",
        embedding_model="bge-m3",
        reranker_model="bge-reranker-v2-m3",
        candidates=30,
        rrf_k=60,
        rerank_candidates=30,
    )


def test_summary_statistics_skip_errors() -> None:
    summary = _summary()
    assert summary.off == VariantStats(3, 1, 1, 0.20, 0.21)
    assert summary.on == VariantStats(3, 1, 3, 1.62, 1.71)
    assert summary.decision == (
        "keep", "в первых пяти 3 против 1, медиана 1,62 с ≤ 10 с"
    )


def test_text_summary() -> None:
    text = "\n".join(qs.render(_summary()))
    assert "Б3. Замер реранкера: 4 вопроса, ошибок в наборе 1" in text
    assert "версия кода: 1d241f9" in text
    assert "модели: поиск bge-m3, реранкер bge-reranker-v2-m3" in text
    assert "настройки: кандидатов 30, rrf_k 60, реранкер читает 30" in text
    assert "ошибка в наборе: нет отрывка D-0031/99.1" in text
    assert "на первом месте      1 из 3 (33%)" in text
    assert "в первых пяти        1 из 3 (33%)" in text
    assert "Решение (FR-014): оставить реранкер включённым — в первых пяти 3 против 1" in text
    lines = {line.split()[0]: line for line in text.splitlines() if line.strip()[:1].isdigit()}
    assert "—" in lines["3"]  # not found without the reranker
    assert "0,21 / 1,62" in lines["1"]


def test_text_summary_disable() -> None:
    summary = _summary()
    summary.rows[2] = qs.Row(3, "D-0031/9.3", 1, None, 0.2, 11.0, None)
    text = "\n".join(qs.render(summary))
    assert "Решение (FR-014): выключить реранкер по умолчанию —" in text


def test_json_summary() -> None:
    data = json.loads(json.dumps(qs.to_json(_summary()), ensure_ascii=False))
    assert data["code_version"] == "1d241f9"
    assert data["models"] == {"embedding": "bge-m3", "reranker": "bge-reranker-v2-m3"}
    assert data["settings"] == {"candidates": 30, "rrf_k": 60, "rerank_candidates": 30}
    assert data["questions"] == 4 and data["errors"] == 1
    assert data["rows"][0] == {
        "number": 1, "answer": "D-0015/2.2.1", "place_off": 1, "place_on": 1,
        "seconds_off": 0.21, "seconds_on": 1.62, "error": None,
    }
    assert data["off"] == {"questions": 3, "top1": 1, "top5": 1, "median_s": 0.2, "max_s": 0.21}
    assert data["decision"] == {
        "verdict": "keep", "reason": "в первых пяти 3 против 1, медиана 1,62 с ≤ 10 с"
    }
