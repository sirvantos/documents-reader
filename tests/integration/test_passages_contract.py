"""The cutting rule on the synthetic passage contract after add, read, parse (T009).

`PASSAGE_TRUTH` (tests/synthetic/make_pdfs.py) is the expected result of the rule on
`make_passage_contract`. Written by the main session; the implementer must not edit,
weaken, skip or delete this test.
"""

from __future__ import annotations

from docreader.extraction_text import shown_end
from docreader.passages import ClauseRecord, coverage, cut
from tests.integration.test_read import add_files
from tests.synthetic import make_pdfs as mk


def test_cut_on_the_passage_contract_gives_the_truth(cli, db, tmp_path) -> None:
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_passage_contract])
    assert cli("read").exit_code == 0
    assert cli("parse").exit_code == 0
    (text,) = db.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()
    records = [
        ClauseRecord(*row)
        for row in db.execute(
            "SELECT key, kind, depth, start, end_, section_number, section_title FROM clause"
            " WHERE document_id = %s ORDER BY ordinal",
            (doc,),
        )
    ]
    tail = next(r for r in records if r.kind == "tail")
    tail_end = shown_end(text, tail.start)
    spans = cut(text, records, tail_end)
    assert {s.key: text[s.start:s.end] for s in spans} == mk.PASSAGE_TRUTH
    assert coverage(text, records, tail_end, spans) == (0, 0)
