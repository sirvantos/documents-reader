"""Text output of `docreader search` and its argument parsing (contracts/cli.md «docreader search»).

Synthetic text only; results are built by hand.
"""

import pytest

from docreader.cli import _build_parser, main
from docreader.render import render_search_text
from docreader.search import Hit, SearchResult


def _hit(
    place: int = 1,
    *,
    clause_id: str = "D-0001/1.1",
    label: str = "Пункт первый",
    text: str = "Текст отрывка.",
    first_page: int | None = 1,
    last_page: int | None = 1,
    word_place: int | None = 1,
    vector_place: int | None = 2,
    fused_place: int = 1,
    rerank_score: float | None = None,
) -> Hit:
    return Hit(
        place=place,
        document_id=clause_id.split("/")[0],
        clause_key="key",
        clause_id=clause_id,
        label=label,
        text=text,
        first_page=first_page,
        last_page=last_page,
        word_place=word_place,
        vector_place=vector_place,
        fused_place=fused_place,
        rerank_score=rerank_score,
    )


def _result(
    hits: list[Hit] | None = None,
    *,
    document_id: str | None = None,
    reranked: bool = False,
    warnings: list[str] | None = None,
    seconds: float = 1.8,
) -> SearchResult:
    return SearchResult(
        query="synthetic query",
        document_id=document_id,
        reranked=reranked,
        hits=hits if hits is not None else [_hit()],
        word_candidates=5,
        vector_candidates=7,
        warnings=warnings or [],
        embedding_model="fake-model",
        reranker_model="fake-reranker" if reranked else None,
        seconds=seconds,
    )


def test_header_all_documents_without_reranker() -> None:
    lines = render_search_text(_result()).splitlines()
    assert lines[0] == (
        "Запрос по всем договорам, без реранкера — результатов 1 "
        "(кандидатов по словам 5, по смыслу 7), 1,8 с"
    )


def test_header_one_document_with_reranker() -> None:
    result = _result(document_id="D-0015", reranked=True)
    lines = render_search_text(result).splitlines()
    assert lines[0] == (
        "Запрос в D-0015, реранкер fake-reranker — результатов 1 "
        "(кандидатов по словам 5, по смыслу 7), 1,8 с"
    )


def test_seconds_one_decimal_with_comma() -> None:
    lines = render_search_text(_result(seconds=0.25)).splitlines()
    assert lines[0].endswith(", 0,2 с")


def test_warnings_follow_header_as_bang_lines() -> None:
    text = render_search_text(_result(warnings=["Документ D-0003 устарел", "Запрос обрезан"]))
    lines = text.splitlines()
    assert lines[1] == "! Документ D-0003 устарел"
    assert lines[2] == "! Запрос обрезан"
    assert lines[3] == ""


def test_no_hits_says_nothing_found() -> None:
    text = render_search_text(_result(hits=[], warnings=["Документ D-0003 устарел"]))
    assert text == (
        "Запрос по всем договорам, без реранкера — результатов 0 "
        "(кандидатов по словам 5, по смыслу 7), 1,8 с\n"
        "! Документ D-0003 устарел\n"
        "Ничего не найдено\n"
    )


def test_place_line_without_score_and_with_missing_place_dash() -> None:
    hit = _hit(word_place=None, vector_place=3, fused_place=2)
    text = render_search_text(_result(hits=[hit]))
    assert "  (слова —, смысл 3, слияние 2)" in text.splitlines()
    assert "оценка" not in text


def test_place_line_with_score_and_both_places() -> None:
    hit = _hit(word_place=1, vector_place=None, fused_place=1, rerank_score=0.91234)
    lines = render_search_text(_result(hits=[hit], reranked=True)).splitlines()
    assert lines[2] == "1. D-0001/1.1  стр. 1"
    assert lines[3] == "  оценка 0.912"
    assert lines[4] == "  (слова 1, смысл —, слияние 1)"


def test_one_page_shows_single_number() -> None:
    lines = render_search_text(_result(hits=[_hit(first_page=4, last_page=4)])).splitlines()
    assert lines[2] == "1. D-0001/1.1  стр. 4"


def test_multi_page_shows_range() -> None:
    lines = render_search_text(_result(hits=[_hit(first_page=4, last_page=6)])).splitlines()
    assert lines[2] == "1. D-0001/1.1  стр. 4–6"


def test_label_then_indented_text_lines() -> None:
    hit = _hit(label="Оплата", text="первая строка\nвторая строка\nтретья строка")
    lines = render_search_text(_result(hits=[hit])).splitlines()
    assert lines[4] == "   Оплата"
    assert lines[5:8] == [
        "   первая строка",
        "   вторая строка",
        "   третья строка",
    ]


def test_hits_separated_by_one_empty_line() -> None:
    hits = [
        _hit(1, clause_id="D-0001/1.1", text="один"),
        _hit(2, clause_id="D-0001/2.1", text="два", word_place=None, vector_place=1),
    ]
    text = render_search_text(_result(hits=hits, reranked=False))
    lines = text.splitlines()
    second = lines.index("2. D-0001/2.1  стр. 1")
    assert lines[second - 1] == ""
    assert lines[second - 2] == "   один"
    assert lines[second + 1] == "  (слова —, смысл 1, слияние 1)"
    assert text.endswith("   два\n")


def test_text_ends_with_newline() -> None:
    assert render_search_text(_result()).endswith("\n")


def test_parse_search_arguments() -> None:
    args = _build_parser().parse_args(["search", "срок оплаты"])
    assert args.command == "search"
    assert args.query == "срок оплаты"
    assert args.no_rerank is False
    assert args.results is None
    assert args.json is False


def test_parse_search_options() -> None:
    args = _build_parser().parse_args(
        ["search", "неустойки", "--no-rerank", "--results", "3", "--json"]
    )
    assert args.no_rerank is True
    assert args.results == 3
    assert args.json is True


def test_parse_search_document_option() -> None:
    args = _build_parser().parse_args(["search", "срок", "--document", "D-0015"])
    assert args.document == "D-0015"
    assert _build_parser().parse_args(["search", "срок"]).document is None


def test_parse_search_results_must_be_int() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["search", "срок", "--results", "много"])


def test_parse_search_needs_query() -> None:
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["search"])


def test_search_help_exits_zero() -> None:
    assert main(["search", "--help"]) == 0
