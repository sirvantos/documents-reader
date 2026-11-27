"""`docreader eval search`: the search measurement on gold questions (feature 02, T035).

research.md R-12; the same calls as `scripts/quickstart_search.py`, so the places equal
the measurement of feature 08 on the same set (SC-007).
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from docreader.questions import question_key
from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.fakes.reranker import TableReranker
from tests.integration.test_search import _measurement_module
from tests.integration.test_search_scope import index_search_contracts

SYNTH = Path(__file__).resolve().parents[1] / "synthetic"
SCORES = {"перечисл": 9.0, "неустойк": 7.0, "30 дней": 5.0}


@pytest.fixture
def indexed(cli, tmp_path, use_embedder, use_reranker):  # type: ignore[no-untyped-def]
    ids, _ = index_search_contracts(cli, tmp_path, use_embedder)
    use_reranker(TableReranker(SCORES))
    extra = tmp_path / "extra.toml"
    extra.write_text(
        '[[question]]\ntext = "Предусмотрен ли аванс?"\ndocument = "D-0001"\n'
        'expected = "none"\n\n'
        '[[question]]\ntext = "Таблица цен?"\nanswer = "D-0001/2.1"\nkind = "table"\n',
        encoding="utf-8",
    )
    for path in (SYNTH / "search_questions.toml", extra):
        result = cli("eval", "questions", "load", path)
        assert result.exit_code == 0, result.stderr
    return ids


def measure(cli, *args: object, code: int = 0) -> dict:  # type: ignore[no-untyped-def,type-arg]
    result = cli("eval", "search", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout) if code == 0 else {}


def places(db, record: int) -> dict[str, int | None]:  # type: ignore[no-untyped-def]
    return dict(db.execute(
        "SELECT case_key, place FROM eval_case WHERE result_id = %s AND NOT "
        "('excluded' = ANY(flags))",
        (record,),
    ).fetchall())


def test_two_records_with_one_label(cli, db, indexed) -> None:  # type: ignore[no-untyped-def]
    report = measure(cli, "--label", "после 02")
    plain, rerank = report["records"]["search_plain"], report["records"]["search_rerank"]
    stages = dict(db.execute(
        "SELECT id, stage FROM eval_result WHERE label = 'после 02'").fetchall())
    assert stages == {plain: "search_plain", rerank: "search_rerank"}
    pay = question_key("D-0002", "Какой срок оплаты?")
    assert places(db, rerank)[pay] == 2
    assert places(db, rerank)[question_key("D-0002", "Куда переводить деньги?")] == 1
    assert places(db, plain)[question_key("D-0001", "Какая неустойка за просрочку?")] == 1


def test_places_equal_the_feature_08_measurement(cli, db, tmp_path, indexed, capsys) -> None:  # type: ignore[no-untyped-def]
    report = measure(cli)
    questions = tmp_path / "q" / "set.toml"
    questions.parent.mkdir()
    questions.write_text((SYNTH / "search_questions.toml").read_text(encoding="utf-8"),
                         encoding="utf-8")
    assert _measurement_module().main(["--questions", str(questions), "--json"]) == 0
    data = json.loads(capsys.readouterr().out.split("\nСводка сохранена:")[0])
    texts = {1: "Какой срок оплаты?", 2: "Куда переводить деньги?",
             3: "Какая неустойка за просрочку?"}
    plain = places(db, report["records"]["search_plain"])
    rerank = places(db, report["records"]["search_rerank"])
    for row in data["rows"]:
        if row.get("error"):
            continue
        doc = row["answer"].split("/")[0]
        key = question_key(doc, texts[row["number"]])
        assert (plain[key], rerank[key]) == (row["place_off"], row["place_on"])  # SC-007


def test_metrics_and_excluded_questions(cli, db, indexed) -> None:  # type: ignore[no-untyped-def]
    report = measure(cli)
    variant = report["variants"]["search_rerank"]
    assert variant["participating"] == 3
    assert variant["excluded"] == 2  # no answer, kind «table»
    assert variant["first"] == 2 and variant["top5"] == 3
    excluded = db.execute(
        "SELECT count(*) FROM eval_case WHERE result_id = %s AND 'excluded' = ANY(flags)",
        (report["records"]["search_rerank"],),
    ).fetchone()[0]
    assert excluded == 2


def test_show_by_search_outcome(cli, indexed) -> None:  # type: ignore[no-untyped-def]
    record = measure(cli)["records"]["search_rerank"]
    for outcome, count in (("first", 2), ("top5", 3), ("found", 3), ("not_found", 0),
                           ("excluded", 2)):
        result = cli("eval", "show", record, "--outcome", outcome, "--json")
        assert result.exit_code == 0, result.stderr
        assert len(json.loads(result.stdout)["cases"]) == count, outcome


def test_results_from_a_file_need_no_models(cli, db, data_dir, indexed, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    pay = question_key("D-0002", "Какой срок оплаты?")
    path = data_dir / "eval" / "search-results.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({
        "format": "docreader-search-results/1", "source": "синтетика",
        "variants": {"search_plain": {pay: ["D-0002/2.3", "D-0002/2.2"]},
                     "search_rerank": {pay: ["D-0002/2.2"]}},
    }), encoding="utf-8")
    from docreader import embedding, reranker

    monkeypatch.setattr(embedding, "load_embedder", lambda *_: pytest.fail("model used"))
    monkeypatch.setattr(reranker, "load_reranker", lambda *_: pytest.fail("model used"))
    report = measure(cli, "--from", path)
    assert places(db, report["records"]["search_plain"])[pay] == 2
    assert places(db, report["records"]["search_rerank"])[pay] == 1
    row = db.execute("SELECT from_file FROM eval_result WHERE id = %s",
                     (report["records"]["search_plain"],)).fetchone()
    assert row[0] == "eval/search-results.json"


def test_forbidden_models_stop_before_the_first_question(cli, db, tmp_path, use_embedder) -> None:  # type: ignore[no-untyped-def]
    index_search_contracts(cli, tmp_path, use_embedder)
    assert cli("eval", "questions", "load", SYNTH / "search_questions.toml").exit_code == 0
    # no reranker fake installed: DOCREADER_FORBID_MODELS stops it
    result = cli("eval", "search")
    assert result.exit_code == 2
    assert db.execute("SELECT count(*) FROM eval_result").fetchone()[0] == 0


def test_no_questions_is_a_user_error(cli, tmp_path, use_embedder, use_reranker) -> None:  # type: ignore[no-untyped-def]
    index_search_contracts(cli, tmp_path, use_embedder)
    use_reranker(TableReranker(SCORES))
    result = cli("eval", "search")
    assert result.exit_code == 1
    assert "вопрос" in result.stderr


def test_review_file(cli, data_dir, indexed) -> None:  # type: ignore[no-untyped-def]
    report = measure(cli)
    raw = (data_dir / report["review_file"]).read_bytes()
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))
    assert {"question_key", "document_id", "question", "correct_clauses", "place_plain",
            "place_rerank", "top5_plain", "top5_rerank"} <= set(rows[0])
    assert any(r["question"] == "Какой срок оплаты?" for r in rows)


def test_output_holds_no_question_texts(cli, db, indexed) -> None:  # type: ignore[no-untyped-def]
    secrets = synthetic_secrets(db)
    for extra in ((), ("--json",)):
        result = cli("eval", "search", *extra)
        assert result.exit_code == 0, result.stderr
        assert_no_values(result.stdout + result.stderr, secrets)


def test_search_provenance_holds_the_reranker_settings(cli, db, indexed) -> None:  # type: ignore[no-untyped-def]
    # converge T053 (research R-13)
    report = measure(cli)
    [prov] = db.execute(
        "SELECT provenance FROM eval_result WHERE id = %s", (report["records"]["search_plain"],)
    ).fetchone()
    assert set(prov["reranker_settings"]) >= {"enabled", "model", "max_chars"}


def test_text_parts_add_up_to_the_questions(cli, db, indexed) -> None:  # type: ignore[no-untyped-def]
    # converge T052 (US5/AC7, SC-011): the «пункт не указан» questions are counted too
    import re

    result = cli("eval", "search")
    assert result.exit_code == 0, result.stderr
    m = re.search(
        r"вопросов (\d+): участвуют (\d+), без ответа (\d+), вида «таблица» (\d+), "
        r"пункт не указан (\d+)", result.stdout,
    )
    assert m, result.stdout
    total, *parts = map(int, m.groups())
    assert total == sum(parts)
    assert json.loads(cli("eval", "search", "--json").stdout)["unspecified"] == parts[3]
