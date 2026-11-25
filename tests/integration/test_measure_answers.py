"""The automated answer measurement end to end (analyst's request 2026-11-25; tasks T027, T028).

`scripts/quickstart_answers.py` on the synthetic contracts with the fakes: questions of the
feature 08 form (`answer = clause id`), the program check of each answer (expected clause,
`contains` values), the three servers checked before the first question, and the default
questions file in the data folder. Written by the main session; the implementer must not
edit, weaken, skip or delete these tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx2
import pytest

from tests.fakes.llm import ScriptedModel
from tests.fakes.reranker import DownReranker, TableReranker
from tests.integration.answer_fixtures import (
    ANSWER_SCORES,
    QUOTE_PARTIES,
    QUOTE_PAYMENT,
    index_answer_contracts,
)

ROOT = Path(__file__).resolve().parents[2]

# Fictional questions on the synthetic contracts of `make_answer_contracts`.
QUESTIONS = """
[[question]]
text = "Какой срок оплаты?"
answer = "D-0001/2.2"
contains = "30 дней"

# the wrong clause on purpose: the answer comes from the preamble
[[question]]
text = "Кто подрядчик?"
answer = "D-0001/2.2"

[[question]]
text = "Предусмотрен ли аванс?"
document = "D-0001"
expected = "none"
"""
TEXTS = ("Какой срок оплаты?", "Кто подрядчик?", "Предусмотрен ли аванс?")


def reply(*claims: dict, kind: str = "answer") -> str:
    return json.dumps({"kind": kind, "claims": list(claims)}, ensure_ascii=False)


def claim(quote: str, clause: str, text: str) -> dict:
    return {"text": text, "clause": clause, "quote": quote}


ANSWERS = (
    reply(claim(QUOTE_PAYMENT, "D-0001/2.2", "Оплата — 30 дней.")),
    reply(claim(QUOTE_PARTIES, "D-0001/преамбула", "Подрядчик — ООО «Бета».")),
    reply(kind="not_found"),
)


def _module():
    spec = importlib.util.spec_from_file_location(
        "quickstart_answers_measure", ROOT / "scripts" / "quickstart_answers.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def indexed(cli, tmp_path, use_embedder, use_reranker) -> None:
    index_answer_contracts(cli, tmp_path, use_embedder)
    use_reranker(TableReranker(ANSWER_SCORES))


@pytest.fixture
def questions(tmp_path) -> Path:
    path = tmp_path / "questions" / "set.toml"
    path.parent.mkdir()
    path.write_text(QUESTIONS, encoding="utf-8")
    return path


def _row(lines: list[str], n: str) -> str:
    return next(line for line in lines if line.split()[:1] == [n])


def test_answers_are_checked_by_the_program(indexed, questions, use_model, capsys) -> None:
    use_model(ScriptedModel(*ANSWERS))
    assert _module().main(["--questions", str(questions)]) == 0
    out = capsys.readouterr().out
    lines = out.splitlines()

    assert "Б4. Замер ответов: 3 вопроса (с ответом 2, без ответа 1), ошибок в наборе 0" in out
    assert _row(lines, "1").split()[:4] == ["1", "D-0001", "answer", "answered"]
    assert _row(lines, "1").rstrip().endswith("верно")
    assert "другой пункт — проверить" in _row(lines, "2")
    assert _row(lines, "3").rstrip().endswith("отказ")
    assert "проверка программой: верно 1 из 2 вопросов с ответом (50%)" in out
    assert "проверить вручную: 2" in out

    (answers_file,) = questions.parent.glob("answers-b4-2*.txt")
    (summary_file,) = questions.parent.glob("answers-b4-summary-*.txt")
    answers_text = answers_file.read_text(encoding="utf-8")
    assert "проверка: верно" in answers_text
    assert "проверка: другой пункт — проверить (ожидался пункт D-0001/2.2)" in answers_text
    assert "проверка: отказ" in answers_text

    summary_text = summary_file.read_text(encoding="utf-8")
    for shown in (out, summary_text):
        for text in (*TEXTS, QUOTE_PAYMENT, QUOTE_PARTIES, "30 дней"):
            assert text not in shown  # questions, contract text and `contains` values


def test_json_summary_has_the_checks(indexed, questions, use_model, capsys) -> None:
    use_model(ScriptedModel(*ANSWERS))
    assert _module().main(["--questions", str(questions), "--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out[: out.index("\nОтветы для оценки")])
    assert [r["check"] for r in data["rows"]] == ["right", "other_clause", "refused"]
    assert data["to_review"] == [2]


def test_servers_are_checked_before_the_first_question(
    indexed, questions, use_model, use_reranker, capsys
) -> None:
    model = use_model(ScriptedModel(models_error=httpx2.ConnectError("refused")))
    use_reranker(DownReranker())
    assert _module().main(["--questions", str(questions)]) == 2
    err = capsys.readouterr().err
    assert "языковая модель: не отвечает" in err
    assert "модель поиска: fake-embedder" in err  # the one that answers is named too
    assert "реранкер: не отвечает" in err
    assert model.requests == []
    assert list(questions.parent.glob("answers-b4-*.txt")) == []


def test_default_questions_file_in_the_data_folder(
    indexed, tmp_path, use_model, monkeypatch, capsys
) -> None:
    data = tmp_path / "data"
    (data / "questions").mkdir(parents=True)
    (data / "questions" / "answers-09.toml").write_text(QUESTIONS, encoding="utf-8")
    monkeypatch.setenv("DOCREADER_DATA_DIR", str(data))
    use_model(ScriptedModel(*ANSWERS))
    assert _module().main([]) == 0
    assert len(list((data / "questions").glob("answers-b4-summary-*.txt"))) == 1


def test_no_questions_file_and_no_data_folder(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DOCREADER_DATA_DIR", raising=False)
    assert _module().main([]) == 1
    assert "--questions" in capsys.readouterr().err
