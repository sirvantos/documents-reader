"""`recognition_report` / `recognition_review` called directly (task T047)."""

from __future__ import annotations

from pathlib import Path

import pytest

from docreader.config import Settings
from docreader.textview import recognition_report, recognition_review
from tests.fakes.ocr import FailingEngine, TruthEngine
from tests.integration.test_recognize import add, truth_of
from tests.integration.test_recognize_reading import fake_truth
from tests.synthetic import make_pdfs, make_scans


@pytest.fixture
def recognised(cli, tmp_path: Path, use_engine) -> dict:
    (clean, faded, stamp, text), (pdf1, _, _, _) = add(
        cli,
        tmp_path / "in",
        make_scans.make_scan_clean,
        lambda p: make_scans.make_scan_clean(p, pages=1),
        make_scans.make_scan_stamp_only,
        make_pdfs.make_contract_ru,
    )
    use_engine(FailingEngine({2}, TruthEngine(truth_of(pdf1))))
    assert cli("recognize", clean).exit_code == 0
    use_engine(TruthEngine(fake_truth([("Пдрдчк бзтс вплнть", 700.0, 0.40)])))
    assert cli("recognize", faded).exit_code == 0
    use_engine(TruthEngine({"pages": [{"page": 1, "kind": "scan", "lines": []}]}))
    assert cli("recognize", stamp).exit_code == 0
    return {"clean": clean, "faded": faded, "stamp": stamp, "text": text}


@pytest.fixture
def settings(data_dir: Path, database_url: str) -> Settings:
    return Settings(data_dir=data_dir, database_url=database_url)


def test_report(db, settings, recognised) -> None:
    report = recognition_report(db, settings)

    docs = {d.id: d for d in report.documents}
    assert list(docs) == [recognised["clean"], recognised["faded"], recognised["stamp"]]
    clean = docs[recognised["clean"]]
    assert (clean.scan_pages, clean.recognized, clean.errors) == (2, 1, 1)
    assert clean.state == "needs_review"
    assert clean.mean_quality == pytest.approx(0.99)
    assert docs[recognised["faded"]].flags == {
        "low_recognition_quality": 1, "scan_no_text": 0, "empty": 0,
    }
    assert docs[recognised["stamp"]].mean_quality is None
    assert docs[recognised["stamp"]].flags["scan_no_text"] == 1
    totals = report.totals
    assert (totals.scan_pages, totals.recognized, totals.errors) == (4, 3, 1)
    assert totals.flags == {"low_recognition_quality": 1, "scan_no_text": 1, "empty": 0}
    data = report.to_json()
    assert set(data) == {"documents", "totals"}
    assert data["documents"][0]["name"] == "f0.pdf"


def test_review_order(db, settings, recognised) -> None:
    pages = recognition_review(db, settings)

    assert [(p.id, p.page, p.code) for p in pages] == [
        (recognised["clean"], 2, "recognition_error"),
        (recognised["stamp"], 1, "scan_no_text"),
        (recognised["faded"], 1, "low_recognition_quality"),
    ]
    assert pages[0].reason == "RuntimeError: engine failed" and pages[0].quality is None
    assert pages[2].quality == pytest.approx(0.40)


def test_empty(db, settings) -> None:
    report = recognition_report(db, settings)
    assert report.documents == [] and report.totals.scan_pages == 0
    assert recognition_review(db, settings) == []
