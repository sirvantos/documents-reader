"""`docreader recognize` text output and progress line (contracts/cli.md, T020)."""

from __future__ import annotations

from docreader.render import render_recognize_progress, render_recognize_text


def _doc(
    seq: int,
    *,
    scan_pages: int = 0,
    recognized: int = 0,
    errors: int = 0,
    state: str = "done",
    reason: str | None = None,
    reading_reset: bool = False,
    seconds: float = 0.0,
    flags: dict | None = None,
) -> dict:
    return {
        "id": f"D-{seq:04d}",
        "scan_pages": scan_pages,
        "recognized": recognized,
        "errors": errors,
        "state": state,
        "reason": reason,
        "reading_reset": reading_reset,
        "seconds": seconds,
        "flags": flags or {},
        "pages": [],
    }


def _data(
    documents: list[dict],
    *,
    run_id: int = 57,
    engine: str | None = "tesseract",
    engine_version: str | None = "5.5.0 rus 4.1.0",
    dpi: int | None = 300,
    totals: dict | None = None,
) -> dict:
    return {
        "run_id": run_id,
        "engine": engine,
        "engine_version": engine_version,
        "dpi": dpi,
        "interrupted": False,
        "documents": documents,
        "totals": totals
        or {"pages": 0, "recognized": 0, "errors": 0, "seconds": 0.0, "flags": {}},
    }


def _lines(data: dict) -> list[str]:
    return render_recognize_text(data).splitlines()


def _totals(pages: int = 0, recognized: int = 0, errors: int = 0, seconds: float = 0.0,
            low: int = 0) -> dict:
    flags = {"low_recognition_quality": low} if low else {}
    return {
        "pages": pages,
        "recognized": recognized,
        "errors": errors,
        "seconds": seconds,
        "flags": flags,
    }


# --- header ----------------------------------------------------------------------------


def test_header_with_engine_and_documents_plural() -> None:
    data = _data([_doc(3), _doc(4), _doc(5)])

    assert _lines(data)[0] == (
        "Распознавание, запуск 57 (tesseract 5.5.0 rus 4.1.0, 300 dpi): 3 документа"
    )


def test_header_without_engine() -> None:
    data = _data([_doc(3)], engine=None, engine_version=None, dpi=None)

    assert _lines(data)[0] == "Распознавание, запуск 57: 1 документ"


def test_header_documents_plural_forms() -> None:
    cases = {
        1: "документ",
        2: "документа",
        4: "документа",
        5: "документов",
        11: "документов",
        12: "документов",
        21: "документ",
        22: "документа",
    }
    for count, word in cases.items():
        data = _data([_doc(i) for i in range(1, count + 1)], engine=None)
        assert _lines(data)[0].endswith(f": {count} {word}"), count


# --- rows ------------------------------------------------------------------------------


def test_row_with_statistics() -> None:
    doc = _doc(
        3,
        scan_pages=42,
        recognized=42,
        errors=0,
        seconds=412.4,
        flags={
            "low_recognition_quality": [1, 2, 3],
            "scan_no_text": [7],
            "empty": [10, 11],
        },
    )

    row = _lines(_data([doc]))[1]

    assert row == (
        "D-0003  42 скана  распознано 42  ошибок 0  низкое качество 3  без текста 1"
        "  пустых 2  412 с  готово"
    )


def test_row_with_error_reason() -> None:
    doc = _doc(
        5,
        scan_pages=52,
        recognized=51,
        errors=1,
        state="needs_review",
        reason="стр. 17: ошибка распознавания — RuntimeError: boom",
        seconds=530.0,
    )

    row = _lines(_data([doc]))[1]

    assert row == (
        "D-0005  52 скана  распознано 51  ошибок 1  низкое качество 0  без текста 0"
        "  пустых 0  530 с  требует просмотра: стр. 17: ошибка распознавания"
        " — RuntimeError: boom"
    )


def test_failed_state_word() -> None:
    doc = _doc(6, scan_pages=2, state="failed", reason="копия не открывается")

    assert _lines(_data([doc]))[1].endswith("  ошибка: копия не открывается")


def test_scan_word_plural_forms() -> None:
    cases = {1: "скан", 2: "скана", 4: "скана", 5: "сканов", 11: "сканов", 21: "скан",
             22: "скана"}
    for count, word in cases.items():
        row = _lines(_data([_doc(1, scan_pages=count, recognized=count)]))[1]
        assert f"{count:>2} {word}  " in row, count


def test_document_without_scans_is_aligned_with_others() -> None:
    full = _doc(3, scan_pages=42, recognized=42, seconds=412.0)
    empty = _doc(4)

    rows = _lines(_data([full, empty]))[1:3]

    assert rows[1].startswith("D-0004   0 сканов")
    assert rows[1].endswith("  готово")
    assert rows[0].index("готово") == rows[1].index("готово")
    assert "распознано" not in rows[1]


def test_zero_scan_row_alone_has_no_padding() -> None:
    assert _lines(_data([_doc(4)]))[1] == "D-0004   0 сканов  готово"


# --- reset line ------------------------------------------------------------------------


def test_reset_line_present_lists_documents() -> None:
    docs = [_doc(3, scan_pages=1, recognized=1, reading_reset=True), _doc(4),
            _doc(5, scan_pages=1, recognized=1, reading_reset=True)]

    lines = _lines(_data(docs))

    assert lines[-2] == (
        "Чтение сброшено (распознанный текст изменён): D-0003, D-0005"
        " — выполните docreader read"
    )


def test_reset_line_absent_without_reset() -> None:
    lines = _lines(_data([_doc(3, scan_pages=1, recognized=1)]))

    assert not any(line.startswith("Чтение сброшено") for line in lines)


# --- totals ----------------------------------------------------------------------------


def test_totals_with_average_in_decimal_comma() -> None:
    data = _data(
        [_doc(3, scan_pages=3, recognized=3)],
        totals=_totals(pages=93, recognized=92, errors=1, seconds=942.0, low=3),
    )

    assert _lines(data)[-1] == (
        "Итого: страниц 93, распознано 92, ошибок 1, низкое качество 3;"
        " 942 с, в среднем 10,1 с/стр."
    )


def test_totals_without_pages_omit_average_part() -> None:
    data = _data([_doc(4)], totals=_totals())

    assert _lines(data)[-1] == "Итого: страниц 0, распознано 0, ошибок 0, низкое качество 0"


def test_totals_average_rounds_to_one_decimal() -> None:
    data = _data(
        [_doc(3, scan_pages=2, recognized=2)],
        totals=_totals(pages=3, recognized=3, seconds=10.0),
    )

    assert _lines(data)[-1].endswith("; 10 с, в среднем 3,3 с/стр.")


# --- progress line ---------------------------------------------------------------------


def test_progress_line_uses_decimal_comma() -> None:
    assert render_recognize_progress("D-0003", 5, 42, 3.8) == "D-0003 стр. 5/42  3,8 с"
    assert render_recognize_progress("D-0003", 6, 42, 12.0) == "D-0003 стр. 6/42  12,0 с"
