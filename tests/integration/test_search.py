"""Integration tests for `docreader search` and `search.search` (feature 08).

US1 (task T008): words + meaning + fusion, the places of each way, warnings, the
checks before search. Later tasks add US2 (T012), US3 (T014) and the measurement
(T018). Everything goes through `add`, `read`, `parse`, `index` on the synthetic
contracts of `make_search_contracts` with `TopicEmbedder` (research R-8). Written by
the main session; the implementer must not edit, weaken, skip or delete these tests
(CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import json

import pytest

from docreader import embedding, search
from docreader.config import load_settings
from tests.integration.test_search_scope import index_search_contracts

ORIGINAL_LOAD_EMBEDDER = embedding.load_embedder
EMBED_FORBIDDEN = "На этой машине модель поиска не запускается (DOCREADER_FORBID_MODELS)"
EMPTY_QUERY = "Пустой запрос — введите слова для поиска"
NO_WORDS = "в запросе нет слов для поиска по словам — только поиск по смыслу"
WORDS_FOUND_NOTHING = "поиск по словам ничего не нашёл"
HIT_KEYS = {
    "place", "clause_id", "label", "text", "first_page", "last_page",
    "word_place", "vector_place", "fused_place", "rerank_score",
}
TOP_KEYS = {
    "query", "document_id", "reranked", "embedding_model", "reranker_model",
    "word_candidates", "vector_candidates", "seconds", "warnings", "hits",
}


@pytest.fixture
def indexed(cli, tmp_path, use_embedder):
    return index_search_contracts(cli, tmp_path, use_embedder)


def run(cli, *args, code: int = 0) -> dict:
    result = cli("search", *args, "--no-rerank", "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout)


def ids(report: dict) -> list[str]:
    return [h["clause_id"] for h in report["hits"]]


def hit(report: dict, clause_id: str) -> dict:
    (found,) = [h for h in report["hits"] if h["clause_id"] == clause_id]
    return found


def rrf_score(h: dict, k: int = 60) -> float:
    return sum(1 / (k + p) for p in (h["word_place"], h["vector_place"]) if p is not None)


def stale(cli, doc: str) -> None:
    result = cli("parse", doc)
    assert result.exit_code == 0, result.stderr


# --- what is found -----------------------------------------------------------------------


def test_number_found_by_words(cli, indexed) -> None:
    report = run(cli, "ДП-17/2026")
    found = hit(report, "D-0001/1.1")
    assert found["word_place"] == 1
    assert "D-0001/1.1" in ids(report)[:2]
    assert report["word_candidates"] == 2  # the preamble of D-0001 holds the number too


def test_paraphrase_found_by_meaning_only(cli, indexed) -> None:
    report = run(cli, "куда переводить деньги")
    found = hit(report, "D-0002/2.3")
    assert found["word_place"] is None and found["vector_place"] is not None
    assert report["word_candidates"] == 0
    assert WORDS_FOUND_NOTHING in report["warnings"]


def test_word_form_found_by_words(cli, indexed) -> None:
    report = run(cli, "неустойки")
    assert hit(report, "D-0001/3.1")["word_place"] == 1
    assert "неустойку 0,1%" in hit(report, "D-0001/3.1")["text"]


def test_fusion_order_follows_places(cli, indexed) -> None:
    report = run(cli, "срок оплаты")
    hits = report["hits"]
    assert [h["place"] for h in hits] == list(range(1, len(hits) + 1))
    assert [h["fused_place"] for h in hits] == [h["place"] for h in hits]
    scores = [rrf_score(h) for h in hits]
    assert scores == sorted(scores, reverse=True)
    # found by both ways ranks above found by one way
    both = [h["place"] for h in hits if h["word_place"] and h["vector_place"]]
    one = [h["place"] for h in hits if not (h["word_place"] and h["vector_place"])]
    assert both and one and max(both) < min(one)


def test_json_form(cli, indexed) -> None:
    report = run(cli, "срок оплаты")
    assert set(report) == TOP_KEYS
    assert report["query"] == "срок оплаты" and report["document_id"] is None
    assert report["reranked"] is False and report["reranker_model"] is None
    assert report["embedding_model"] == "fake-embedder"
    assert report["vector_candidates"] == 18  # every current passage: fewer than 30
    assert len(report["hits"]) == 8  # [search] results
    for h in report["hits"]:
        assert set(h) == HIT_KEYS
        assert h["rerank_score"] is None
        assert 1 <= h["first_page"] <= h["last_page"]
        assert h["label"].startswith(h["clause_id"].split("/")[0])
        assert h["text"]
    assert isinstance(report["seconds"], float)


def test_text_of_hit_is_the_passage(cli, db, indexed) -> None:
    report = run(cli, "гарантийный срок")
    found = hit(report, "D-0001/4.1")
    label, text, first, last = db.execute(
        "SELECT p.label, substr(t.text, p.start + 1, p.end_ - p.start), p.first_page,"
        " p.last_page FROM passage p JOIN document_text t USING (document_id)"
        " WHERE p.document_id = 'D-0001' AND p.clause_key = '4.1'"
    ).fetchone()
    assert (found["label"], found["text"], found["first_page"], found["last_page"]) == (
        label, text, first, last
    )


def test_same_query_same_list(cli, indexed) -> None:
    first = run(cli, "срок оплаты")
    second = run(cli, "срок оплаты")
    assert [(h["clause_id"], h["word_place"], h["vector_place"]) for h in first["hits"]] == [
        (h["clause_id"], h["word_place"], h["vector_place"]) for h in second["hits"]
    ]


def test_results_option(cli, indexed) -> None:
    assert len(run(cli, "срок оплаты", "--results", "3")["hits"]) == 3


@pytest.mark.parametrize("value", ["0", "31"])
def test_results_option_bounds(cli, indexed, value: str) -> None:
    result = cli("search", "срок оплаты", "--no-rerank", "--results", value)
    assert result.exit_code == 1
    assert "--results: целое от 1 до 30" in result.stderr


def test_function_gives_the_cli_list(cli, db, indexed) -> None:
    result = search.search(db, load_settings(), "срок оплаты", rerank=False)
    assert [h.clause_id for h in result.hits] == ids(run(cli, "срок оплаты"))
    assert result.reranked is False and result.document_id is None


def test_text_output(cli, indexed) -> None:
    result = cli("search", "неустойки", "--no-rerank")
    assert result.exit_code == 0, result.stderr
    assert "D-0001/3.1" in result.stdout
    assert "неустойку 0,1%" in result.stdout


# --- edge cases --------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["", "   "])
def test_empty_query_before_any_model(cli, indexed, query: str) -> None:
    _, fake = indexed
    before = len(fake.inputs)
    result = cli("search", query, "--no-rerank")
    assert result.exit_code == 1
    assert EMPTY_QUERY in result.stderr
    assert len(fake.inputs) == before


def test_only_function_words(cli, indexed) -> None:
    report = run(cli, "и в на по")
    assert report["word_candidates"] == 0
    assert NO_WORDS in report["warnings"]
    assert report["hits"] and all(h["word_place"] is None for h in report["hits"])


def test_long_query_cut_for_the_model(cli, data_dir, indexed) -> None:
    _, fake = indexed
    (data_dir / "settings.toml").write_text("[embedding]\nmax_chars = 40\n", encoding="utf-8")
    query = "срок оплаты товара " * 5
    report = run(cli, query)
    assert fake.inputs[-1] == query[:40]
    assert (
        "запрос длиннее предела модели поиска (40 знаков) — вектор построен по его началу"
        in report["warnings"]
    )
    assert report["query"] == query


def test_stale_documents_warned_and_not_searched(cli, indexed) -> None:
    stale(cli, "D-0003")
    report = run(cli, "срок оплаты")
    assert "договоров без актуальных отрывков: 1 — выполните docreader index" in report[
        "warnings"
    ]
    wide = ids(run(cli, "срок оплаты", "--results", "30"))
    assert not [i for i in wide if i.startswith("D-0003")]


def test_no_warning_when_all_current(cli, indexed) -> None:
    assert run(cli, "срок оплаты")["warnings"] == []


def test_forbidden_without_fake(cli, indexed, monkeypatch) -> None:
    monkeypatch.setattr(embedding, "load_embedder", ORIGINAL_LOAD_EMBEDDER)
    result = cli("search", "МАРКЕР-9921 срок", "--no-rerank")
    assert result.exit_code == 2
    assert EMBED_FORBIDDEN in result.stderr
    assert "МАРКЕР-9921" not in result.stderr and result.stdout == ""


def test_empty_indexes_code_1(cli, tmp_path) -> None:
    result = cli("search", "срок оплаты", "--no-rerank")
    assert result.exit_code == 1
    assert "Индексы пусты — выполните docreader index" in result.stderr


def test_errors_do_not_hold_the_query(cli, indexed, data_dir) -> None:
    (data_dir / "settings.toml").write_text('[embedding]\nmodel = "frida"\n', encoding="utf-8")
    result = cli("search", "МАРКЕР-7710 оплата", "--no-rerank")
    assert result.exit_code == 2
    assert "нет векторов frida" in result.stderr
    assert "МАРКЕР-7710" not in result.stderr


# --- US2: one document (task T012) -------------------------------------------------------


def test_typical_clause_of_three_contracts_on_top(cli, indexed) -> None:
    report = run(cli, "срок оплаты")
    assert set(ids(report)[:3]) == {"D-0001/2.2", "D-0002/2.2", "D-0003/2.2"}


def test_document_limits_every_hit(cli, indexed) -> None:
    report = run(cli, "срок оплаты", "--document", "D-0002")
    assert report["document_id"] == "D-0002"
    assert report["hits"] and all(i.startswith("D-0002/") for i in ids(report))
    assert ids(report)[0] == "D-0002/2.2"


def test_document_in_short_form(cli, indexed) -> None:
    assert run(cli, "срок оплаты", "--document", "d-2")["document_id"] == "D-0002"


def test_document_with_fewer_passages_than_results(cli, db, indexed) -> None:
    report = run(cli, "срок оплаты", "--document", "D-0003", "--results", "30")
    count = db.execute("SELECT count(*) FROM passage WHERE document_id = 'D-0003'").fetchone()[0]
    assert count < 30
    assert sorted(ids(report)) == sorted(set(ids(report)))
    assert len(ids(report)) == count


def test_function_with_document(cli, db, indexed) -> None:
    result = search.search(db, load_settings(), "оплата", document_id="D-0001", rerank=False)
    assert result.document_id == "D-0001"
    assert all(h.clause_id.startswith("D-0001/") for h in result.hits)


def test_document_search_has_no_stale_warning(cli, indexed) -> None:
    stale(cli, "D-0003")
    assert run(cli, "срок оплаты", "--document", "D-0001")["warnings"] == []


@pytest.mark.parametrize(
    ("setup", "doc", "message"),
    [
        (None, "D-0099", "Документ D-0099 не найден — список документов: docreader list"),
        ("stale", "D-0002",
         "Отрывки устарели: текст или разбор изменились — выполните docreader index D-0002"),
        ("new", "D-0004", "Отрывков нет: выполните docreader index D-0004"),
    ],
)
def test_document_errors_before_any_model(
    cli, tmp_path, indexed, setup, doc: str, message: str
) -> None:
    from tests.integration.test_read import add_files
    from tests.synthetic import make_pdfs as mk

    _, fake = indexed
    if setup == "stale":
        stale(cli, "D-0002")
    elif setup == "new":
        add_files(cli, tmp_path / "more", [mk.make_passage_contract])
        assert cli("read").exit_code == 0 and cli("parse").exit_code == 0
    before = len(fake.inputs)
    result = cli("search", "срок оплаты", "--no-rerank", "--document", doc)
    assert result.exit_code == 1
    assert message in result.stderr
    assert result.stdout == ""
    assert len(fake.inputs) == before
