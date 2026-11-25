"""Text and `--json` output of `docreader ask` (feature 09, contracts/cli.md).

Synthetic text only; answers are built by hand.
"""

import json

from docreader.answer import Answer, Provenance
from docreader.answer_check import AnswerOutcome, CheckedClaim, ClaimStatus, ShownPassage
from docreader.render import render_answer_json, render_answer_text


def _provenance(reranker_model: str | None = "fake-reranker") -> Provenance:
    return Provenance(
        code_version="abc1234",
        llm_model="fake-llm",
        prompt_version="09.1",
        embedding_model="fake-embedding",
        reranker_model=reranker_model,
        passages=8,
        candidates=30,
        rrf_k=60,
        rerank_candidates=30,
    )


def _shown(
    clause_id: str = "D-0001/2.2",
    *,
    first_page: int = 1,
    last_page: int = 1,
    word_place: int | None = 1,
    vector_place: int | None = 2,
    added_by_rule: bool = False,
) -> ShownPassage:
    return ShownPassage(
        clause_id=clause_id,
        document_id=clause_id.split("/")[0],
        clause_key="key",
        label="Пункт условный",
        start=0,
        end=10,
        first_page=first_page,
        last_page=last_page,
        word_place=word_place,
        vector_place=vector_place,
        fused_place=1,
        added_by_rule=added_by_rule,
    )


def _claim(
    text: str = "Утверждение.",
    *,
    status: ClaimStatus = ClaimStatus.CONFIRMED,
    named_clause: str = "D-0001/2.2",
    clause_id: str | None = "D-0001/2.2",
    quote_text: str | None = "Синтетическая цитата.",
    pages: tuple[int, ...] = (1,),
) -> CheckedClaim:
    return CheckedClaim(
        text=text,
        quote="пересказ",
        named_clause=named_clause,
        status=status,
        clause_id=clause_id,
        quote_text=quote_text,
        pages=pages,
    )


def _answer(
    outcome: AnswerOutcome = AnswerOutcome.ANSWERED,
    *,
    claims: list[CheckedClaim] | None = None,
    shown: list[ShownPassage] | None = None,
    document_id: str | None = "D-0001",
    retried: bool = False,
    not_found_first: int = 0,
    not_found_final: int = 0,
    failure: str | None = None,
    warnings: list[str] | None = None,
    seconds: float = 18.4,
    provenance: Provenance | None = None,
) -> Answer:
    return Answer(
        question="Синтетический вопрос?",
        document_id=document_id,
        outcome=outcome,
        claims=claims if claims is not None else [_claim()],
        shown=shown if shown is not None else [_shown()],
        retried=retried,
        not_found_first=not_found_first,
        not_found_final=not_found_final,
        failure=failure,
        warnings=warnings or [],
        provenance=provenance or _provenance(),
        seconds=seconds,
    )


def _lines(answer: Answer) -> list[str]:
    return render_answer_text(answer).splitlines()


def test_answered_first_line_counts_confirmed_claims() -> None:
    claims = [_claim("Первое."), _claim("Второе.", status=ClaimStatus.NO_QUOTE, clause_id=None)]
    lines = _lines(_answer(claims=claims))
    assert lines[0] == "Вопрос в D-0001 — ответ: подтверждено 1 из 2 утверждений, 18,4 с"


def test_answered_text_has_numbered_claim_quote_and_reference() -> None:
    out = render_answer_text(_answer(claims=[_claim("Оплата — 30 дней.")]))
    assert "1. Оплата — 30 дней." in out
    assert "   «Синтетическая цитата.»" in out
    assert "   D-0001/2.2, стр. 1" in out


def test_unconfirmed_first_line_and_block() -> None:
    claims = [
        _claim("Первое.", status=ClaimStatus.QUOTE_NOT_FOUND, clause_id=None),
        _claim("Второе.", status=ClaimStatus.NO_QUOTE, clause_id=None),
    ]
    answer = _answer(
        AnswerOutcome.UNCONFIRMED,
        claims=claims,
        retried=True,
        not_found_first=2,
        not_found_final=2,
    )
    lines = _lines(answer)
    assert lines[0] == (
        "Вопрос в D-0001 — подтверждённого ответа нет: "
        "ни одна из 2 цитат не найдена, 18,4 с"
    )
    assert "Не подтверждено (цитата не найдена):" in lines
    assert "- Первое." in lines
    assert "- Второе. (нет цитаты)" in lines
    assert "Повтор запроса: цитат не найдено 2, после повтора 2" in lines
    assert not any(line.startswith("   «") for line in lines)  # no confirmed claims shown


def test_not_found_first_line_without_claims() -> None:
    answer = _answer(AnswerOutcome.NOT_FOUND, claims=[], shown=[], document_id=None)
    lines = _lines(answer)
    assert lines[0] == "Вопрос по всем договорам — в документах ответ не найден, 18,4 с"
    assert "Просмотрено: отрывков не найдено" in lines


def test_failed_first_line_and_shown_passages() -> None:
    answer = _answer(
        AnswerOutcome.FAILED,
        claims=[],
        failure="ответ модели не по форме после 3 попыток",
        seconds=40.1,
    )
    lines = _lines(answer)
    assert lines[0] == (
        "Вопрос в D-0001 — ошибка ответа модели: "
        "ответ модели не по форме после 3 попыток, 40,1 с"
    )
    assert "Просмотрено (1):" in lines


def test_warnings_follow_the_first_line() -> None:
    lines = _lines(_answer(warnings=["индексы устарели", "реранкер не ответил"]))
    assert lines[1:3] == ["! индексы устарели", "! реранкер не ответил"]


def test_corrected_reference_names_the_clause_the_model_gave() -> None:
    claim = _claim(
        status=ClaimStatus.CONFIRMED_ELSEWHERE,
        named_clause="D-0001/3.2",
        clause_id="D-0001/2.2",
    )
    out = render_answer_text(_answer(claims=[claim]))
    assert (
        "   D-0001/2.2, стр. 1 (ссылка исправлена: модель указала D-0001/3.2)" in out
    )


def test_added_preamble_is_marked_by_the_rule() -> None:
    shown = [
        _shown("D-0001/2.2"),
        _shown("D-0001/преамбула", word_place=None, vector_place=None, added_by_rule=True),
    ]
    out = render_answer_text(_answer(shown=shown))
    assert "Просмотрено (2):" in out
    assert "  1. D-0001/2.2  стр. 1  Пункт условный  (слова 1, смысл 2)" in out
    assert "  —  D-0001/преамбула  стр. 1  Пункт условный  (добавлена правилом)" in out


def test_no_shown_passages_says_so() -> None:
    out = render_answer_text(_answer(shown=[]))
    assert "Просмотрено: отрывков не найдено" in out
    assert "Просмотрено (" not in out


def test_page_range_with_en_dash_and_list_otherwise() -> None:
    claims = [
        _claim("Один.", pages=(1, 2)),
        _claim("Два.", pages=(1, 3)),
    ]
    out = render_answer_text(_answer(claims=claims))
    assert "   D-0001/2.2, стр. 1–2" in out
    assert "   D-0001/2.2, стр. 1, 3" in out


def test_retry_line_only_when_retried() -> None:
    plain = render_answer_text(_answer())
    assert "Повтор запроса" not in plain
    retried = render_answer_text(_answer(retried=True, not_found_first=2, not_found_final=1))
    assert "Повтор запроса: цитат не найдено 2, после повтора 1" in retried


def test_shown_placeholder_for_missing_places() -> None:
    out = render_answer_text(_answer(shown=[_shown(word_place=None, vector_place=None)]))
    assert "(слова —, смысл —)" in out


def test_provenance_line_with_reranker_and_without() -> None:
    out = render_answer_text(_answer())
    assert out.rstrip("\n").splitlines()[-1] == (
        "Получено: код abc1234; модель fake-llm, подсказка 09.1; "
        "поиск fake-embedding, реранкер fake-reranker; "
        "отрывков 8, кандидатов 30, rrf_k 60, реранкер читает 30"
    )
    off = render_answer_text(_answer(provenance=_provenance(reranker_model=None)))
    assert "реранкер выключен;" in off


def test_text_ends_with_newline() -> None:
    assert render_answer_text(_answer()).endswith("\n")


def test_json_is_to_json_dumped_without_ascii_escapes() -> None:
    answer = _answer()
    text = render_answer_json(answer)
    assert text == json.dumps(answer.to_json(), ensure_ascii=False, indent=2)
    assert "Синтетическая цитата." in text
    assert json.loads(text) == json.loads(json.dumps(answer.to_json()))
