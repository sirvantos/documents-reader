"""Translating a question into a table query: the model, the check, one retry (feature 10,
T012; outcomes refused/clarify/unsupported — T016). Research R-1, R-9.

Written by the main session: the implementer must not edit, weaken, skip or delete these
tests (CLAUDE.md «Model routing»).

Interface of `docreader.table_answer`:
- `translate(client, question, today) -> Translation` — no database: the model gets
  `table_prompt.build_messages(question, today)`; the reply is checked by
  `table_query.validate`; an invalid query gets one retry
  (`build_retry(messages, reply.model_dump_json(), problem.retry_text())`);
- `Translation(outcome: TableOutcome, parsed: TableQuery | NonQuery | None,
  reason: str | None, retried: bool)`:
  valid query → `answered`, `parsed` the query; `refuse`/`clarify`/`unsupported` →
  `refused`/`clarify`/`unsupported` with the model's reason, `parsed` the NonQuery;
  invalid twice → `rejected`, reason `Problem.text()` of the second;
  form or HTTP error on the first call → `failed`, reason the error's message; on the
  retry → `rejected` with `Problem.text()` of the first;
  no connection or a timeout → `ModelUnavailable` raised (exit 2 in the CLI).
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from datetime import date
from decimal import Decimal

import httpx2
import pytest

from docreader import llm
from docreader import table_answer as ta
from docreader import table_query as tq
from docreader.config import ExtractionSettings
from docreader.errors import EnvironmentProblem
from docreader.table_answer import TableOutcome
from docreader.table_prompt import build_messages
from tests.fakes.llm import ScriptedModel
from tests.integration.table_fixtures import reply

TODAY = date(2026, 11, 28)
QUESTION = "Какие договоры дороже миллиона с НДС?"
GOOD = reply(action="list", field="amount_with_vat", op="gt", value="1000000")
BAD_FIELD = reply(action="list", field="price", op="gt", value="1000000")
BAD_ACTION = reply(action="sum", field="amount_with_vat", op="gt", value="1000000")


def client(*answers: str | Exception | httpx2.Response) -> tuple[llm.ModelClient, ScriptedModel]:
    model = ScriptedModel(*answers)
    settings = dataclasses.replace(ExtractionSettings(), max_retries=0)
    return llm.load_client(settings, model.transport), model


def _assert_sent(sent: list[dict], built: list[dict]) -> None:
    """The messages as built, in order; Instructor (`md_json`) adds its schema text to them."""
    assert [m["role"] for m in sent] == [m["role"] for m in built]
    for got, want in zip(sent, built, strict=True):
        assert want["content"] in got["content"]


def test_translate_needs_no_database() -> None:
    assert list(inspect.signature(ta.translate).parameters) == ["client", "question", "today"]


def test_valid_query_is_answered_with_one_call() -> None:
    c, model = client(GOOD)
    got = ta.translate(c, QUESTION, TODAY)
    assert got.outcome is TableOutcome.ANSWERED and not got.retried and got.reason is None
    assert isinstance(got.parsed, tq.TableQuery)
    assert (got.parsed.field, got.parsed.op, got.parsed.value) == (
        "amount_with_vat", "gt", Decimal("1000000"))
    assert len(model.requests) == 1
    _assert_sent(model.requests[0]["messages"][:2], build_messages(QUESTION, TODAY))


def test_today_goes_into_the_messages() -> None:
    c, model = client(GOOD)
    ta.translate(c, QUESTION, date(2027, 3, 1))
    assert "2027-03-01" in model.requests[0]["messages"][0]["content"]


def test_invalid_then_valid_is_answered_after_one_retry() -> None:
    c, model = client(BAD_FIELD, GOOD)
    got = ta.translate(c, QUESTION, TODAY)
    assert got.outcome is TableOutcome.ANSWERED and got.retried
    assert isinstance(got.parsed, tq.TableQuery)
    assert len(model.requests) == 2
    messages = model.requests[1]["messages"]
    _assert_sent(messages[:2], build_messages(QUESTION, TODAY))
    assert messages[2]["role"] == "assistant"
    assert json.loads(messages[2]["content"])["field"] == "price"
    assert messages[3]["role"] == "user"
    assert messages[3]["content"].startswith("Запрос недопустим: поле не из перечня")
    assert "price" in messages[3]["content"]  # the model's own string, in the retry only


def test_invalid_twice_is_rejected_with_the_second_reason() -> None:
    c, model = client(BAD_FIELD, BAD_ACTION)
    got = ta.translate(c, QUESTION, TODAY)
    assert got.outcome is TableOutcome.REJECTED and got.retried
    assert got.reason == tq.Problem("unknown_action").text()
    assert got.parsed is None
    assert len(model.requests) == 2


@pytest.mark.parametrize(
    "first",
    ["не JSON", httpx2.Response(400, json={"error": "too long"})],
    ids=["form", "http"],
)
def test_error_on_the_first_call_is_failed(first: str | httpx2.Response) -> None:
    c, model = client(first)
    got = ta.translate(c, QUESTION, TODAY)
    assert got.outcome is TableOutcome.FAILED and not got.retried
    assert got.reason and got.parsed is None
    assert len(model.requests) == 1


@pytest.mark.parametrize(
    "second",
    ["не JSON", httpx2.Response(400, json={"error": "too long"})],
    ids=["form", "http"],
)
def test_error_on_the_retry_is_rejected_with_the_first_reason(
    second: str | httpx2.Response,
) -> None:
    c, model = client(BAD_FIELD, second)
    got = ta.translate(c, QUESTION, TODAY)
    assert got.outcome is TableOutcome.REJECTED and got.retried
    assert got.reason == tq.Problem("unknown_field").text()
    assert len(model.requests) == 2


@pytest.mark.parametrize(
    "error", [httpx2.ConnectError("refused"), httpx2.ReadTimeout("slow")], ids=["down", "slow"]
)
def test_no_answer_raises_model_unavailable(error: Exception) -> None:
    c, _ = client(error)
    with pytest.raises(EnvironmentProblem):
        ta.translate(c, QUESTION, TODAY)


def test_no_answer_on_the_retry_raises_too() -> None:
    c, _ = client(BAD_FIELD, httpx2.ReadTimeout("slow"))
    with pytest.raises(EnvironmentProblem):
        ta.translate(c, QUESTION, TODAY)


def test_failed_reason_holds_no_question_text() -> None:
    c, _ = client("не JSON")
    got = ta.translate(c, QUESTION, TODAY)
    assert got.reason and QUESTION not in got.reason and "миллиона" not in got.reason


def test_outcome_values() -> None:
    assert [o.value for o in TableOutcome] == [
        "answered", "refused", "clarify", "unsupported", "rejected", "failed"]
