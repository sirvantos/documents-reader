"""Reading takes the recognised lines of scan pages (US2, US3; task T017).

Recognition runs with fakes (tests/fakes/ocr.py), then `read` turns the stored lines
into page text through the same path as PDF text (FR-009). No real engine anywhere.
"""

from __future__ import annotations

import json

import pytest

from docreader import textnorm
from tests.fakes.ocr import TruthEngine
from tests.integration.test_recognize import add, rows, stage, truth_of
from tests.synthetic import make_pdfs, make_scans

A4_TOP = 842.0


def page_text(db, doc_id: str) -> list[tuple]:
    return db.execute(
        "SELECT page_number, source, lines, has_table FROM page_text WHERE document_id = %s"
        " ORDER BY page_number",
        (doc_id,),
    ).fetchall()


def flags(db, doc_id: str) -> dict[int, dict[str, str]]:
    found: dict[int, dict[str, str]] = {}
    for page, code, reason in db.execute(
        "SELECT page_number, code, reason FROM page_flag WHERE document_id = %s", (doc_id,)
    ):
        found.setdefault(page, {})[code] = reason
    return found


def document_text(db, doc_id: str) -> str:
    return db.execute(
        "SELECT text FROM document_text WHERE document_id = %s", (doc_id,)
    ).fetchone()[0]


def read(cli, *args) -> None:
    result = cli("read", *args)
    assert result.exit_code == 0, result.stderr


def fake_truth(*pages: list[tuple]) -> dict:
    """Truth for TruthEngine: per page a list of (text, top, confidence) lines at x 50."""
    return {
        "pages": [
            {
                "page": n,
                "kind": "scan",
                "lines": [
                    {
                        "text": text,
                        "bbox": [50.0, top - 10.0, 50.0 + 6.0 * len(text), top],
                        "confidence": conf,
                    }
                    for text, top, conf in lines
                ],
            }
            for n, lines in enumerate(pages, start=1)
        ]
    }


# --- US2-1, FR-004, FR-009 ------------------------------------------------------------------


def test_recognised_pages_are_read_as_recognised(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")

    read(cli, doc)

    for _, source, lines, _ in page_text(db, doc):
        assert source == "recognized"
        assert lines and all("confidence" in line for line in lines)
    assert flags(db, doc) == {}
    assert stage(db, doc, "reading")[:2] == ("done", None)
    text = document_text(db, doc)
    for page in truth_of(pdf)["pages"]:
        assert page["lines"][1]["text"] in text


def test_mixed_document_keeps_page_order_and_sources(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_mixed)
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")

    read(cli, doc)

    assert [(p, src) for p, src, _, _ in page_text(db, doc)] == [
        (1, "pdf"),
        (2, "recognized"),
        (3, "pdf"),
        (4, "recognized"),
    ]
    spans = db.execute(
        "SELECT page_number FROM text_span WHERE document_id = %s ORDER BY start", (doc,)
    ).fetchall()
    pages_in_order = [p for (p,) in spans]
    assert pages_in_order == sorted(pages_in_order)


# --- US2-2 --------------------------------------------------------------------------------


def test_unrecognised_and_failed_scans_stay_scan_unread(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_mixed)
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")
    db.execute("DELETE FROM page_recognition WHERE document_id = %s AND page_number = 4", (doc,))
    db.execute(
        "UPDATE page_recognition SET error = 'RuntimeError: engine failed', lines = '[]',"
        " quality = NULL WHERE document_id = %s AND page_number = 2",
        (doc,),
    )

    read(cli, doc)

    found = flags(db, doc)
    assert found[4] == {"scan_unread": f"распознавание не выполнено — docreader recognize {doc}"}
    assert found[2] == {"scan_unread": "ошибка распознавания: RuntimeError: engine failed"}
    assert [p for p, _, lines, _ in page_text(db, doc) if lines] == [1, 3]


# --- US2-3: find a phrase across a line break -------------------------------------------------


def test_phrase_across_a_line_break_is_found_on_the_page(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    truth = truth_of(pdf)
    use_engine(TruthEngine(truth))
    cli("recognize")
    read(cli, doc)
    lines = truth["pages"][0]["lines"]
    k = next(
        i
        for i in range(len(lines) - 1)
        if not lines[i]["text"].endswith("-") and " " in lines[i + 1]["text"]
    )
    phrase = f"{lines[k]['text'].split()[-1]} {lines[k + 1]['text'].split()[0]}"

    result = cli("text", doc, "--find", phrase, "--json")

    assert result.exit_code == 0
    (match,) = json.loads(result.stdout)["matches"]
    assert match["page"] == 1
    assert match["bbox"] == pytest.approx(lines[k]["bbox"], abs=1.0)
    assert [ln["page"] for ln in match["lines"]] == [1, 1]


# --- US2-4: headers and hyphenation work on recognised text -----------------------------------


def test_headers_and_hyphenation_on_recognised_pages(cli, db, tmp_path, use_engine) -> None:
    (doc,), _ = add(cli, tmp_path / "in", lambda p: make_scans.make_scan_clean(p, pages=3))
    page = [
        ("Договор подряда № 123/45-У", A4_TOP - 30, 0.95),
        ("Подрядчик выполняет строительно-мон-", 700.0, 0.95),
        ("тажные работы на объекте.", 686.0, 0.95),
    ]
    use_engine(TruthEngine(fake_truth(page, page, page)))
    cli("recognize")

    read(cli, doc)

    text = document_text(db, doc)
    assert "строительно-монтажные работы" in text
    assert "Договор подряда № 123/45-У" not in text
    roles = {line["role"] for _, _, lines, _ in page_text(db, doc) for line in lines}
    assert "header" in roles


# --- US2-5: after a reset, plain `read` re-reads ---------------------------------------------


def test_plain_read_rereads_after_recognition(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    read(cli)
    assert db.execute(
        "SELECT read_pages FROM document_text WHERE document_id = %s", (doc,)
    ).fetchone()[0] == 0
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")
    assert stage(db, doc, "reading")[0] == "pending"

    read(cli)

    assert stage(db, doc, "reading")[:2] == ("done", None)
    assert truth_of(pdf)["pages"][0]["lines"][0]["text"] in document_text(db, doc)


# --- US2-6: a recognition error inside a quote is not hidden ----------------------------------


def test_wrong_letter_is_kept_and_the_quote_is_not_found(cli, db, tmp_path, use_engine) -> None:
    (doc,), _ = add(cli, tmp_path / "in", lambda p: make_scans.make_scan_clean(p, pages=1))
    use_engine(TruthEngine(fake_truth([("Подрядчик обязуется выполнитъ работы", 700.0, 0.9)])))
    cli("recognize")
    read(cli, doc)

    text = document_text(db, doc)

    assert "выполнитъ" in text
    assert textnorm.locate(text, "Подрядчик обязуется выполнить") == []
    assert "Не найдено" in cli("text", doc, "--find", "обязуется выполнить").stdout


# --- US3: low recognition quality -------------------------------------------------------------


def test_low_quality_page_is_flagged_and_needs_review(cli, db, tmp_path, use_engine) -> None:
    (doc,), _ = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    good = [("Подрядчик обязуется выполнить работы", 700.0, 0.95)]
    bad = [("Пдрдчк бзтс", 700.0, 0.40), ("вплнть рбт", 686.0, 0.45)]
    use_engine(TruthEngine(fake_truth(good, bad)))
    cli("recognize")

    read(cli, doc)

    found = flags(db, doc)
    assert set(found) == {2}
    reason = found[2]["low_recognition_quality"]
    assert reason.startswith("оценка 0,4") and "< 0,80" in reason
    assert [len(lines) for _, _, lines, _ in page_text(db, doc)] == [1, 2]
    state, reason, _ = stage(db, doc, "reading")
    assert state == "needs_review"
    assert "стр. 2: низкое качество распознавания" in reason


def test_good_recognition_alone_does_not_need_review(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf), confidence=0.99))
    cli("recognize")

    read(cli, doc)

    assert stage(db, doc, "reading")[:2] == ("done", None)


def test_thresholds_used_by_reading_are_recorded(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf)))
    cli("recognize")

    read(cli, doc)

    (settings,) = db.execute(
        "SELECT settings FROM run WHERE stage = 'reading' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert settings["recognition"]["page_min_quality"] == 0.8


# --- columns, other flags, regression -----------------------------------------------------------


def test_requisites_left_column_before_right(cli, db, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_requisites_two_columns)
    truth = truth_of(pdf)
    use_engine(TruthEngine(truth))
    cli("recognize")

    read(cli, doc)

    text = document_text(db, doc)
    lines = [ln["text"] for ln in truth["pages"][0]["lines"]]
    positions = [text.index(line) for line in lines]
    assert positions == sorted(positions)  # truth lists the left column first


def test_not_russian_letters_are_flagged_on_recognised_text(cli, db, tmp_path, use_engine) -> None:
    (doc,), _ = add(cli, tmp_path / "in", lambda p: make_scans.make_scan_clean(p, pages=1))
    page = [(line, 700.0 - 14 * n, 0.95) for n, line in enumerate(make_pdfs.kazakh_ru_lines(3))]
    use_engine(TruthEngine(fake_truth(page)))
    cli("recognize")

    read(cli, doc)

    assert "maybe_not_russian" in flags(db, doc)[1]
    stored = rows(db, doc)[0]["lines"]
    assert [ln["text"] for ln in stored] == [line for line, _, _ in page]


def test_text_pdfs_are_still_read_from_the_text_layer(cli, db, tmp_path) -> None:
    (doc,), _ = add(cli, tmp_path / "in", make_pdfs.make_contract_ru)

    read(cli, doc)

    assert {src for _, src, _, _ in page_text(db, doc)} == {"pdf"}
    text = document_text(db, doc)
    for page in make_pdfs.CONTRACT_RU_PAGES:
        assert page[0] in text


# --- US4: pages without text and recomputed flags (task T041) ---------------------------------


def test_stamp_only_page_and_blank_sheet(cli, db, tmp_path, use_engine) -> None:
    (stamp, blank), _ = add(
        cli, tmp_path / "in", make_scans.make_scan_stamp_only, make_scans.make_scan_blank
    )
    use_engine(TruthEngine({"pages": [{"page": 1, "kind": "scan", "lines": []}]}))
    assert cli("recognize", stamp).exit_code == 0
    use_engine(TruthEngine({"pages": [{"page": 1, "kind": "scan", "lines": []}]}))
    assert cli("recognize", blank).exit_code == 0

    read(cli)

    (stamp_flag,) = flags(db, stamp)[1].items()
    assert stamp_flag[0] == "scan_no_text" and stamp_flag[1].startswith("строк нет, тёмных точек")
    assert stage(db, stamp, "reading")[0] == "needs_review"
    assert set(flags(db, blank)[1]) == {"empty"}
    assert stage(db, blank, "reading")[0] == "needs_review"  # no read text at all
    assert "нет прочитанного текста" in stage(db, blank, "reading")[1]
    assert "текст на скане не найден" not in stage(db, blank, "reading")[1]


def test_changed_threshold_needs_only_a_reread(cli, db, data_dir, tmp_path, use_engine) -> None:
    (doc,), (pdf,) = add(cli, tmp_path / "in", make_scans.make_scan_clean)
    use_engine(TruthEngine(truth_of(pdf), confidence=0.9))
    cli("recognize")
    read(cli, doc)
    assert flags(db, doc) == {}
    saved = rows(db, doc)
    factory = use_engine(TruthEngine(truth_of(pdf)))

    (data_dir / "settings.toml").write_text(
        "[recognition]\npage_min_quality = 0.95\n", encoding="utf-8"
    )
    read(cli, "--all")

    assert {page: set(codes) for page, codes in flags(db, doc).items()} == {
        1: {"low_recognition_quality"},
        2: {"low_recognition_quality"},
    }
    assert factory.calls == 0
    assert rows(db, doc) == saved

    (data_dir / "settings.toml").write_text("", encoding="utf-8")
    read(cli, "--all")
    assert flags(db, doc) == {}
