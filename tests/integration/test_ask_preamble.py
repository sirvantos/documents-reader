"""The passages shown to the model and the preamble rule (feature 09; FR-010, research R-5; T008).

Written by the main session (critical part, CLAUDE.md «Model routing»): the implementer
must not edit, weaken, skip or delete these tests.
"""

from __future__ import annotations

import pytest

from docreader import answer, search
from docreader.config import load_settings
from docreader.textnorm import locate
from tests.integration.answer_fixtures import index_answer_contracts


@pytest.fixture
def indexed(cli, tmp_path, use_embedder):
    return index_answer_contracts(cli, tmp_path, use_embedder)


def hits_of(db, document_id: str | None, *, without_preamble: bool) -> list[search.Hit]:
    result = search.search(
        db, load_settings(), "срок оплаты", document_id=document_id, rerank=False, results=30
    )
    hits = list(result.hits)
    if without_preamble:
        hits = [h for h in hits if h.clause_key != "преамбула"]
    assert hits
    return hits


def test_preamble_appended_last_when_the_search_missed_it(cli, db, indexed) -> None:
    hits = hits_of(db, "D-0001", without_preamble=True)[:3]
    shown, texts = answer.shown_passages(db, hits, "D-0001")
    assert [p.clause_id for p in shown[:3]] == [h.clause_id for h in hits]
    last = shown[-1]
    assert len(shown) == 4
    assert last.clause_id == "D-0001/преамбула"
    assert last.added_by_rule is True
    assert last.search_place is None and last.fused_place is None
    assert last.label == "D-0001 · преамбула"
    assert "D-0001" in texts
    text = texts["D-0001"].text
    assert locate(text[last.start : last.end], "именуемое в дальнейшем Подрядчик")


def test_found_passages_keep_their_places(cli, db, indexed) -> None:
    hits = hits_of(db, "D-0001", without_preamble=True)[:3]
    shown, texts = answer.shown_passages(db, hits, "D-0001")
    for p, h in zip(shown[:3], hits, strict=True):
        assert p.search_place == h.place
        assert (p.word_place, p.vector_place, p.fused_place) == (
            h.word_place, h.vector_place, h.fused_place
        )
        assert p.added_by_rule is False
        assert (p.document_id, p.clause_key, p.label) == (h.document_id, h.clause_key, h.label)
        assert (p.first_page, p.last_page) == (h.first_page, h.last_page)
        assert texts[p.document_id].text[p.start : p.end] == h.text


def test_preamble_found_by_the_search_is_not_doubled(cli, db, indexed) -> None:
    hits = hits_of(db, "D-0001", without_preamble=False)
    assert any(h.clause_key == "преамбула" for h in hits)
    shown, _ = answer.shown_passages(db, hits, "D-0001")
    assert [p.clause_id for p in shown] == [h.clause_id for h in hits]
    assert not any(p.added_by_rule for p in shown)


def test_document_without_a_preamble_gets_nothing_added(cli, db, indexed) -> None:
    hits = hits_of(db, "D-0002", without_preamble=True)[:2]
    shown, _ = answer.shown_passages(db, hits, "D-0002")
    assert [p.clause_id for p in shown] == [h.clause_id for h in hits]


def test_no_preamble_added_without_a_document(cli, db, indexed) -> None:
    hits = hits_of(db, None, without_preamble=True)[:3]
    shown, texts = answer.shown_passages(db, hits, None)
    assert [p.clause_id for p in shown] == [h.clause_id for h in hits]
    assert set(texts) == {p.document_id for p in shown}


def test_no_hits_nothing_added(cli, db, indexed) -> None:
    shown, texts = answer.shown_passages(db, [], "D-0001")
    assert shown == [] and texts == {}


def test_stale_preamble_is_not_appended(cli, db, indexed) -> None:
    hits = hits_of(db, "D-0001", without_preamble=True)[:2]
    # re-parse: the passages of D-0001 are now from an older parse run (stale)
    assert cli("parse", "D-0001").exit_code == 0
    shown, _ = answer.shown_passages(db, hits, "D-0001")
    assert not any(p.added_by_rule for p in shown)


def test_spans_give_the_pages_of_clause_4_1(cli, db, indexed) -> None:
    hits = [h for h in hits_of(db, "D-0001", without_preamble=True) if h.clause_key == "4.1"]
    shown, texts = answer.shown_passages(db, hits, "D-0001")
    p = next(p for p in shown if p.clause_key == "4.1")
    doc = texts["D-0001"]
    pages = sorted({page for s, e, page, _ in doc.spans if s < p.end and e > p.start})
    assert pages == [1, 2]
    assert list(doc.spans) == sorted(doc.spans)
