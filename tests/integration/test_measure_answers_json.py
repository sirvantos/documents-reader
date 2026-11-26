"""The machine-readable answers file of the answer measurement (feature 02, T033, R-11)."""

from __future__ import annotations

import json

from tests.fakes.llm import ScriptedModel
from tests.integration.test_measure_answers import ANSWERS, _module, indexed, questions

__all__ = ["indexed", "questions"]  # fixtures


def test_answers_json_next_to_the_text_files(indexed, questions, use_model) -> None:  # type: ignore[no-untyped-def]
    use_model(ScriptedModel(*ANSWERS))
    assert _module().main(["--questions", str(questions)]) == 0
    (path,) = questions.parent.glob("answers-b4-2*.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == "docreader-answers-b4/1"
    first, second, third = data["questions"]
    assert (first["number"], first["document"], first["text"]) == (1, "D-0001",
                                                                   "Какой срок оплаты?")
    assert first["outcome"] == "answered" and first["confirmed_clauses"] == ["D-0001/2.2"]
    assert second["confirmed_clauses"] == ["D-0001/преамбула"]
    assert third["outcome"] == "not_found" and third["confirmed_clauses"] == []
