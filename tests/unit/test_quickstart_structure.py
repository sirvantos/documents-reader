"""Pure helpers of scripts/quickstart_structure.py on synthetic `parse --json` data (T020)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "quickstart_structure", ROOT / "scripts" / "quickstart_structure.py"
)
assert _spec is not None and _spec.loader is not None
qs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qs)


def _doc(doc_id: str, state: str, reason: str | None = None, **extra) -> dict:
    return {"document_id": doc_id, "state": state, "reason": reason, "sections": 2,
            "clauses": 5, "first_page": 1, "last_page": 3, "has_tail": True, **extra}


def test_reason_kinds() -> None:
    reason = (
        "пропуск: после 5.2 идёт 5.4 (стр. 4), после 8 идёт 10 (стр. 9); повтор: 6 (стр. 4); "
        "нет заголовка раздела 5 (стр. 4); не прочитана страница: стр. 3"
    )
    assert qs.reason_kinds(reason) == [
        "пропуск", "повтор", "нет заголовка раздела", "непрочитанная страница",
    ]
    assert qs.reason_kinds("заголовок раздела 7 после пункта 7.1 (стр. 12)") == [
        "заголовок раздела после его пункта",
    ]
    assert qs.reason_kinds("ошибка разбора: ValueError") == ["другое"]
    assert qs.reason_kinds(None) == []


def test_summarize_parse() -> None:
    data = {
        "documents": [
            _doc("D-0001", "done"),
            _doc("D-0002", "needs_review", "повтор: 6 (стр. 9)", has_tail=False),
            _doc("D-0003", "failed", "ошибка разбора: ValueError", sections=0, clauses=0),
        ],
        "skipped": [{"document_id": "D-0004", "reason": "не прочитан"}],
        "totals": {"parsed": 3, "needs_review": 1, "failed": 1, "skipped": 1},
    }
    text = "\n".join(qs.summarize_parse(data, 12.34))
    assert "время parse --all: 12.3 с" in text and "БОЛЬШЕ МИНУТЫ" not in text
    assert "готово 1, требует просмотра 1, ошибка 1, пропущено 1" in text
    assert "с хвостом (реквизиты): 2 из 3" in text
    assert "повтор: 1" in text
    assert "D-0002  needs_review  повтор: 6 (стр. 9)" in text
    assert "D-0001" not in text
    assert "БОЛЬШЕ МИНУТЫ" in "\n".join(qs.summarize_parse(data, 61))


def test_ids_digest_depends_on_ids_and_order() -> None:
    assert qs.ids_digest(["D-0001/1", "D-0001/1.1"]) == qs.ids_digest(["D-0001/1", "D-0001/1.1"])
    assert qs.ids_digest(["D-0001/1", "D-0001/1.1"]) != qs.ids_digest(["D-0001/1.1", "D-0001/1"])


def test_same_results() -> None:
    a = {"documents": [_doc("D-0001", "done"), _doc("D-0002", "needs_review", "повтор: 6")]}
    b = {"documents": [_doc("D-0002", "needs_review", "повтор: 6"), _doc("D-0001", "done")]}
    c = {"documents": [_doc("D-0001", "done"), _doc("D-0002", "done")]}
    assert qs.same_results(a, b) and not qs.same_results(a, c)


def test_pick_review() -> None:
    docs = [
        _doc("D-0003", "needs_review"), _doc("D-0001", "done"), _doc("D-0056", "needs_review"),
        _doc("D-0002", "done"), _doc("D-0005", "done"), _doc("D-0004", "needs_review"),
        _doc("D-0006", "failed"), _doc("D-0007", "needs_review"),
    ]
    assert qs.pick_review(docs) == ["D-0056", "D-0001", "D-0002", "D-0003", "D-0004"]
    assert qs.pick_review([_doc("D-0001", "done")]) == ["D-0001"]


def test_read_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\n\nDOCREADER_DATA_DIR='/x/data'\nexport A = b\n", encoding="utf-8")
    assert qs.read_env(env) == {"DOCREADER_DATA_DIR": "/x/data", "A": "b"}
