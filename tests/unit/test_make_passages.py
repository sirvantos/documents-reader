"""Tests of the synthetic passage contract (feature 07, task T003).

The generator writes only under pytest tmp_path.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

from tests.synthetic.make_pdfs import _PASSAGE_PAGES, make_passage_contract


def _pages_text(path: Path) -> list[str]:
    document = pdfium.PdfDocument(str(path))
    try:
        return [
            " ".join(str(document[i].get_textpage().get_text_range()).split())
            for i in range(len(document))
        ]
    finally:
        document.close()


def test_writes_three_page_pdf(tmp_path: Path) -> None:
    path = make_passage_contract(tmp_path / "passage.pdf")
    assert path == tmp_path / "passage.pdf"
    assert path.is_file()
    assert len(_pages_text(path)) == 3


def test_each_page_holds_its_lines(tmp_path: Path) -> None:
    path = make_passage_contract(tmp_path / "passage.pdf")
    texts = _pages_text(path)
    assert len(texts) == len(_PASSAGE_PAGES) == 3
    for text, page in zip(texts, _PASSAGE_PAGES, strict=True):
        for line in page:
            assert " ".join(line.split()) in text, line


def test_first_page_starts_with_title(tmp_path: Path) -> None:
    path = make_passage_contract(tmp_path / "passage.pdf")
    assert _pages_text(path)[0].startswith("ДОГОВОР ПОДРЯДА")


def test_writes_only_under_given_path(tmp_path: Path) -> None:
    make_passage_contract(tmp_path / "passage.pdf")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["passage.pdf"]
