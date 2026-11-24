"""Rendering of `docreader index` (feature 07, task T018)."""

from __future__ import annotations

from docreader.indexing import IndexedDocument, IndexRun, SkippedDocument, Stopped
from docreader.render import NOTHING_TO_INDEX, render_index_text


def _run() -> IndexRun:
    return IndexRun(
        run_id=72,
        model="bge-m3",
        served_model="bge-m3-Q8_0.gguf",
        dims=1024,
        documents=[
            IndexedDocument("D-0001", "done", None, 118, 118, 118, 0, 1.5),
            IndexedDocument(
                "D-0002", "needs_review", "отрывок длиннее предела модели: D-0002/7.4",
                120, 120, 120, 1, 2.0,
            ),
            IndexedDocument(
                "D-0004", "failed", "ошибка построения векторов: EmbeddingRequestError",
                0, 0, 0, 0, 0.1,
            ),
        ],
        skipped=[SkippedDocument("D-0003", "не разобран — выполните docreader parse D-0003")],
    )


def test_text_lines_and_totals() -> None:
    assert render_index_text(_run()).splitlines() == [
        "D-0001  готово             отрывков 118, по словам 118, по смыслу 118",
        "D-0002  требует просмотра  отрывков 120, по словам 120, по смыслу 120"
        " — отрывок длиннее предела модели: D-0002/7.4",
        "D-0004  ошибка             ошибка построения векторов: EmbeddingRequestError",
        "D-0003  пропущен           не разобран — выполните docreader parse D-0003",
        "Итого: готово 1, требует просмотра 1, ошибок 1, пропущено 1; отрывков 238"
        " (запуск 72, модель bge-m3, размерность 1024)",
    ]


def test_stopped_line() -> None:
    run = _run()
    run.stopped = Stopped("D-0005", "модель поиска не ответила")
    assert "Остановлено на D-0005: модель поиска не ответила" in render_index_text(run)


def test_nothing() -> None:
    assert render_index_text(IndexRun()) == NOTHING_TO_INDEX


def test_json_keys() -> None:
    data = _run().to_json()
    assert list(data) == [
        "run_id", "model", "served_model", "dims", "documents", "skipped", "totals",
        "interrupted", "stopped",
    ]
    assert list(data["documents"][0]) == [
        "document_id", "state", "reason", "passages", "word_entries", "vectors", "truncated",
        "seconds",
    ]
    assert data["totals"] == {
        "indexed": 1, "needs_review": 1, "failed": 1, "skipped": 1, "passages": 238,
    }
    assert data["stopped"] is None


def _view(**kw):
    from docreader.passageview import PassageView, VectorInfo

    base = dict(
        clause_id="D-0001/5.2", document_id="D-0001", clause_key="5.2", part="main",
        first_page=3, last_page=4, label="D-0001 · раздел 5. X · пункт 5.2", text="тело",
        word_index=True, vectors=[VectorInfo("bge-m3", 1024, False, 10)], run_id=72,
        run_date="2026-11-25",
    )
    base.update(kw)
    return PassageView(**base)


def test_passage_text() -> None:
    from docreader.render import render_passage_text

    assert render_passage_text(_view()).splitlines() == [
        "D-0001/5.2 — стр. 3–4, основной текст (индексация: запуск 72, 2026-11-25)",
        "Метка: D-0001 · раздел 5. X · пункт 5.2",
        "В индексе по словам: да",
        "В индексе по смыслу: bge-m3, размерность 1024",
        "Текст:",
        "тело",
    ]


def test_passage_single_page_part_and_truncated() -> None:
    from docreader.passageview import VectorInfo
    from docreader.render import render_passage_text

    out = render_passage_text(
        _view(first_page=2, last_page=2, part="tail", vectors=[VectorInfo("m", 8, True, 60)])
    )
    assert out.splitlines()[0].startswith("D-0001/5.2 — стр. 2, реквизиты (")
    assert "В индексе по смыслу: m, размерность 8 (вход обрезан до 60 знаков)" in out
