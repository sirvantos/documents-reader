import json

from docreader.render import render_intake_json, render_intake_text

REPORT_PATH = "/data/reports/intake-7.json"


def _contract_report() -> dict:
    return {
        "run_id": 7,
        "started_at": "2026-11-16T10:42:05+05:00",
        "finished_at": "2026-11-16T10:42:08.100000+05:00",
        "code_version": "a1b2c3d",
        "interrupted": False,
        "files": [
            {
                "path": "/in/dogovor_12.pdf",
                "status": "added",
                "document_id": "D-0006",
                "page_count": 24,
                "page_kinds": {"text": 24, "scan": 0, "scan_with_text": 0},
                "warnings": [],
            },
            {
                "path": "/in/dogovor_13.pdf",
                "status": "added",
                "document_id": "D-0007",
                "page_count": 18,
                "page_kinds": {"text": 17, "scan": 1, "scan_with_text": 0},
                "warnings": [
                    {
                        "code": "scan_pages",
                        "pages": [18],
                        "message": "страницы-сканы на первом этапе не читаются: стр. 18",
                    }
                ],
            },
            {
                "path": "/in/scan_14.pdf",
                "status": "added",
                "document_id": "D-0008",
                "page_count": 9,
                "page_kinds": {"text": 0, "scan": 0, "scan_with_text": 9},
                "warnings": [
                    {
                        "code": "scan_with_text_pages",
                        "pages": list(range(1, 10)),
                        "message": "текст стр. 1–9 получен распознаванием и может содержать ошибки",
                    }
                ],
            },
            {
                "path": "/in/dogovor_12_copy.pdf",
                "status": "existing",
                "document_id": "D-0006",
                "warnings": [],
            },
            {
                "path": "/in/contract.docx",
                "status": "rejected",
                "reason_code": "word",
                "reason": "формат не поддерживается: документ Word — сохраните его в PDF",
                "warnings": [],
            },
            {
                "path": "/in/secret.pdf",
                "status": "rejected",
                "reason_code": "encrypted",
                "reason": "защищён паролем",
                "warnings": [],
            },
        ],
        "totals": {"files": 6, "added": 3, "existing": 1, "rejected": 2},
    }


CONTRACT_TEXT = "\n".join(
    [
        "Запуск 7, 2026-11-16 10:42, версия a1b2c3d",
        "",
        "Добавлено: 3",
        "  D-0006  dogovor_12.pdf        24 стр.  текст 24",
        "  D-0007  dogovor_13.pdf        18 стр.  текст 17, скан 1",
        "          ! страницы-сканы на первом этапе не читаются: стр. 18",
        "  D-0008  scan_14.pdf            9 стр.  скан с текстом 9",
        "          ! текст стр. 1–9 получен распознаванием и может содержать ошибки",
        "Уже есть: 1",
        "  dogovor_12_copy.pdf  → D-0006",
        "Не добавлено: 2",
        "  contract.docx        формат не поддерживается: документ Word — сохраните его в PDF",
        "  secret.pdf           защищён паролем",
        "",
        f"Всего файлов: 6, время 3,1 с. Отчёт: {REPORT_PATH}",
        "",
    ]
)


def test_contract_example_text_matches_exactly():
    assert render_intake_text(_contract_report(), REPORT_PATH) == CONTRACT_TEXT


def test_empty_groups_are_omitted():
    report = {
        "run_id": 1,
        "started_at": "2026-11-16T10:00:00+00:00",
        "finished_at": "2026-11-16T10:00:00.500000+00:00",
        "code_version": "v",
        "interrupted": False,
        "files": [
            {
                "path": "/in/a.pdf",
                "status": "rejected",
                "reason_code": "hidden",
                "reason": "скрытый файл",
                "warnings": [],
            }
        ],
        "totals": {"files": 1, "added": 0, "existing": 0, "rejected": 1},
    }
    text = render_intake_text(report, REPORT_PATH)
    assert "Добавлено" not in text
    assert "Уже есть" not in text
    assert "Не добавлено: 1" in text
    assert "время 0,5 с" in text


def test_kind_labels_show_only_nonzero_kinds():
    report = _contract_report()
    text = render_intake_text(report, REPORT_PATH)
    assert "  D-0006  dogovor_12.pdf        24 стр.  текст 24\n" in text
    assert "нулев" not in text
    assert "скан 0" not in text
    assert "текст 0" not in text
    assert "скан с текстом 0" not in text


def test_added_line_without_any_kind_has_no_trailing_separator():
    report = _contract_report()
    report["files"][0]["page_kinds"] = {"text": 0, "scan": 0, "scan_with_text": 0}
    text = render_intake_text(report, REPORT_PATH)
    assert "  D-0006  dogovor_12.pdf        24 стр.\n" in text


def test_interrupted_footer_line_follows_totals_footer():
    report = _contract_report()
    report["interrupted"] = True
    text = render_intake_text(report, REPORT_PATH)
    assert text.endswith(
        f"Всего файлов: 6, время 3,1 с. Отчёт: {REPORT_PATH}\n"
        "Прервано: уже добавленные документы сохранены, "
        "повторный запуск добавит остальные\n"
    )


def test_unfinished_run_shows_dash_for_elapsed_time():
    report = _contract_report()
    report["finished_at"] = None
    text = render_intake_text(report, REPORT_PATH)
    assert "время —." in text


def test_json_round_trip_preserves_cyrillic():
    report = _contract_report()
    rendered = render_intake_json(report)
    assert "документ Word" in rendered
    assert "\\u" not in rendered
    assert json.loads(rendered) == report
