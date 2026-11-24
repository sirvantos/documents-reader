"""Scope of the search: which passages are searched (feature 08, research R-3, R-5, R-6; T007).

Critical part (CLAUDE.md «Model routing»): only current passages are searched (their
text and parse run are the document's current ones), documents without them are
counted, the vectors of another model are never compared, and a search limited to one
document never widens. Everything goes through `add`, `read`, `parse` and `index` on the
synthetic contracts of `make_search_contracts`, with `TopicEmbedder`. Written by the
main session; the implementer must not edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

import pytest

from docreader import search
from docreader.errors import EnvironmentProblem, UserError
from tests.fakes.embedding import TopicEmbedder
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk

# The topics of the search tests (tasks T008, T012, T014, T018).
SEARCH_TOPICS = {
    "payment": ["оплат", "плат", "перечисл", "денежн", "деньг"],
    "penalty": ["неустойк", "штраф", "пен"],
    "warranty": ["гарант"],
}


def add_search_contracts(cli, folder) -> list[str]:
    paths = mk.make_search_contracts(folder / "made")
    makers = [lambda dst, src=p: dst.write_bytes(src.read_bytes()) for p in paths]
    return add_files(cli, folder / "in", makers)


def index_search_contracts(cli, folder, use_embedder) -> tuple[list[str], TopicEmbedder]:
    ids = add_search_contracts(cli, folder)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    fake = use_embedder(TopicEmbedder(SEARCH_TOPICS))
    result = cli("index")
    assert result.exit_code == 0, result.stderr
    return ids, fake


@pytest.fixture
def indexed(cli, tmp_path, use_embedder) -> tuple[list[str], TopicEmbedder]:
    return index_search_contracts(cli, tmp_path, use_embedder)


def _passage_count(db, doc: str | None = None) -> int:
    if doc is None:
        return db.execute("SELECT count(*) FROM passage").fetchone()[0]
    return db.execute(
        "SELECT count(*) FROM passage WHERE document_id = %s", (doc,)
    ).fetchone()[0]


def _reparse(cli, doc: str) -> None:
    result = cli("parse", doc)
    assert result.exit_code == 0, result.stderr


# --- the whole set ---------------------------------------------------------------------


def test_all_current_after_index(db, indexed) -> None:
    ids, _ = indexed
    assert ids == ["D-0001", "D-0002", "D-0003"]
    assert search.stale_documents(db) == 0
    assert search.ensure_searchable(db, "bge-m3", None) is None
    corpus = search.word_corpus(db, None)
    assert len(corpus) == _passage_count(db)
    keys = [k for k, _ in corpus]
    assert keys == sorted(keys)
    assert {k[0] for k in keys} == set(ids)


def test_word_corpus_holds_lower_cased_lemmas(db, indexed) -> None:
    lemmas = dict(
        ((doc, ordinal), text)
        for doc, ordinal, text in db.execute(
            "SELECT document_id, ordinal, lemmas FROM passage"
        )
    )
    for passage_key, words in search.word_corpus(db, None):
        assert words == lemmas[passage_key].lower().split()
    all_words = {w for _, words in search.word_corpus(db, None) for w in words}
    assert "дп-17/2026" in all_words and "оплата" in all_words


def test_vector_candidates_nearest_first(db, indexed) -> None:
    _, fake = indexed
    label, text = db.execute(
        "SELECT p.label, substr(t.text, p.start + 1, p.end_ - p.start) FROM passage p"
        " JOIN document_text t USING (document_id)"
        " WHERE p.document_id = 'D-0001' AND p.clause_key = '3.1'"
    ).fetchone()
    own = fake.topic_vector(label + "\n" + text)
    ordinal = db.execute(
        "SELECT ordinal FROM passage WHERE document_id = 'D-0001' AND clause_key = '3.1'"
    ).fetchone()[0]
    got = search.vector_candidates(db, "bge-m3", own, 5, None)
    assert len(got) == 5
    assert got[0] == ("D-0001", ordinal)
    assert len(set(got)) == 5


def test_vector_candidates_whole_set_when_n_large(db, indexed) -> None:
    _, fake = indexed
    got = search.vector_candidates(db, "bge-m3", fake.topic_vector("оплата"), 500, None)
    assert len(got) == _passage_count(db)


def test_vector_candidates_same_order_twice(db, indexed) -> None:
    _, fake = indexed
    vector = fake.topic_vector("срок оплаты")
    first = search.vector_candidates(db, "bge-m3", vector, 30, None)
    assert search.vector_candidates(db, "bge-m3", vector, 30, None) == first


def test_vector_candidates_of_another_model_are_none(db, indexed) -> None:
    _, fake = indexed
    assert search.vector_candidates(db, "frida", fake.topic_vector("оплата"), 30, None) == []


# --- one document ------------------------------------------------------------------------


def test_document_scope(db, indexed) -> None:
    _, fake = indexed
    assert search.ensure_searchable(db, "bge-m3", "D-0002") == "D-0002"
    assert search.ensure_searchable(db, "bge-m3", "d-2") == "D-0002"
    corpus = search.word_corpus(db, "D-0002")
    assert corpus and {k[0] for k, _ in corpus} == {"D-0002"}
    assert len(corpus) == _passage_count(db, "D-0002")
    got = search.vector_candidates(db, "bge-m3", fake.topic_vector("оплата"), 500, "D-0002")
    assert {k[0] for k in got} == {"D-0002"} and len(got) == _passage_count(db, "D-0002")


def test_unknown_document(db, indexed) -> None:
    with pytest.raises(UserError) as exc:
        search.ensure_searchable(db, "bge-m3", "D-0099")
    assert str(exc.value) == "Документ D-0099 не найден — список документов: docreader list"


def test_malformed_document_id(db, indexed) -> None:
    with pytest.raises(UserError):
        search.ensure_searchable(db, "bge-m3", "договор-7")


def test_document_without_passages(cli, db, tmp_path, indexed) -> None:
    (doc,) = add_files(cli, tmp_path / "more", [mk.make_passage_contract])
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    assert doc == "D-0004"
    with pytest.raises(UserError) as exc:
        search.ensure_searchable(db, "bge-m3", doc)
    assert str(exc.value) == "Отрывков нет: выполните docreader index D-0004"
    # never indexed → counted, and the rest is still searchable
    assert search.stale_documents(db) == 1
    assert search.ensure_searchable(db, "bge-m3", None) is None


def test_document_reparsed_after_index_is_stale(cli, db, indexed) -> None:
    before = _passage_count(db, "D-0002")
    _reparse(cli, "D-0002")
    assert _passage_count(db, "D-0002") == before  # the passages are still stored
    assert search.stale_documents(db) == 1
    with pytest.raises(UserError) as exc:
        search.ensure_searchable(db, "bge-m3", "D-0002")
    assert str(exc.value) == (
        "Отрывки устарели: текст или разбор изменились — выполните docreader index D-0002"
    )
    assert "D-0002" not in {k[0] for k, _ in search.word_corpus(db, None)}
    vec = [0.0] * 15 + [1.0]
    assert "D-0002" not in {k[0] for k in search.vector_candidates(db, "bge-m3", vec, 500, None)}


def test_document_with_changed_text_is_stale(db, indexed) -> None:
    db.execute(
        "UPDATE document_text SET text_sha256 = repeat('0', 64) WHERE document_id = 'D-0003'"
    )
    assert search.stale_documents(db) == 1
    assert "D-0003" not in {k[0] for k, _ in search.word_corpus(db, None)}
    with pytest.raises(UserError, match="Отрывки устарели"):
        search.ensure_searchable(db, "bge-m3", "D-0003")


# --- the indexes as a whole ----------------------------------------------------------------


def test_vectors_of_another_model(db, indexed) -> None:
    with pytest.raises(EnvironmentProblem) as exc:
        search.ensure_searchable(db, "frida", None)
    assert str(exc.value) == (
        "Индекс по смыслу построен другой моделью (нет векторов frida) — выполните "
        "docreader index --all или укажите [embedding] model"
    )
    with pytest.raises(EnvironmentProblem, match="нет векторов frida"):
        search.ensure_searchable(db, "frida", "D-0001")


def test_empty_indexes(cli, db, tmp_path) -> None:
    add_search_contracts(cli, tmp_path)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    with pytest.raises(UserError) as exc:
        search.ensure_searchable(db, "bge-m3", None)
    assert str(exc.value) == "Индексы пусты — выполните docreader index"
    assert search.stale_documents(db) == 3


def test_all_passages_stale_is_empty(cli, db, indexed) -> None:
    for doc in ("D-0001", "D-0002", "D-0003"):
        _reparse(cli, doc)
    with pytest.raises(UserError, match="Индексы пусты"):
        search.ensure_searchable(db, "bge-m3", None)
