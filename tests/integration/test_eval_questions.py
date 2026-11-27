"""`docreader eval questions load|generate|clauses` (feature 02, T033, research R-11)."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from docreader import gold
from docreader.gold import CellValue, GoldPath, GoldState, LoadKind, ParsedGold
from docreader.questions import question_key
from tests.eval_guard import assert_no_values, synthetic_secrets
from tests.synthetic import make_pdfs as mk

SYNTH = Path(__file__).resolve().parents[1] / "synthetic"


@pytest.fixture
def parsed_docs(cli, tmp_path: Path) -> list[str]:  # type: ignore[no-untyped-def]
    """The search contracts of feature 08 (D-0001…D-0003), read and parsed."""
    mk.make_search_contracts(tmp_path / "in")
    assert cli("add", tmp_path / "in").exit_code == 0
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    return ["D-0001", "D-0002", "D-0003"]


def load(cli, *files: object, code: int = 0, extra: tuple[str, ...] = ()) -> dict:  # type: ignore[no-untyped-def,type-arg]
    result = cli("eval", "questions", "load", *files, *extra, "--json")
    assert result.exit_code == code, result.stderr
    return json.loads(result.stdout)


def rows(db) -> dict[str, tuple]:  # type: ignore[no-untyped-def,type-arg]
    return {
        r[0]: r[1:]
        for r in db.execute(
            "SELECT key, document_id, has_answer, clause_keys, origin, source_file, "
            "false_premise, expected FROM gold_question"
        ).fetchall()
    }


def write(data_dir: Path, name: str, body: str) -> Path:
    path = data_dir / "questions" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_feature_08_set_loads_as_is(cli, db, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    report = load(cli, SYNTH / "search_questions.toml", extra=("--origin", "set08"))
    [file] = report["files"]
    assert file["loaded"] == 3
    # «Несуществующий пункт» names a clause that is not in the parse
    assert [e["number"] for e in file["errors"]] == [4]
    got = rows(db)
    key = question_key("D-0002", "Какой срок оплаты?")
    assert got[key][:4] == ("D-0002", True, ["2.2"], "set08")
    assert got[key][4] == "search_questions.toml"


def test_feature_09_set_with_and_without_clauses(cli, db, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    report = load(cli, SYNTH / "answer_questions.toml", extra=("--origin", "set09"))
    [file] = report["files"]
    assert file["loaded"] == 3
    assert [e["number"] for e in file["errors"]] == [4]  # D-0099 is not in the registry
    c = report["composition"]
    assert (c["total"], c["no_answer"], c["no_clause"]) == (3, 1, 2)
    assert any("пункт не указан" in w for w in report["warnings"])


def test_composition_warnings(cli, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    report = load(cli, SYNTH / "search_questions.toml")
    assert any("без ответа меньше 10" in w for w in report["warnings"])
    assert any("ложной посылкой меньше 5" in w for w in report["warnings"])
    c = report["composition"]
    assert (c["text"], c["table"], c["both"], c["false_premise"]) == (3, 0, 0, 0)


def test_reload_replaces_the_questions_of_that_file_only(cli, db, data_dir, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    a = write(data_dir, "a.toml", '[[question]]\ntext = "Первый?"\nanswer = "D-0001/2.1"\n')
    b = write(data_dir, "b.toml", '[[question]]\ntext = "Второй?"\nanswer = "D-0001/2.2"\n')
    load(cli, a, b)
    a.write_text('[[question]]\ntext = "Третий?"\nanswer = "D-0001/2.1"\n', encoding="utf-8")
    report = load(cli, a)
    assert report["files"][0]["replaced"] == 1
    texts = {r[0] for r in db.execute("SELECT text FROM gold_question").fetchall()}
    assert texts == {"Второй?", "Третий?"}
    assert {r[4] for r in rows(db).values()} == {"questions/a.toml", "questions/b.toml"}


def test_same_question_in_two_files_is_one_row(cli, db, data_dir, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    a = write(data_dir, "a.toml", '[[question]]\ntext = "Какой срок?"\nanswer = "D-0001/2.1"\n')
    b = write(data_dir, "b.toml", '[[question]]\ntext = "какой  срок?"\nanswer = "D-0001/2.2"\n')
    load(cli, a)
    report = load(cli, b)
    assert len(rows(db)) == 1
    assert next(iter(rows(db).values()))[2] == ["2.2"]  # the latest file wins
    assert report["conflicts"] == [{"key": question_key("D-0001", "Какой срок?"),
                                    "files": ["questions/a.toml", "questions/b.toml"]}]


def test_origin_from_the_file_wins(cli, db, data_dir, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    path = write(data_dir, "g.toml",
                 'origin = "generated"\n[[question]]\ntext = "Х?"\nanswer = "D-0001/2.1"\n')
    load(cli, path, extra=("--origin", "set08"))
    assert {r[3] for r in rows(db).values()} == {"generated"}


def _gold(db, cells: dict) -> None:  # type: ignore[no-untyped-def,type-arg]
    gold.load(db, ParsedGold(LoadKind.REVIEW, frozenset(cells), cells, [], []),
              file_name="eval/g.json", file_bytes=b"g", yes=True)


def value(text: str, norm: str, clause: str | None) -> CellValue:
    return CellValue(GoldState.VALUE, (text,), (norm,), GoldPath.AGREE, clause, norm)


def test_generate_every_kind(cli, db, data_dir, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    _gold(db, {
        ("D-0001", "amount_with_vat"): value("700 000 рублей", "700000.00", "2.1"),
        ("D-0002", "amount_with_vat"): value("500 000 рублей", "500000.00", "2.2"),
        ("D-0001", "contract_number"): value("ДП-21/2026", "ДП-21/2026", "преамбула"),
        ("D-0003", "contract_number"): value("Х-9", "Х-9", None),  # no clause: no question
        ("D-0002", "advance_share"): CellValue(GoldState.ABSENT, (), (),
                                               GoldPath.ABSENT_MARKED),
    })
    result = cli("eval", "questions", "generate", "--json")
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    path = data_dir / report["path"]
    assert path.parent == data_dir / "questions" and path.suffix == ".toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    assert data["origin"] == "generated"
    qs = data["question"]
    with_answer = [q for q in qs if "answer" in q or "answers" in q]
    plain = [q for q in with_answer if not q.get("false_premise")]
    premise = [q for q in with_answer if q.get("false_premise")]
    none = [q for q in qs if q.get("expected") == "none"]
    assert len(plain) == 3 and report["with_answer"] == 3
    assert {q["answer"] for q in plain} == {"D-0001/2.1", "D-0002/2.2", "D-0001/преамбула"}
    assert [q["document"] for q in none] == ["D-0002"] and report["no_answer"] == 1
    assert len(premise) == 2 and report["false_premise"] == 2
    one = next(q for q in premise if q["answer"] == "D-0001/2.1")
    assert "500 000 рублей" in one["text"]  # the value of another contract
    assert one["contains"] == ["700000.00"]
    assert "Какая цена договора с учётом НДС?" in {q["text"] for q in plain}
    assert_no_values(result.stdout + result.stderr, synthetic_secrets(db))
    # the generated file loads back
    assert load(cli, path)["files"][0]["errors"] == []


def test_generate_never_overwrites(cli, db, data_dir, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    _gold(db, {("D-0001", "amount_with_vat"): value("700 000 рублей", "700000.00", "2.1")})
    target = write(data_dir, "taken.toml", "# keep\n")
    result = cli("eval", "questions", "generate", "--out", target)
    assert result.exit_code == 1
    assert target.read_text(encoding="utf-8") == "# keep\n"


def test_generate_out_outside_the_data_dir_is_refused(cli, db, tmp_path, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    _gold(db, {("D-0001", "amount_with_vat"): value("700 000 рублей", "700000.00", "2.1")})
    target = tmp_path / "elsewhere.toml"
    result = cli("eval", "questions", "generate", "--out", target)
    assert result.exit_code == 1
    assert "только в папку данных" in result.stderr
    assert not target.exists()


def test_clauses_from_the_answers_file(cli, db, data_dir, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    questions = write(data_dir, "answers-09.toml", '''origin = "set09"

[[question]]
text = "Какой срок оплаты?"
document = "D-0002"
expected = "answer"

[[question]]
text = "Какая неустойка?"
document = "D-0001"
expected = "answer"

[[question]]
text = "Предусмотрен ли аванс?"
document = "D-0001"
expected = "none"

[[question]]
text = "Куда переводить деньги?"
answer = "D-0002/2.3"
''')
    answers = write(data_dir, "answers-b4-1.json", json.dumps({
        "format": "docreader-answers-b4/1",
        "questions": [  # a re-run on a part of the questions: other numbers
            {"number": 1, "document": "D-0002", "text": "Какой срок оплаты?",
             "outcome": "answered", "confirmed_clauses": ["D-0002/2.2"]},
            {"number": 2, "document": "D-0001", "text": "Какая неустойка?",
             "outcome": "unconfirmed", "confirmed_clauses": []},
        ],
    }, ensure_ascii=False))
    result = cli("eval", "questions", "clauses", "--answers", answers, "--questions",
                 questions, "--json")
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert (report["without_clause"], report["proposed"], report["no_confirmed"]) == (2, 1, 1)
    out = data_dir / report["path"]
    text = out.read_text(encoding="utf-8")
    assert "пункт из ответа — проверить" in text
    data = tomllib.loads(text)
    assert data["origin"] == "set09"
    assert len(data["question"]) == 4  # the whole source set
    first = data["question"][0]
    assert first["answers"] == ["D-0002/2.2"] and "expected" not in first
    assert data["question"][1]["expected"] == "answer"  # nothing confirmed: left as is
    assert_no_values(result.stdout + result.stderr, synthetic_secrets(db))


def test_clauses_out_refused(cli, db, tmp_path, data_dir, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    questions = write(data_dir, "answers-09.toml", '''origin = "set09"

[[question]]
text = "Какой срок оплаты?"
document = "D-0002"
expected = "answer"
''')
    answers = write(data_dir, "answers-b4-1.json", json.dumps({
        "format": "docreader-answers-b4/1",
        "questions": [
            {"number": 1, "document": "D-0002", "text": "Какой срок оплаты?",
             "outcome": "answered", "confirmed_clauses": ["D-0002/2.2"]},
        ],
    }, ensure_ascii=False))
    target = tmp_path / "elsewhere.toml"
    result = cli("eval", "questions", "clauses", "--answers", answers, "--questions",
                 questions, "--out", target)
    assert result.exit_code == 1
    assert "только в папку данных" in result.stderr
    assert not target.exists()


def test_output_holds_no_question_texts(cli, db, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    for args in ((), ("--json",)):
        result = cli("eval", "questions", "load", SYNTH / "search_questions.toml", *args)
        assert result.exit_code == 0
        assert_no_values(result.stdout + result.stderr,
                         synthetic_secrets(db, extra=["Несуществующий пункт"]))


def test_generate_names_the_no_answer_shortfall(cli, db, parsed_docs) -> None:  # type: ignore[no-untyped-def]
    # converge T052: like the false-premise shortfall, the missing no-answer questions
    _gold(db, {
        ("D-0001", "amount_with_vat"): value("700 000 рублей", "700000.00", "2.1"),
        ("D-0002", "advance_share"): CellValue(GoldState.ABSENT, (), (),
                                               GoldPath.ABSENT_MARKED),
    })
    report = json.loads(cli("eval", "questions", "generate", "--json").stdout)
    assert report["no_answer_shortfall"] == 9  # the set needs ten without an answer
    text = cli("eval", "questions", "generate").stdout
    assert "без ответа 1 (не хватило 9)" in text
