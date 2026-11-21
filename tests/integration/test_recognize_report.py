"""`docreader recognize-report` (US7, FR-018; task T046).

Four documents: D-0001 two clean scans with an engine error on page 2; D-0002 one page
recognised with low confidence; D-0003 a stamp-only page (no text); D-0004 a text PDF,
which has no scans and is not in the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakes.ocr import FailingEngine, TruthEngine
from tests.integration.test_recognize import add, truth_of
from tests.integration.test_recognize_reading import fake_truth
from tests.synthetic import make_pdfs, make_scans

HEADER = [
    "ID", "Имя", "Сканы", "Распозн.", "Ошибки", "Низк. кач.", "Без текста", "Пустые",
    "Ср. оценка", "Время, с", "Состояние",
]


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
    assert cli("recognize", text).exit_code == 0
    return {"clean": clean, "faded": faded, "stamp": stamp, "text": text}


def _json(cli, *args) -> dict:
    result = cli("recognize-report", *args, "--json")
    assert result.exit_code == 0, result.stderr
    return json.loads(result.stdout)


def test_report_per_document_and_totals(cli, recognised) -> None:
    data = _json(cli)

    docs = {d["id"]: d for d in data["documents"]}
    assert set(docs) == {recognised["clean"], recognised["faded"], recognised["stamp"]}
    clean = docs[recognised["clean"]]
    assert (clean["scan_pages"], clean["recognized"], clean["errors"]) == (2, 1, 1)
    assert clean["state"] == "needs_review"
    assert clean["mean_quality"] == pytest.approx(0.99)
    assert clean["seconds"] >= 0
    assert clean["name"] == "f0.pdf"
    faded = docs[recognised["faded"]]
    assert faded["flags"] == {"low_recognition_quality": 1, "scan_no_text": 0, "empty": 0}
    assert faded["state"] == "done"
    stamp = docs[recognised["stamp"]]
    assert stamp["flags"] == {"low_recognition_quality": 0, "scan_no_text": 1, "empty": 0}
    assert stamp["mean_quality"] is None
    totals = data["totals"]
    assert (totals["scan_pages"], totals["recognized"], totals["errors"]) == (4, 3, 1)
    assert totals["flags"] == {"low_recognition_quality": 1, "scan_no_text": 1, "empty": 0}


def test_text_table_has_header_rows_and_totals(cli, recognised) -> None:
    out = cli("recognize-report").stdout.splitlines()

    assert out[0].split("  ")[0] == "ID"
    for word in HEADER:
        assert word in out[0]
    assert out[1].startswith(recognised["clean"])
    assert out[-1].startswith("Итого")
    assert len(out) == 1 + 3 + 1
    assert "0,99" in out[1] and "требует просмотра" in out[1]


def test_review_list_errors_first_then_worst_quality(cli, recognised) -> None:
    pages = _json(cli, "--review")["pages"]

    assert [(p["id"], p["page"], p["code"]) for p in pages] == [
        (recognised["clean"], 2, "recognition_error"),
        (recognised["stamp"], 1, "scan_no_text"),
        (recognised["faded"], 1, "low_recognition_quality"),
    ]
    assert pages[0]["reason"] == "RuntimeError: engine failed"
    assert pages[2]["reason"].startswith("оценка 0,40 < 0,90")
    assert pages[2]["quality"] == pytest.approx(0.40)

    text = cli("recognize-report", "--review").stdout.splitlines()
    assert text[0].startswith(f"{recognised['clean']}  стр. 2  ошибка распознавания")
    assert "текст на скане не найден" in text[1]
    assert "низкое качество распознавания" in text[2]


def test_csv_files(cli, recognised, data_dir: Path) -> None:
    result = cli("recognize-report", "--csv")

    assert result.exit_code == 0
    (path,) = (data_dir / "reports").glob("recognition-2*.csv")
    assert result.stdout.strip() == f"Отчёт сохранён: {path}"
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    rows = raw.decode("utf-8-sig").splitlines()
    assert rows[0].split(";") == HEADER
    assert rows[-1].startswith("Итого;")
    assert "Пдрдчк" not in raw.decode("utf-8-sig")  # no contract text

    review = cli("recognize-report", "--review", "--csv")
    (review_path,) = (data_dir / "reports").glob("recognition-review-*.csv")
    assert review.stdout.strip() == f"Отчёт сохранён: {review_path}"


def test_csv_to_a_given_path(cli, recognised, tmp_path: Path) -> None:
    target = tmp_path / "report.csv"
    result = cli("recognize-report", "--csv", target)
    assert result.exit_code == 0 and target.is_file()


def test_list_and_read_report_show_recognition(cli, recognised) -> None:
    listing = cli("list").stdout.splitlines()
    assert "Распозн." in listing[0]
    assert listing[0].index("Распозн.") < listing[0].index("Чтение")
    assert cli("read").exit_code == 0
    report = cli("read-report", "--json")
    docs = {d["id"]: d for d in json.loads(report.stdout)["documents"]}
    assert docs[recognised["faded"]]["flags"]["low_recognition_quality"] == 1
    assert docs[recognised["stamp"]]["flags"]["scan_no_text"] == 1
    header = cli("read-report").stdout.splitlines()[0]
    assert "Низк. кач." in header and "Без текста" in header


def test_empty_report(cli) -> None:
    result = cli("recognize-report")
    assert result.exit_code == 0
    assert result.stdout.strip() == "Нет документов со страницами-сканами"
