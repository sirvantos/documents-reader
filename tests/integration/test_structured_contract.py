"""Integration test: the structured contract of feature 04 (task T001) is read through the CLI.

The generator is in `tests/synthetic/make_pdfs.py`; the expected lines come from its
constants, nothing is copied here. Everything goes through `add` and `read` and the database.
"""

from __future__ import annotations

from pathlib import Path

from tests.integration.test_read import add_files, flags_of, page_rows, stage
from tests.synthetic import make_pdfs as mk


def test_structured_contract_is_read_with_lines_table_and_scan_page(cli, db, tmp_path: Path):
    (doc,) = add_files(cli, tmp_path / "in", [mk.make_structured_contract])

    result = cli("read", doc)

    assert result.exit_code == 0, result.stderr

    # 5 pages, page 3 is a picture without text and is flagged as an unread scan.
    rows = page_rows(db, doc)
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]
    assert flags_of(db, doc) == {3: {"scan_unread"}}
    assert stage(db, doc)[0] == "needs_review"

    # Every plain line of every text page is in the document text, in page order.
    (text,) = db.execute("SELECT text FROM document_text WHERE document_id = %s", (doc,)).fetchone()
    position = 0
    for page_no, expected in enumerate(mk.STRUCTURED_CONTRACT_PAGES, start=1):
        if expected is None:
            continue
        for line in expected:
            found = text.find(line, position)
            assert found >= 0, f"page {page_no}: line not found in order: {line!r}"
            position = found + len(line)

    # The table rows of page 2 are stored as table cells.
    lines_page2 = next(r[4] for r in rows if r[0] == 2)
    table_texts = [ln["text"] for ln in lines_page2 if ln["table"] is not None]
    for row in mk.STRUCTURED_CONTRACT_TABLE:
        for cell in row:
            assert cell in table_texts, f"table cell not marked as table: {cell!r}"

    # The glued clause number starts its own line of the text.
    assert "\n2.2Оплата производится по счёту." in text
