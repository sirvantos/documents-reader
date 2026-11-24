"""Integration tests for `docreader index` (feature 07; task T016).

Everything goes through `add`, `read`, `parse` and `index` on the synthetic contracts of
`make_passage_contract` and `make_extraction_contract("base")`; the search model is a
fake transport (`tests/fakes/embedding.py`) installed with `use_embedder`. Written by
the main session; the implementer must not edit, weaken, skip or delete these tests
(CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import json
import math
from functools import partial

import pytest

from docreader.extraction_text import shown_end
from docreader.passages import ClauseRecord, coverage, cut, label
from docreader.wordforms import lemmatize
from tests.fakes.embedding import DownEmbedder, FailingEmbedder, HashEmbedder
from tests.integration.test_read import add_files, stage
from tests.synthetic import make_pdfs as mk

NOTHING = "Нечего индексировать: индексы всех договоров построены (заново: docreader index --all)"
FORBIDDEN = "На этой машине модель поиска не запускается (DOCREADER_FORBID_MODELS)"
DOWN = (
    "Модель поиска недоступна по адресу http://127.0.0.1:8081/v1 — "
    "запустите сервер модели поиска"
)


def index_json(cli, *args, code: int = 0) -> dict:
    result = cli("index", *args, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout)


def _text(db, doc: str) -> str:
    return db.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()[0]


def _records(db, doc: str) -> list[ClauseRecord]:
    return [
        ClauseRecord(*row)
        for row in db.execute(
            "SELECT key, kind, depth, start, end_, section_number, section_title FROM clause"
            " WHERE document_id = %s ORDER BY ordinal",
            (doc,),
        )
    ]


def _passages(db, doc: str) -> dict[str, dict]:
    cur = db.execute(
        "SELECT clause_key, ordinal, part, start, end_, first_page, last_page, label, lemmas,"
        " source_text_sha256, structure_run_id, run_id FROM passage WHERE document_id = %s"
        " ORDER BY ordinal",
        (doc,),
    )
    names = [c.name for c in cur.description]
    return {r[0]: dict(zip(names, r, strict=True)) for r in cur.fetchall()}


def _vectors(db, doc: str) -> dict[str, tuple]:
    return {
        r[0]: r[1:]
        for r in db.execute(
            "SELECT clause_key, model, dims, embedding::text, truncated, input_chars"
            " FROM passage_vector WHERE document_id = %s",
            (doc,),
        )
    }


def _page_of(db, doc: str, offset: int) -> int:
    return db.execute(
        "SELECT page_number FROM text_span WHERE document_id = %s AND start <= %s"
        " ORDER BY start DESC LIMIT 1",
        (doc, offset),
    ).fetchone()[0]


@pytest.fixture
def two(cli, tmp_path) -> list[str]:
    makers = [mk.make_passage_contract, partial(mk.make_extraction_contract, variant="base")]
    ids = add_files(cli, tmp_path / "in", makers)
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    return ids


# --- the passages and both indexes -------------------------------------------------------


def test_index_builds_passages_and_both_indexes(cli, db, two, use_embedder) -> None:
    fake = use_embedder(HashEmbedder())
    report = index_json(cli)
    passage_doc = two[0]
    assert [d["document_id"] for d in report["documents"]] == two
    assert all(d["state"] == "done" and d["reason"] is None for d in report["documents"])

    text = _text(db, passage_doc)
    rows = _passages(db, passage_doc)
    assert {k: text[r["start"]:r["end_"]] for k, r in rows.items()} == mk.PASSAGE_TRUTH

    records = {r.key: r for r in _records(db, passage_doc)}
    sha = db.execute("SELECT text_sha256 FROM document_text WHERE document_id = %s",
                     (passage_doc,)).fetchone()[0]
    srun = db.execute("SELECT DISTINCT run_id FROM clause WHERE document_id = %s",
                      (passage_doc,)).fetchone()[0]
    for key, row in rows.items():
        passage_text = text[row["start"]:row["end_"]]
        assert row["label"] == label(passage_doc, records[key])
        assert row["lemmas"] == lemmatize(row["label"] + "\n" + passage_text)
        assert row["first_page"] == _page_of(db, passage_doc, row["start"])
        assert row["last_page"] == _page_of(db, passage_doc, row["end_"] - 1)
        assert (row["source_text_sha256"], row["structure_run_id"]) == (sha, srun)
        assert row["run_id"] == report["run_id"]
    assert [r["part"] for r in rows.values()] == ["preamble"] + ["main"] * 7 + ["tail"]

    vectors = _vectors(db, passage_doc)
    assert set(vectors) == set(rows)
    for key, (model, dims, emb, truncated, chars) in vectors.items():
        values = json.loads(emb)
        assert (model, dims, truncated) == ("bge-m3", 8, False)
        assert math.isclose(math.sqrt(sum(x * x for x in values)), 1.0, rel_tol=1e-6)
        assert chars == len(rows[key]["label"]) + 1 + rows[key]["end_"] - rows[key]["start"]

    # what went to the model: the probe of check(), then label + "\n" + text, in order
    sent = fake.inputs[1:]
    expected = [
        r["label"] + "\n" + _text(db, doc)[r["start"]:r["end_"]]
        for doc in two
        for r in _passages(db, doc).values()
    ]
    assert sent == expected

    for doc in two:
        text = _text(db, doc)
        records = _records(db, doc)
        tail = next(r for r in records if r.kind == "tail")
        tail_end = shown_end(text, tail.start)
        assert coverage(text, records, tail_end, cut(text, records, tail_end)) == (0, 0)
        assert len(_passages(db, doc)) == len(_vectors(db, doc))


def test_word_index_finds_forms_and_whole_numbers(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    index_json(cli)
    passage_doc = two[0]

    def found(query: str, fn: str = "to_tsquery") -> list[str]:
        return [
            r[0] for r in db.execute(
                f"SELECT clause_key FROM passage WHERE document_id = %s"
                f" AND tsv @@ {fn}('simple', %s) ORDER BY ordinal",
                (passage_doc, query),
            )
        ]

    assert found("неустойка") == ["3.1", "3.2"]
    preamble = _passages(db, passage_doc)["преамбула"]
    assert "ДП-17/2026" in preamble["lemmas"].split()
    assert found("ДП-17/2026", "plainto_tsquery") == ["преамбула"]


def test_run_record(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder(served_model="bge-m3-Q8_0.gguf"))
    report = index_json(cli, "--label", "проба")
    assert (report["model"], report["served_model"], report["dims"]) == (
        "bge-m3", "bge-m3-Q8_0.gguf", 8
    )
    stage_name, model, settings, run_label = db.execute(
        "SELECT stage, model, settings, label FROM run WHERE id = %s", (report["run_id"],)
    ).fetchone()
    assert (stage_name, model, run_label) == ("indexing", "bge-m3", "проба")
    assert settings["served_model"] == "bge-m3-Q8_0.gguf"
    assert settings["dims"] == 8
    assert settings["embedding"]["max_chars"] == 16000
    for doc in two:
        assert stage(db, doc, "indexing")[:3] == ("done", None, report["run_id"])


def test_json_counts(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    report = index_json(cli)
    for doc in report["documents"]:
        n = len(_passages(db, doc["document_id"]))
        assert (doc["passages"], doc["word_entries"], doc["vectors"], doc["truncated"]) == (
            n, n, n, 0
        )
        assert doc["seconds"] >= 0
    assert report["totals"] == {
        "indexed": 2, "needs_review": 0, "failed": 0, "skipped": 0,
        "passages": sum(d["passages"] for d in report["documents"]),
    }
    assert (report["interrupted"], report["stopped"], report["skipped"]) == (False, None, [])


# --- the choice of documents ---------------------------------------------------------------


def test_without_arguments_only_pending_and_failed(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    first, second = two
    index_json(cli, first)
    report = index_json(cli)
    assert [d["document_id"] for d in report["documents"]] == [second]
    result = cli("index")
    assert result.exit_code == 0
    assert result.stdout.strip() == NOTHING


def test_all_and_explicit_ids(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    index_json(cli)
    assert [d["document_id"] for d in index_json(cli, "--all")["documents"]] == two
    assert [d["document_id"] for d in index_json(cli, two[1])["documents"]] == [two[1]]
    result = cli("index", two[0], "--all")
    assert result.exit_code == 1


def test_second_run_keeps_the_counts(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    index_json(cli)
    counts = {doc: (len(_passages(db, doc)), len(_vectors(db, doc))) for doc in two}
    index_json(cli, "--all")
    assert {doc: (len(_passages(db, doc)), len(_vectors(db, doc))) for doc in two} == counts
    total = db.execute("SELECT count(*) FROM passage").fetchone()[0]
    assert total == sum(c[0] for c in counts.values())


def test_a_second_parse_is_taken_again(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    index_json(cli)
    assert cli("parse", two[0]).exit_code == 0
    report = index_json(cli)
    assert [d["document_id"] for d in report["documents"]] == [two[0]]


def test_unparsed_and_stale_parse_are_skipped(cli, db, two, tmp_path, use_embedder) -> None:
    use_embedder(HashEmbedder())
    (third,) = add_files(cli, tmp_path / "more", [mk.make_structured_contract])
    assert cli("read", third).exit_code == 0
    db.execute("UPDATE document_text SET text_sha256 = %s WHERE document_id = %s",
               ("d" * 64, two[1]))
    report = index_json(cli, third, two[1], two[0])
    assert [d["document_id"] for d in report["documents"]] == [two[0]]
    assert report["skipped"] == [
        {"document_id": third, "reason": f"не разобран — выполните docreader parse {third}"},
        {"document_id": two[1], "reason": f"разбор устарел — выполните docreader parse {two[1]}"},
    ]
    text = cli("index", third).stdout
    assert f"{third}  пропущен" in text


# --- states --------------------------------------------------------------------------------


def test_truncated_input_needs_review(cli, db, two, data_dir, use_embedder) -> None:
    (data_dir / "settings.toml").write_text("[embedding]\nmax_chars = 60\n", "utf-8")
    fake = use_embedder(HashEmbedder())
    report = index_json(cli, two[0])
    (doc,) = report["documents"]
    assert doc["state"] == "needs_review"
    assert doc["reason"].startswith(f"отрывок длиннее предела модели: {two[0]}/")
    assert doc["truncated"] > 0
    assert all(len(t) <= 60 for t in fake.inputs)
    truncated = {k for k, v in _vectors(db, two[0]).items() if v[3]}
    assert len(truncated) == doc["truncated"]
    assert all(v[4] == 60 for k, v in _vectors(db, two[0]).items() if k in truncated)
    assert stage(db, two[0], "indexing")[:2] == ("needs_review", doc["reason"])


def test_a_model_error_fails_one_document(cli, db, two, use_embedder) -> None:
    first, second = two
    use_embedder(HashEmbedder())
    index_json(cli, first)
    before = _passages(db, first)
    use_embedder(FailingEmbedder("неустойку", "http_500"))  # only in the passage contract
    report = index_json(cli, "--all")
    states = {d["document_id"]: (d["state"], d["reason"]) for d in report["documents"]}
    assert states[first] == ("failed", "ошибка построения векторов: EmbeddingRequestError")
    assert states[second] == ("done", None)
    assert _passages(db, first) == before
    assert stage(db, first, "indexing")[:2] == states[first]


def test_server_down_before_the_run(cli, db, two, use_embedder) -> None:
    use_embedder(DownEmbedder())
    result = cli("index")
    assert result.exit_code == 2
    assert DOWN in result.stderr
    for doc in two:
        assert stage(db, doc, "indexing")[0] == "pending"
    assert db.execute("SELECT count(*) FROM passage").fetchone()[0] == 0


def test_server_lost_on_the_second_document(cli, db, two, use_embedder) -> None:
    first, second = two
    # «ДП-17/2026» is in both; «Предмет договора» only in the base contract (second)
    use_embedder(FailingEmbedder("Обеспечение исполнения", "connect"))
    report = index_json(cli, code=2)
    assert [d["document_id"] for d in report["documents"]] == [first]
    assert report["stopped"]["document_id"] == second
    assert "модель поиска" in report["stopped"]["reason"]
    assert stage(db, first, "indexing")[0] == "done"
    assert stage(db, second, "indexing")[0] == "pending"
    assert _passages(db, second) == {}


def test_forbidden_without_a_fake(cli, db, two) -> None:
    result = cli("index")
    assert result.exit_code == 2
    assert FORBIDDEN in result.stderr
    assert stage(db, two[0], "indexing")[0] == "pending"


def test_removing_a_document_removes_its_passages(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    index_json(cli)
    assert cli("remove", two[0], "--yes").exit_code == 0
    for table in ("passage", "passage_vector"):
        n = db.execute(
            f"SELECT count(*) FROM {table} WHERE document_id = %s", (two[0],)
        ).fetchone()[0]
        assert n == 0
    assert len(_passages(db, two[1])) > 0


def test_output_holds_no_label_and_no_contract_text(cli, db, two, use_embedder) -> None:
    use_embedder(HashEmbedder())
    text_out = cli("index").stdout
    json_out = cli("index", "--all", "--json").stdout
    lines = [line for page in mk._PASSAGE_PAGES for line in page]
    for out in (text_out, json_out):
        for line in lines:
            if len(line) > 8:
                assert line not in out, line
        assert "Ответственность" not in out and " · " not in out
