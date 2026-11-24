"""`scripts/make_search_questions.py` on the database (feature 08; task T026).

The T001 contracts are indexed with `TopicEmbedder`; the extracted fields of feature 05
are written by the test (the extraction needs a language model). Written by the main
session.
"""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

from docreader.runs import start_run
from tests.integration.test_search_scope import index_search_contracts

ROOT = Path(__file__).resolve().parents[2]


def _module(name: str):
    spec = importlib.util.spec_from_file_location(f"{name}_it", ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _field(db, run_id: int, doc: str, field: str, key: str | None, *, sha: str | None = None,
           found: bool = True) -> None:
    current = db.execute(
        "SELECT text_sha256 FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()[0]
    if found:
        db.execute(
            "INSERT INTO field_value (document_id, field, result, value_text, value_normalized,"
            " quote, quote_start, quote_end, clause_key, page, pages, source_text_sha256, run_id)"
            " VALUES (%s, %s, 'found', 'значение', 'значение', 'цитата', 0, 6, %s, 1, '{1}',"
            " %s, %s)",
            (doc, field, key, sha or current, run_id),
        )
    else:
        db.execute(
            "INSERT INTO field_value (document_id, field, result, source_text_sha256, run_id)"
            " VALUES (%s, %s, 'not_found', %s, %s)",
            (doc, field, current, run_id),
        )


def test_question_set_from_fields(cli, db, tmp_path, use_embedder, data_dir, capsys) -> None:
    index_search_contracts(cli, tmp_path, use_embedder)
    preamble = db.execute(
        "SELECT clause_key FROM passage WHERE document_id = 'D-0001' AND part = 'preamble'"
    ).fetchone()[0]
    run_id = start_run(db, "extraction", {})
    _field(db, run_id, "D-0001", "contract_number", preamble)
    _field(db, run_id, "D-0001", "amount_without_vat", "2.1")
    _field(db, run_id, "D-0002", "contract_end_date", "99.9")  # no such passage
    _field(db, run_id, "D-0002", "amount_with_vat", "2.2", sha="0" * 64)  # older text
    _field(db, run_id, "D-0003", "customer_name_short", None, found=False)

    mq = _module("make_search_questions")
    assert mq.main(["--count", "20"]) == 0
    out = capsys.readouterr().out
    target = data_dir / "questions" / "rerank-08.toml"
    data = tomllib.loads(target.read_text(encoding="utf-8"))
    assert sorted((q["answer"], q["source"]) for q in data["question"]) == sorted([
        (f"D-0001/{preamble}", "field:contract_number"),
        ("D-0001/2.1", "field:amount_without_vat"),
    ])
    assert "Записано 2 вопроса" in out and "без актуального отрывка: 2" in out
    for template in mq.TEMPLATES.values():
        assert template not in out  # counts only
    assert "значение" not in out and "цитата" not in out

    # the measurement script reads the set: every answer is a valid clause id
    qs = _module("quickstart_search")
    questions = qs.read_questions(target)
    assert [q.error for q in questions] == [None, None]
    assert {q.source for q in questions} == {"field:contract_number", "field:amount_without_vat"}

    # a second run does not overwrite the analyst's file without --force
    target.write_text(target.read_text(encoding="utf-8") + "# мои вопросы\n", encoding="utf-8")
    assert mq.main(["--count", "20"]) == 1
    assert "# мои вопросы" in target.read_text(encoding="utf-8")
    assert mq.main(["--count", "1", "--force"]) == 0
    assert len(tomllib.loads(target.read_text(encoding="utf-8"))["question"]) == 1


def test_no_found_fields(cli, db, tmp_path, use_embedder, data_dir, capsys) -> None:
    index_search_contracts(cli, tmp_path, use_embedder)
    mq = _module("make_search_questions")
    assert mq.main([]) == 1
    assert "нет найденных полей" in capsys.readouterr().err
    assert not (data_dir / "questions" / "rerank-08.toml").exists()
