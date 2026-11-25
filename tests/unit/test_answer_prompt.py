"""The prompt and the answer schemas of the text answer (feature 09, research R-3, R-6; T004).

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from docreader import answer_prompt as ap


def claim(**over) -> dict:
    base = {"text": "Оплата — в течение 30 дней.", "clause": "D-0001/2.2", "quote": "30 дней"}
    base.update(over)
    return base


def passage(n: int, text: str = "Текст пункта.") -> ap.PromptPassage:
    return ap.PromptPassage(clause_id=f"D-0001/{n}.1", label=f"D-0001 · пункт {n}.1", text=text)


# --- AnswerReply ---------------------------------------------------------------


def test_prompt_version() -> None:
    assert ap.PROMPT_VERSION == "09.1"


def test_answer_with_one_claim_accepted() -> None:
    reply = ap.AnswerReply.model_validate({"kind": "answer", "claims": [claim()]})
    assert reply.kind == "answer"
    assert reply.claims[0].clause == "D-0001/2.2"


def test_not_found_without_claims_accepted() -> None:
    reply = ap.AnswerReply.model_validate({"kind": "not_found", "claims": []})
    assert reply.kind == "not_found" and reply.claims == []


def test_answer_without_claims_rejected() -> None:
    with pytest.raises(ValidationError):
        ap.AnswerReply.model_validate({"kind": "answer", "claims": []})


def test_answer_with_eleven_claims_rejected() -> None:
    ap.AnswerReply.model_validate({"kind": "answer", "claims": [claim()] * 10})
    with pytest.raises(ValidationError):
        ap.AnswerReply.model_validate({"kind": "answer", "claims": [claim()] * 11})


@pytest.mark.parametrize("text", ["", "   "])
def test_claim_with_blank_text_rejected(text: str) -> None:
    with pytest.raises(ValidationError):
        ap.AnswerReply.model_validate({"kind": "answer", "claims": [claim(text=text)]})


def test_not_found_with_claims_rejected() -> None:
    with pytest.raises(ValidationError):
        ap.AnswerReply.model_validate({"kind": "not_found", "claims": [claim()]})


def test_unknown_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        ap.AnswerReply.model_validate({"kind": "maybe", "claims": [claim()]})


def test_empty_quote_and_clause_are_not_form_errors() -> None:
    reply = ap.AnswerReply.model_validate(
        {"kind": "answer", "claims": [claim(quote="", clause="")]}
    )
    assert reply.claims[0].quote == "" and reply.claims[0].clause == ""


@pytest.mark.parametrize("key", ["text", "clause", "quote"])
def test_claim_without_a_key_rejected(key: str) -> None:
    bad = claim()
    del bad[key]
    with pytest.raises(ValidationError):
        ap.AnswerReply.model_validate({"kind": "answer", "claims": [bad]})


def test_extra_keys_ignored() -> None:
    reply = ap.AnswerReply.model_validate(
        {"kind": "answer", "claims": [claim(note="x")], "comment": "y"}
    )
    assert len(reply.claims) == 1


# --- RetryReply (analyst's decision U1) ------------------------------------------


def test_retry_reply_accepts_no_claims() -> None:
    assert ap.RetryReply.model_validate({"claims": []}).claims == []


def test_retry_reply_accepts_numbered_claims() -> None:
    reply = ap.RetryReply.model_validate(
        {"claims": [claim(replaces=2), claim(replaces=1)]}
    )
    assert [c.replaces for c in reply.claims] == [2, 1]
    assert reply.claims[0].quote == "30 дней"


@pytest.mark.parametrize("replaces", [0, -1])
def test_retry_number_below_one_rejected(replaces: int) -> None:
    with pytest.raises(ValidationError):
        ap.RetryReply.model_validate({"claims": [claim(replaces=replaces)]})


def test_retry_number_repeated_rejected() -> None:
    with pytest.raises(ValidationError):
        ap.RetryReply.model_validate({"claims": [claim(replaces=1), claim(replaces=1)]})


def test_retry_number_missing_rejected() -> None:
    with pytest.raises(ValidationError):
        ap.RetryReply.model_validate({"claims": [claim()]})


def test_retry_number_above_the_list_is_not_a_form_error() -> None:
    # merge_retry ignores it (T007); the schema does not know the list length
    assert ap.RetryReply.model_validate({"claims": [claim(replaces=9)]}).claims[0].replaces == 9


# --- messages ------------------------------------------------------------------


def test_build_messages_system_then_user() -> None:
    messages = ap.build_messages("Какой срок оплаты?", [passage(2), passage(3)])
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == ap.SYSTEM_PROMPT


def test_user_message_holds_question_and_passages_in_order() -> None:
    user = ap.build_messages(
        "Какой срок оплаты?", [passage(3, "Третий."), passage(2, "Второй.")]
    )[1]["content"]
    assert "Вопрос: Какой срок оплаты?" in user
    lines = user.split("\n")
    assert "<<<ОТРЫВКИ" in lines and "ОТРЫВКИ>>>" in lines
    start, end = lines.index("<<<ОТРЫВКИ"), lines.index("ОТРЫВКИ>>>")
    inside = "\n".join(lines[start + 1 : end])
    first = inside.index("[D-0001/3.1] D-0001 · пункт 3.1\nТретий.")
    second = inside.index("[D-0001/2.1] D-0001 · пункт 2.1\nВторой.")
    assert first < second
    assert user.index("Вопрос:") < user.index("<<<ОТРЫВКИ")


def test_braces_and_placeholders_inserted_unchanged() -> None:
    text = "Сумма {amount} и {question} и {passages} остаются {как есть}."
    user = ap.build_messages("Что значит {x}?", [passage(1, text)])[1]["content"]
    assert text in user
    assert "Вопрос: Что значит {x}?" in user


def test_build_retry_appends_answer_and_numbered_list() -> None:
    messages = ap.build_messages("Вопрос?", [passage(1)])
    first = json.dumps({"kind": "answer", "claims": [claim()]}, ensure_ascii=False)
    retry = ap.build_retry(messages, first, [(1, "Первое утверждение."), (2, "Второе.")])
    assert retry[: len(messages)] == messages
    assert retry[len(messages)] == {"role": "assistant", "content": first}
    assert len(retry) == len(messages) + 2
    last = retry[-1]
    assert last["role"] == "user"
    assert "1. Первое утверждение." in last["content"]
    assert "2. Второе." in last["content"]
    assert "replaces" in last["content"]


def test_build_retry_does_not_repeat_quotes() -> None:
    messages = ap.build_messages("Вопрос?", [passage(1)])
    first = json.dumps(
        {"kind": "answer", "claims": [claim(quote="особая цитата модели")]}, ensure_ascii=False
    )
    last = ap.build_retry(messages, first, [(1, "Утверждение.")])[-1]["content"]
    assert "особая цитата модели" not in last


def test_build_retry_does_not_change_its_input() -> None:
    messages = ap.build_messages("Вопрос?", [passage(1)])
    before = [dict(m) for m in messages]
    ap.build_retry(messages, "{}", [(1, "x")])
    assert messages == before


# --- fingerprint ---------------------------------------------------------------


def test_prompt_sha256_is_hex() -> None:
    digest = ap.prompt_sha256()
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)
    assert digest == ap.prompt_sha256()


@pytest.mark.parametrize("name", ["SYSTEM_PROMPT", "USER_TEMPLATE", "RETRY_TEMPLATE"])
def test_prompt_sha256_changes_with_each_template(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    before = ap.prompt_sha256()
    monkeypatch.setattr(ap, name, getattr(ap, name) + " ")
    assert ap.prompt_sha256() != before


def test_prompt_sha256_changes_with_the_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    before = ap.prompt_sha256()
    real = ap.RetryReply.model_json_schema

    def changed(*args, **kwargs):
        schema = real(*args, **kwargs)
        schema["title"] = "Changed"
        return schema

    monkeypatch.setattr(ap.RetryReply, "model_json_schema", changed)
    assert ap.prompt_sha256() != before


def test_module_imports_no_model_or_database_library() -> None:
    source = Path(ap.__file__).read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"openai", "instructor", "psycopg", "httpx2"}
