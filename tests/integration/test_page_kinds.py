"""Integration tests for page kinds (task T031, US3, FR-007).

Everything goes through `docreader add --json` and the `page` table.
"""

from __future__ import annotations

import json

import pytest

from tests.synthetic import make_pdfs as mk


def add_json(cli, path) -> dict:
    result = cli("add", path, "--json")
    assert result.exit_code == 0, result.stderr
    entry = json.loads(result.stdout)["files"][0]
    assert entry["status"] == "added", entry
    return entry


def page_rows(db, document_id: str) -> list[tuple]:
    return db.execute(
        "SELECT page_number, kind, image_coverage, invisible_text_share "
        "FROM page WHERE document_id = %s ORDER BY page_number",
        (document_id,),
    ).fetchall()


def kinds(rows) -> list[str]:
    return [r[1] for r in rows]


def warning(entry: dict, code: str) -> dict | None:
    return next((w for w in entry["warnings"] if w["code"] == code), None)


@pytest.mark.parametrize(
    ("maker", "expected"),
    [
        (mk.make_digital, ["text"] * 3),
        (mk.make_image_only, ["scan"] * 2),
        (mk.make_mixed, ["text", "text", "text", "scan"]),
        (mk.make_image_with_invisible_text, ["scan_with_text"] * 2),
        (mk.make_image_strips, ["scan"]),
        (mk.make_image_in_form, ["scan"]),
        (mk.make_logo_and_text, ["text"]),
        (mk.make_blank_page, ["scan"]),
    ],
    ids=lambda v: getattr(v, "__name__", None),
)
def test_page_kinds(cli, db, tmp_path, maker, expected):
    entry = add_json(cli, maker(tmp_path / "doc.pdf"))

    rows = page_rows(db, entry["document_id"])

    assert kinds(rows) == expected
    assert entry["page_count"] == len(expected)
    assert entry["page_kinds"] == {k: expected.count(k) for k in ("text", "scan", "scan_with_text")}


def test_mixed_reports_scan_pages(cli, tmp_path):
    entry = add_json(cli, mk.make_mixed(tmp_path / "doc.pdf"))

    w = warning(entry, "scan_pages")
    assert w is not None
    assert w["pages"] == [4]
    assert w["message"] == "страницы-сканы на первом этапе не читаются: стр. 4"
    assert warning(entry, "scan_with_text_pages") is None


def test_invisible_text_reports_scan_with_text_pages(cli, tmp_path):
    entry = add_json(cli, mk.make_image_with_invisible_text(tmp_path / "doc.pdf", pages=2))

    w = warning(entry, "scan_with_text_pages")
    assert w is not None
    assert w["pages"] == [1, 2]
    assert w["message"] == "текст стр. 1, 2 получен распознаванием и может содержать ошибки"
    assert warning(entry, "scan_pages") is None


def test_large_file_warning_uses_threshold_from_settings(cli, data_dir, tmp_path):
    (data_dir / "settings.toml").write_text("[intake]\nlarge_file_pages = 2\n", encoding="utf-8")

    entry = add_json(cli, mk.make_digital(tmp_path / "doc.pdf", pages=3))

    w = warning(entry, "large_file")
    assert w is not None
    assert w["message"] == "3 страниц — больше 2"


def test_no_large_file_warning_by_default(cli, tmp_path):
    entry = add_json(cli, mk.make_digital(tmp_path / "doc.pdf", pages=3))

    assert warning(entry, "large_file") is None
    assert entry["warnings"] == []


def test_stored_metrics_are_sane(cli, db, tmp_path):
    form = add_json(cli, mk.make_image_in_form(tmp_path / "form.pdf"))
    logo = add_json(cli, mk.make_logo_and_text(tmp_path / "logo.pdf"))
    invisible = add_json(cli, mk.make_image_with_invisible_text(tmp_path / "inv.pdf"))
    digital = add_json(cli, mk.make_digital(tmp_path / "dig.pdf"))
    image_only = add_json(cli, mk.make_image_only(tmp_path / "img.pdf"))

    assert all(r[2] > 0.99 for r in page_rows(db, form["document_id"]))
    assert all(r[2] < 0.2 for r in page_rows(db, logo["document_id"]))
    assert all(r[3] == 1.0 for r in page_rows(db, invisible["document_id"]))
    assert all(r[3] == 0.0 for r in page_rows(db, digital["document_id"]))
    assert all(r[3] is None for r in page_rows(db, image_only["document_id"]))
