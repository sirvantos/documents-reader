"""`docreader recognize-eval` on synthetic scans (US5, FR-017, research R-12; task T027).

The «verified» texts are the generator's truth, written into a folder inside the test
data folder; one page is recognised with one wrong ИНН digit on purpose.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from docreader.recognition_eval import char_accuracy

from tests.fakes.ocr import TruthEngine
from tests.integration.test_recognize import add, truth_of
from tests.synthetic import make_scans

WRONG_INN = ("ИНН 7701234567", "ИНН 7701234568")


@pytest.fixture
def evaluated(cli, db, data_dir: Path, tmp_path: Path, use_engine):
    """D-0001 clean (exact), D-0002 requisites with one wrong digit; both read."""
    (clean, req), (pdf1, pdf2) = add(
        cli,
        tmp_path / "in",
        make_scans.make_scan_clean,
        make_scans.make_scan_requisites_two_columns,
    )
    truth1, truth2 = truth_of(pdf1), truth_of(pdf2)
    wrong = copy.deepcopy(truth2)
    for line in wrong["pages"][0]["lines"]:
        if line["text"] == WRONG_INN[0]:
            line["text"] = WRONG_INN[1]
    use_engine(TruthEngine(truth1))
    assert cli("recognize", clean).exit_code == 0
    use_engine(TruthEngine(wrong))
    assert cli("recognize", req).exit_code == 0
    assert cli("read").exit_code == 0

    folder = data_dir / "ocr-eval"
    (folder / "pages").mkdir(parents=True)
    for doc, truth in ((clean, truth1), (req, truth2)):
        for page in truth["pages"]:
            text = "\n".join(line["text"] for line in page["lines"])
            (folder / "pages" / f"{doc}-p{page['page']:03d}.txt").write_text(text, encoding="utf-8")
    (folder / "control.csv").write_text(
        "документ;строка;вид\n"
        f"{clean};123/45-У;number\n"
        f"{clean};1 500 000;amount\n"
        f"{req};7701234567;inn\n",
        encoding="utf-8",
    )
    return {"clean": clean, "req": req, "folder": folder, "truth2": truth2}


def _run(cli, folder, *args):
    return cli("recognize-eval", folder, *args)


def test_numbers_on_synthetic_pages(cli, evaluated) -> None:
    result = _run(cli, evaluated["folder"], "--json")

    assert result.exit_code == 0, result.stderr
    data = json.loads(result.stdout)
    pages = {(p["id"], p["page"]): p for p in data["pages"]}
    clean, req = evaluated["clean"], evaluated["req"]
    assert pages[(clean, 1)]["char_accuracy"] == 1.0
    assert pages[(clean, 2)]["char_accuracy"] == 1.0
    expected = "\n".join(line["text"] for line in evaluated["truth2"]["pages"][0]["lines"])
    assert pages[(req, 1)]["char_accuracy"] == pytest.approx(
        char_accuracy(expected, expected.replace(*WRONG_INN))
    )
    assert pages[(req, 1)]["values"]["inn"] == [1, 2]
    assert pages[(req, 1)]["values"]["kpp"] == [2, 2]
    assert pages[(clean, 2)]["values"]["amount"] == [1, 1]
    assert pages[(req, 1)]["missing_lines"] == 0 and pages[(req, 1)]["repeated_lines"] == 0
    for page in pages.values():
        assert isinstance(page["recognition_run_id"], int)
        assert isinstance(page["reading_run_id"], int)
    assert data["totals"]["pages"] == 3 and data["totals"]["documents"] == 2
    assert data["control"]["found"] == 2 and data["control"]["total"] == 3
    assert data["control"]["kinds"]["inn"] == [0, 1]
    assert (data["engine"], data["engine_version"], data["dpi"]) == ("truth", "1", 300)
    assert data["settings"]["recognition"]["page_min_quality"] == 0.8
    assert data["flags"] is None
    assert data["not_recognized"] == []


def test_report_files_keep_run_ids_and_settings_but_csv_has_no_text(
    cli, evaluated, data_dir: Path
) -> None:
    result = _run(cli, evaluated["folder"], "--label", "проба")

    assert result.exit_code == 0
    (report,) = (data_dir / "reports").glob("recognition-eval-*.json")
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["label"] == "проба"
    assert {"recognition_run_id", "reading_run_id"} <= set(saved["pages"][0])
    assert saved["control"]["missing"] == [
        {"id": evaluated["req"], "string": "7701234567", "kind": "inn"}
    ]
    (table,) = (data_dir / "reports").glob("recognition-eval-*.csv")
    csv_text = table.read_text(encoding="utf-8-sig")
    assert "ООО" not in csv_text and "ИНН" not in csv_text
    assert f"Результат сохранён: {report}" in result.stdout


def test_terminal_shows_numbers_only_unless_diff(cli, evaluated) -> None:
    plain = _run(cli, evaluated["folder"]).stdout
    assert "Верных знаков:" in plain and "Контрольные строки: 66,7% (2 из 3)" in plain
    assert "7701234568" not in plain and "ООО" not in plain

    with_diff = _run(cli, evaluated["folder"], "--diff").stdout
    assert "7701234568" in with_diff


def test_folder_outside_the_data_folder_is_refused(cli, evaluated, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    result = _run(cli, outside)

    assert result.exit_code == 1
    assert "Папка замера должна лежать в папке данных" in result.stderr


def test_bad_control_row_names_file_and_line(cli, evaluated) -> None:
    (evaluated["folder"] / "control.csv").write_text(
        "документ;строка;вид\nD-0001;только два поля\n", encoding="utf-8"
    )

    result = _run(cli, evaluated["folder"])

    assert result.exit_code == 1
    assert "control.csv" in result.stderr and "строка 2" in result.stderr


def test_unknown_page_is_a_user_error(cli, evaluated) -> None:
    (evaluated["folder"] / "pages" / "D-0001-p009.txt").write_text("x", encoding="utf-8")

    result = _run(cli, evaluated["folder"])

    assert result.exit_code == 1
    assert "D-0001-p009.txt" in result.stderr


def test_page_without_recognition_is_listed_not_counted(cli, db, evaluated) -> None:
    db.execute(
        "DELETE FROM page_recognition WHERE document_id = %s AND page_number = 2",
        (evaluated["clean"],),
    )

    data = json.loads(_run(cli, evaluated["folder"], "--json").stdout)

    assert data["not_recognized"] == [{"id": evaluated["clean"], "page": 2}]
    assert data["totals"]["pages"] == 2
