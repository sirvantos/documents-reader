"""`show` and `text --page` tell that a page was recognised (US1-4; task T018)."""

from __future__ import annotations

import json
import re

from tests.fakes.ocr import FailingEngine, TruthEngine
from tests.integration.test_recognize import add, truth_of
from tests.synthetic import make_pdfs, make_scans


def test_show_lists_recognition_stage_and_page_facts(cli, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")

    result = cli("show", doc)

    assert result.exit_code == 0
    assert "  Распознавание: готово" in result.stdout
    page_lines = [ln for ln in result.stdout.splitlines() if ln.startswith("  1  ")]
    assert len(page_lines) == 1
    assert re.search(
        r"распознано truth 1, 300 dpi, \d{4}-\d{2}-\d{2} \d{2}:\d{2}, оценка 0,99", page_lines[0]
    )


def test_show_names_a_recognition_error(cli, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(FailingEngine({2}, TruthEngine(truth_of(pdf))))
    cli("recognize")

    out = cli("show", doc).stdout

    page2 = next(ln for ln in out.splitlines() if ln.startswith("  2  "))
    assert "ошибка распознавания: RuntimeError: engine failed" in page2


def test_show_json_has_recognition_or_null(cli, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_mixed)
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")

    data = json.loads(cli("show", doc, "--json").stdout)

    recognitions = {p["page_number"]: p["recognition"] for p in data["pages"]}
    assert recognitions[1] is None and recognitions[3] is None
    rec = recognitions[2]
    assert set(rec) == {
        "engine",
        "engine_version",
        "dpi",
        "turn",
        "quality",
        "ink_share",
        "recognized_at",
        "run_id",
        "error",
    }
    assert (rec["engine"], rec["engine_version"], rec["dpi"], rec["error"]) == (
        "truth",
        "1",
        300,
        None,
    )
    assert data["stages"]["recognition"]["state"] == "done"


def test_text_page_shows_the_source_and_confidence(cli, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_mixed)
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")
    assert cli("read", doc).exit_code == 0

    scan = cli("text", doc, "--page", "2").stdout
    text = cli("text", doc, "--page", "1").stdout

    assert "Источник: распознано (truth 1, оценка 0,99)" in scan
    assert "0,99" in scan.split("Источник:")[1].splitlines()[1]  # first line row
    assert "Источник: текстовый слой PDF" in text

    data = json.loads(cli("text", doc, "--page", "2", "--json").stdout)
    (page,) = data["pages"]
    assert page["source"] == "recognized"
    assert all(line["confidence"] == 0.99 for line in page["lines"])
    text_page = json.loads(cli("text", doc, "--page", "1", "--json").stdout)["pages"][0]
    assert text_page["source"] == "pdf"
    assert all("confidence" not in line for line in text_page["lines"])


def test_text_page_of_a_text_pdf_is_unchanged_but_names_its_source(cli, tmp_path) -> None:
    (doc,), _ = add(cli, tmp_path / "in", make_pdfs.make_contract_ru)
    cli("read", doc)

    out = cli("text", doc, "--page", "1").stdout

    assert "Источник: текстовый слой PDF" in out
