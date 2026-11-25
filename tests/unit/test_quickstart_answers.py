"""Pure helpers of scripts/quickstart_answers.py (feature 09, quickstart Б4; task T015).

The script prints numbers and ids only — never the questions or contract text (FR-012).
A file or format error stops it (code 1); a question whose contract cannot be asked is
«ошибка в наборе» and is left out of the totals (spec US3 scenarios 4 and 5, analyst's
decision U2). Written by the main session; the implementer must not edit, weaken, skip
or delete these tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_answers", ROOT / "scripts" / "quickstart_answers.py"
)
assert _spec is not None and _spec.loader is not None
qa = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = qa  # @dataclass looks its module up there
_spec.loader.exec_module(qa)

SECRET = "ВОПРОС-СЕКРЕТ-5521"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "q.toml"
    path.write_text(text, encoding="utf-8")
    return path


def entry(text: str = "один", document: str = "D-0001", expected: str = "answer") -> str:
    return f'[[question]]\ntext = "{text}"\ndocument = "{document}"\nexpected = "{expected}"\n'


# --- reading the set -------------------------------------------------------------------


def test_reads_questions_in_order(tmp_path: Path) -> None:
    path = write(tmp_path, entry("один") + entry("два", "d-15", "none"))
    got = qa.read_questions(path)
    assert [(q.number, q.text, q.document, q.expected) for q in got] == [
        (1, "один", "D-0001", "answer"),
        (2, "два", "D-0015", "none"),  # the document id in its standard form
    ]


def test_no_file(tmp_path: Path) -> None:
    with pytest.raises(qa.QuestionsFileError):
        qa.read_questions(tmp_path / "missing.toml")


def test_not_toml(tmp_path: Path) -> None:
    with pytest.raises(qa.QuestionsFileError):
        qa.read_questions(write(tmp_path, "это не toml [[["))


def test_no_question(tmp_path: Path) -> None:
    with pytest.raises(qa.QuestionsFileError):
        qa.read_questions(write(tmp_path, "title = 'x'\n"))


@pytest.mark.parametrize(
    "bad",
    [
        '[[question]]\ndocument = "D-0001"\nexpected = "answer"\n',  # no text
        '[[question]]\ntext = "  "\ndocument = "D-0001"\nexpected = "answer"\n',  # blank
        f'[[question]]\ntext = "{SECRET}"\nexpected = "answer"\n',  # no document
        f'[[question]]\ntext = "{SECRET}"\ndocument = "D-0001"\n',  # no expected
        entry(SECRET, expected="maybe"),
        entry(SECRET, document="договор 1"),
    ],
)
def test_format_error_stops_and_names_the_question_number_only(tmp_path: Path, bad: str) -> None:
    path = write(tmp_path, entry("один") + bad)
    with pytest.raises(qa.QuestionsFileError) as info:
        qa.read_questions(path)
    assert "2" in str(info.value)
    assert SECRET not in str(info.value)


# --- totals and the summary ------------------------------------------------------------


def row(number, expected, outcome, confirmed=0, not_found=0, retried=False, seconds=1.0,
        document="D-0001", error=None):
    return qa.Row(
        number=number, document=document, expected=expected, outcome=outcome,
        confirmed=confirmed, not_found=not_found, retried=retried, seconds=seconds,
        error=error,
    )


ROWS = [
    row(1, "answer", "answered", confirmed=2, seconds=10.0),
    row(2, "answer", "unconfirmed", not_found=2, retried=True, seconds=30.0),
    row(3, "answer", "not_found", seconds=8.0),
    row(4, "none", "not_found", seconds=6.0),
    row(5, "none", "answered", confirmed=1, seconds=12.0),
    row(6, "answer", None, seconds=None, document="D-0099", error="договор не найден"),
]


def summary(rows=ROWS, rechecked=3, missing=0):
    return qa.Summary(
        rows=rows,
        code_version="abc1234",
        llm_model="fake-model",
        prompt_version="09.1",
        embedding_model="fake-embedder",
        reranker_model="fake-reranker",
        passages=8,
        candidates=30,
        rrf_k=60,
        rerank_candidates=30,
        rechecked=rechecked,
        recheck_missing=missing,
    )


def test_totals_by_mark_and_outcome_without_set_errors() -> None:
    totals = qa.totals(ROWS)
    assert totals["answer"] == {"answered": 1, "unconfirmed": 1, "not_found": 1, "failed": 0}
    assert totals["none"] == {"answered": 1, "unconfirmed": 0, "not_found": 1, "failed": 0}


def test_render_header_and_settings() -> None:
    text = "\n".join(qa.render(summary()))
    assert "Б4. Замер ответов: 6 вопросов (с ответом 4, без ответа 2), ошибок в наборе 1" in text
    assert "версия кода: abc1234" in text
    assert (
        "модели: ответ fake-model (подсказка 09.1), поиск fake-embedder, реранкер fake-reranker"
        in text
    )
    assert "настройки: отрывков 8, кандидатов 30, rrf_k 60, реранкер читает 30" in text


def test_render_rows() -> None:
    lines = qa.render(summary())
    first = next(line for line in lines if line.split()[:1] == ["1"])
    assert first.split()[:4] == ["1", "D-0001", "answer", "answered"]
    assert "2 / 0" in first and "нет" in first and "10,0" in first
    second = next(line for line in lines if line.split()[:1] == ["2"])
    assert "0 / 2" in second and "да" in second
    sixth = next(line for line in lines if line.split()[:1] == ["6"])
    assert "ошибка в наборе: договор не найден" in sixth


def test_render_totals_refusals_time_recheck_retries() -> None:
    text = "\n".join(qa.render(summary()))
    assert "отказов на «none»" in text and "1 из 2 (50%)" in text
    assert "время: медиана 10,0 с, наибольшее 30,0 с" in text  # set errors left out
    assert "повторная проверка цитат: проверено 3, не найдено 0" in text
    assert "повторов запроса: 1" in text


def test_render_without_valid_questions() -> None:
    text = "\n".join(qa.render(summary(rows=[ROWS[-1]], rechecked=0)))
    assert "ошибок в наборе 1" in text
    assert "время: медиана —" in text


def test_summary_json_holds_numbers_and_ids_only() -> None:
    data = qa.to_json(summary())
    assert data["questions"] == 6 and data["errors"] == 1
    assert data["totals"]["none"]["not_found"] == 1
    assert data["recheck"] == {"checked": 3, "missing": 0}
    assert data["models"]["llm"] == "fake-model" and data["prompt_version"] == "09.1"
    assert [r["number"] for r in data["rows"]] == [1, 2, 3, 4, 5, 6]
    assert all("text" not in r for r in data["rows"])
    json.dumps(data, ensure_ascii=False)


def test_rows_carry_no_question_text() -> None:
    assert "text" not in qa.Row.__dataclass_fields__
