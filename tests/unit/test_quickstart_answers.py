"""Pure helpers of scripts/quickstart_answers.py (feature 09, quickstart Б4; task T015).

The script prints numbers and ids only — never the questions or contract text (FR-012).
A file or format error stops it (code 1); a question whose contract cannot be asked is
«ошибка в наборе» and is left out of the totals (spec US3 scenarios 4 and 5, analyst's
decision U2). Written by the main session; the implementer must not edit, weaken, skip
or delete these tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from docreader.errors import ModelUnavailable

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
        document="D-0001", error=None, check=None):
    return qa.Row(
        number=number, document=document, expected=expected, outcome=outcome,
        confirmed=confirmed, not_found=not_found, retried=retried, seconds=seconds,
        error=error, check=check,
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


# --- the automated measurement (analyst's request 2026-11-25, tasks T027, T028) ------------
#
# 1. A question of the feature 08 set (`answer = "D-0015/5.2"`) is read as is: a question
#    with an answer, asked in the contract of that clause.
# 2. Each answer is checked by the program: a confirmed claim in the expected clause (or its
#    subclause) and every `contains` value in the confirmed claims; the doubtful ones are
#    listed for the analyst by number. The values are never printed (they may be contract
#    data).
# 3. The three servers are checked before the first question, each reported.


def test_reads_a_question_of_the_search_set(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[[question]]\ntext = "один"\nanswer = "d-15/5.2"\nsource = "любая пометка"\n',
    )
    (q,) = qa.read_questions(path)
    assert (q.document, q.expected, q.answer_clause, q.contains) == (
        "D-0015", "answer", "D-0015/5.2", ()
    )


def test_reads_contains_as_a_string_or_a_list(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        entry("один") + 'contains = "30 дней"\n'
        + '[[question]]\ntext = "два"\nanswer = "D-0001/преамбула"\n'
        + 'contains = ["Бета", "Подрядчик"]\n',
    )
    first, second = qa.read_questions(path)
    assert first.answer_clause is None and first.contains == ("30 дней",)
    assert second.contains == ("Бета", "Подрядчик")


def test_old_form_still_reads(tmp_path: Path) -> None:
    (q,) = qa.read_questions(write(tmp_path, entry("один", "D-0002", "none")))
    assert (q.answer_clause, q.contains) == (None, ())


@pytest.mark.parametrize(
    "bad",
    [
        f'[[question]]\ntext = "{SECRET}"\nanswer = "D-0001"\n',  # not a clause id
        f'[[question]]\ntext = "{SECRET}"\nanswer = "D-0001/5.2"\nexpected = "none"\n',
        f'[[question]]\ntext = "{SECRET}"\nanswer = "D-0001/5.2"\ndocument = "D-0002"\n',
        entry(SECRET, expected="none") + 'contains = "30 дней"\n',
        entry(SECRET) + "contains = 30\n",
        entry(SECRET) + 'contains = ["", "x"]\n',
        entry(SECRET) + "contains = []\n",
    ],
)
def test_new_fields_errors_name_the_number_only(tmp_path: Path, bad: str) -> None:
    with pytest.raises(qa.QuestionsFileError) as info:
        qa.read_questions(write(tmp_path, entry("один") + bad))
    assert "2" in str(info.value)
    assert SECRET not in str(info.value)


def test_matching_document_and_answer_are_fine(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '[[question]]\ntext = "один"\nanswer = "D-0001/5.2"\ndocument = "d-1"\n'
        'expected = "answer"\n',
    )
    (q,) = qa.read_questions(path)
    assert q.answer_clause == "D-0001/5.2"


class Claim:
    def __init__(self, clause_id, text="", quote="", confirmed=True):
        self.clause_id, self.text, self.quote, self.confirmed = clause_id, text, quote, confirmed


def question(expected="answer", answer_clause=None, contains=()):
    return qa.Question(1, "вопрос", "D-0001", expected, answer_clause, tuple(contains))


@pytest.mark.parametrize(
    ("q", "claims", "check"),
    [
        # the expected clause, its subclause, a value in the text or in the quote
        (question(answer_clause="D-0001/5.2"), [Claim("D-0001/5.2")], "right"),
        (question(answer_clause="D-0001/5.2"), [Claim("D-0001/5.2.1")], "right"),
        (question(answer_clause="D-0001/5.2"), [Claim("D-0001/5.20")], "other_clause"),
        (question(answer_clause="D-0001/5.2"),
         [Claim("D-0001/1.1"), Claim("D-0001/5.2")], "right"),
        (question(answer_clause="D-0001/5.2"),
         [Claim("D-0001/5.2", confirmed=False), Claim("D-0001/1.1")], "other_clause"),
        (question(answer_clause="D-0001/5.2", contains=["30 дней"]),
         [Claim("D-0001/5.2", text="Срок — 30\nдней.")], "right"),
        (question(answer_clause="D-0001/5.2", contains=["30 дней"]),
         [Claim("D-0001/5.2", quote="в течение 30 ДНЕЙ")], "right"),
        (question(answer_clause="D-0001/5.2", contains=["30 дней", "поставки"]),
         [Claim("D-0001/5.2", text="30 дней")], "no_value"),
        (question(answer_clause="D-0001/5.2", contains=["30 дней"]),
         [Claim("D-0001/1.1", text="30 дней")], "other_clause"),
        # only values, no clause
        (question(contains=["30 дней"]), [Claim("D-0001/1.1", text="30 дней")], "right"),
        (question(contains=["30 дней"]), [Claim("D-0001/1.1", text="10 дней")], "no_value"),
        # nothing to check against
        (question(), [Claim("D-0001/1.1")], "unchecked"),
        # no confirmed claim at all
        (question(answer_clause="D-0001/5.2"), [], "no_answer"),
        (question(answer_clause="D-0001/5.2"),
         [Claim("D-0001/5.2", confirmed=False)], "no_answer"),
        (question(), [], "no_answer"),
        # a question without an answer in the contract
        (question("none"), [], "refused"),
        (question("none"), [Claim("D-0001/5.2", confirmed=False)], "refused"),
        (question("none"), [Claim("D-0001/5.2")], "answered_none"),
    ],
)
def test_judge(q, claims, check) -> None:
    assert qa.judge(q, claims) == check


def test_checks_to_review() -> None:
    assert set(qa.CHECKS) == {
        "right", "other_clause", "no_value", "unchecked", "no_answer", "refused",
        "answered_none",
    }
    assert set(qa.TO_REVIEW) == {"other_clause", "no_value", "unchecked", "answered_none"}


CHECKED_ROWS = [
    dataclasses.replace(ROWS[0], check="right"),
    dataclasses.replace(ROWS[1], check="no_answer"),
    dataclasses.replace(ROWS[2], check="no_answer"),
    dataclasses.replace(ROWS[3], check="refused"),
    dataclasses.replace(ROWS[4], check="answered_none"),
    ROWS[5],  # set error: no check
    row(7, "answer", "answered", confirmed=1, seconds=9.0, check="other_clause"),
    row(8, "answer", "answered", confirmed=1, seconds=9.0, check="unchecked"),
    row(9, "answer", "answered", confirmed=1, seconds=9.0, check="right"),
]


def test_render_check_column_and_line() -> None:
    lines = qa.render(summary(rows=CHECKED_ROWS))
    first = next(line for line in lines if line.split()[:1] == ["1"])
    assert first.rstrip().endswith("верно")
    seventh = next(line for line in lines if line.split()[:1] == ["7"])
    assert "другой пункт — проверить" in seventh
    text = "\n".join(lines)
    # right 2 of the 6 answer-mark questions without a set error
    assert "проверка программой: верно 2 из 6 вопросов с ответом (33%)" in text
    assert "проверить вручную: 5, 7, 8" in text


def test_render_nothing_to_review() -> None:
    text = "\n".join(qa.render(summary(rows=[CHECKED_ROWS[0], CHECKED_ROWS[3]])))
    assert "проверка программой: верно 1 из 1 вопроса с ответом (100%)" in text
    assert "проверить вручную: нет" in text


def test_summary_json_has_checks() -> None:
    data = qa.to_json(summary(rows=CHECKED_ROWS))
    assert data["checks"]["right"] == 2 and data["checks"]["answered_none"] == 1
    assert data["to_review"] == [5, 7, 8]


def test_row_check_defaults_to_none() -> None:
    assert ROWS[0].check is None


class Server:
    def __init__(self, model=None, problem=None):
        self.model, self.problem = model, problem

    def check(self):
        if self.problem:
            raise ModelUnavailable(self.problem)
        return self.model


def test_check_servers_reports_each() -> None:
    states = qa.check_servers(
        [
            ("языковая модель", Server("qwen").check),
            ("модель поиска", Server(problem="нет ответа на 8081").check),
            ("реранкер", Server(problem="нет ответа на 8082").check),
        ]
    )
    assert [(s.name, s.model, s.problem) for s in states] == [
        ("языковая модель", "qwen", None),
        ("модель поиска", None, "нет ответа на 8081"),
        ("реранкер", None, "нет ответа на 8082"),
    ]
    text = "\n".join(qa.render_servers(states))
    assert "языковая модель: qwen" in text
    assert "модель поиска: не отвечает — нет ответа на 8081" in text
    assert "реранкер: не отвечает — нет ответа на 8082" in text


def test_default_questions_path(tmp_path: Path) -> None:
    env = {"DOCREADER_DATA_DIR": str(tmp_path)}
    assert qa.questions_path(None, env) == tmp_path / "questions" / "answers-09.toml"
    assert qa.questions_path("x.toml", env) == Path("x.toml")
    with pytest.raises(qa.QuestionsFileError):
        qa.questions_path(None, {})
