"""Pure parts of the Б6 helper scripts (prepare_b6, tune_thresholds, auto_eval_textlayer).

All values are made up; check digits of ИНН/ОГРН were computed by hand from the formulas.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image, ImageDraw

from docreader.config import RecognitionSettings

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up there
    spec.loader.exec_module(module)
    return module


prepare = load("prepare_b6")
tune = load("tune_thresholds")
auto = load("auto_eval_textlayer")


# --- prepare_b6: requisites that cannot be right ------------------------------------------


def test_inn_check_digits() -> None:
    # 5·2+0+0+1·3+0+0+7·4+3·6+2·8 = 75; 75 mod 11 = 9
    assert prepare.inn_valid("5001007329")
    assert not prepare.inn_valid("5001007328")
    assert prepare.inn_valid("500100732259")  # both check digits: 5 and 9
    assert not prepare.inn_valid("500100732258")
    assert not prepare.inn_valid("50010073")
    assert not prepare.inn_valid("50010О7329")  # a letter О for a zero


def test_ogrn_check_digit() -> None:
    # 102770000000 mod 11 = 8
    assert prepare.ogrn_valid("1027700000008")
    assert not prepare.ogrn_valid("1027700000007")
    assert not prepare.ogrn_valid("102770000000")


def test_dates() -> None:
    assert prepare.date_valid("29.02.2024")
    assert not prepare.date_valid("31.02.2024")
    assert not prepare.date_valid("12.13.2024")
    assert not prepare.date_valid("1.02.2024")


def test_suspicious_values_lists_only_broken_ones() -> None:
    text = (
        "ИНН 5001007329 КПП 500101001\n"
        "ИНН 5001007328 ОГРН 1027700000007\n"
        "КПП 50010100 от 31.02.2024 и от 29.02.2024"
    )
    notes = prepare.suspicious_values(text)
    assert len(notes) == 4
    assert any("5001007328" in n for n in notes)
    assert any("1027700000007" in n for n in notes)
    assert any("50010100" in n for n in notes)
    assert any("31.02.2024" in n for n in notes)


def test_check_notes_name_low_lines_values_and_dpi_differences() -> None:
    lines = [
        {"text": "1.1. Предмет договора", "confidence": 0.95},
        {"text": "ИНН 5001007328", "confidence": 0.55},
        {"text": "———", "confidence": 0.10},  # no letter or digit: not a text line
        {"text": "Сумма 1 000,00 руб.", "confidence": 0.90},
    ]
    other = ["1.1. Предмет договора", "ИНН 5001007329", "Сумма 7 000,00 руб."]
    notes = prepare.check_notes(lines, 0.60, other)
    assert "строка 2: уверенность 0.55" in notes
    assert "строка 3:" not in notes
    assert "ИНН «5001007328»" in notes
    assert "строка 4: при 400 dpi читается иначе — «Сумма 7 000,00 руб.»" in notes


def test_check_notes_without_findings() -> None:
    notes = prepare.check_notes([{"text": "Текст", "confidence": 0.9}], 0.6, None)
    assert "подозрительного не найдено" in notes


# --- prepare_b6: choosing pages -----------------------------------------------------------


def cand(doc: int, page: int, **kw: object) -> object:
    values: dict = {"doc_id": f"D-{doc:04d}", "page": page, "quality": 0.9, "flagged": False,
                    "lines": 30, "requisites": False, "amount": False}
    values.update(kw)
    return prepare.Candidate(**values)


def test_eval_pages_spread_over_documents_and_include_requisites_and_amount() -> None:
    pool = [cand(d, p) for d in range(1, 13) for p in range(1, 4)]
    pool += [cand(3, 9, requisites=True), cand(5, 9, amount=True), cand(4, 9, lines=2)]
    chosen = prepare.select_eval_pages(pool, 20, seed=1)
    keys = [(c.doc_id, c.page) for c in chosen]
    assert len(chosen) == 20 and len(set(keys)) == 20
    assert len({c.doc_id for c in chosen}) == 12  # every document before any second page
    assert ("D-0003", 9) in keys and ("D-0005", 9) in keys
    assert ("D-0004", 9) not in keys  # fewer than 5 lines: not worth verifying
    assert prepare.select_eval_pages(pool, 20, seed=1) == chosen  # reproducible


def test_flag_pages_take_rare_documents_first() -> None:
    pool = [cand(56, p, flagged=True) for p in range(1, 31)]
    pool += [cand(27, 1, flagged=True), cand(51, 2, flagged=True), cand(21, 3, flagged=True)]
    pool += [cand(d, p) for d in range(1, 11) for p in range(1, 5)]
    chosen = prepare.select_flag_pages(pool, 20, seed=1)
    flagged = [c for c in chosen if c.flagged]
    assert len(flagged) == 20 and len(chosen) == 40
    assert {"D-0027", "D-0051", "D-0021"} <= {c.doc_id for c in flagged}
    assert len({c.doc_id for c in chosen if not c.flagged}) == 10


def test_control_rows_come_from_the_drafts() -> None:
    drafts = {("D-0002", 1): "1.1. Предмет\nИНН 5001007329\nот 29.02.2024 на 1 000,00 руб.",
              ("D-0002", 2): "ИНН 5001007329"}
    rows = prepare.control_rows(drafts)
    assert ("D-0002", "5001007329", "inn") in rows
    assert ("D-0002", "1.1", "clause") in rows
    assert ("D-0002", "29.02.2024", "date") in rows
    assert ("D-0002", "1 000,00", "amount") in rows
    assert sum(1 for r in rows if r[1] == "5001007329") == 1
    assert prepare.csv_text(("a", "b"), [("1", "2")]) == "a;b\n1;2\n"


# --- prepare_b6: boxes on the image -------------------------------------------------------


def test_pdf_box_to_image() -> None:
    crop = (0.0, 0.0, 600.0, 800.0)
    assert prepare.pdf_box_to_image((10, 20, 110, 40), crop, 0, 1.0) == (10, 760, 110, 780)
    assert prepare.pdf_box_to_image((10, 20, 110, 40), crop, 90, 1.0) == (20, 10, 40, 110)
    assert prepare.pdf_box_to_image((10, 20, 110, 40), (5, 5, 605, 805), 0, 2.0) == (
        10, 1530, 210, 1570,
    )


def test_box_on_ink() -> None:
    image = Image.new("L", (200, 100), 255)
    ImageDraw.Draw(image).rectangle((20, 20, 80, 30), fill=0)
    page_ink = prepare.dark_share(image)
    assert prepare.box_on_ink(image, (15, 15, 85, 35), page_ink)
    assert not prepare.box_on_ink(image, (120, 60, 190, 90), page_ink)


def test_box_on_ink_of_a_faded_page() -> None:
    # grey text (170) on a light background (235): nothing is darker than 128
    image = Image.new("L", (200, 100), 235)
    ImageDraw.Draw(image).rectangle((20, 20, 80, 30), fill=170)
    assert prepare.dark_share(image) == 0.0
    threshold = prepare.ink_threshold(image)
    assert 170 < threshold < 235
    page_ink = prepare.dark_share(image, None, threshold)
    assert prepare.box_on_ink(image, (15, 15, 85, 35), page_ink, threshold)
    assert not prepare.box_on_ink(image, (120, 60, 190, 90), page_ink, threshold)
    assert prepare.ink_threshold(Image.new("L", (10, 10), 250)) == 128  # blank: no contrast


# --- tune_thresholds ----------------------------------------------------------------------


def test_parse_flags_reports_unfilled_rows() -> None:
    rows, problems = tune.parse_flags(
        "документ;страница;плохая\nD-0001;3;да\nD-0001;4;нет\nD-0002;5;\nD-0002;x;да\n\n"
    )
    assert rows == [("D-0001", 3, True), ("D-0001", 4, False)]
    assert problems == [
        "строка 4: «плохая» — «», нужно да или нет",
        "строка 5: номер страницы «x» неверен",
    ]


def stored(quality: float, low_lines: int = 0, lines: int = 10) -> object:
    items = [{"text": "Текст строки", "confidence": 0.3 if i < low_lines else 0.95}
             for i in range(lines)]
    return tune.Stored(items, quality, 0.05, False)


def test_score_uses_the_flag_rule_of_read() -> None:
    marked = [(stored(0.55), True), (stored(0.92), False), (stored(0.75), False)]
    base = RecognitionSettings()
    now = tune.score(marked, base, (0.80, 0.60, 0.20))
    assert (now.correct, now.false_positive, now.false_negative) == (2, 1, 0)
    lower = tune.score(marked, base, (0.70, 0.60, 0.20))
    assert lower.accuracy == 1.0


def test_rank_prefers_fewer_missed_bad_pages_then_closeness() -> None:
    a = tune.Score((0.5, 0.6, 0.2), 8, 0, 2)
    b = tune.Score((0.9, 0.6, 0.2), 8, 2, 0)
    c = tune.Score((0.85, 0.6, 0.2), 8, 2, 0)
    assert tune.rank([a, b, c], (0.8, 0.6, 0.2)) == [c, b, a]


def test_report_prints_numbers_and_a_settings_snippet() -> None:
    marked = [(stored(0.55), True), (stored(0.92), False), (stored(0.75), False)]
    lines = tune.report_lines(marked, RecognitionSettings(), [p for p, _ in marked])
    text = "\n".join(lines)
    assert "Размечено страниц: 3 (плохих 1, хороших 2)" in text
    assert "Сейчас: page_min_quality 0.80" in text and "верен 66.7%" in text
    assert "Лучшее сочетание:" in text and "верен 100.0%" in text
    assert "  [recognition]" in text and "page_min_quality = " in text
    assert "Текст строки" not in text


# --- auto_eval_textlayer ------------------------------------------------------------------


def test_word_recall_ignores_order_and_punctuation() -> None:
    assert auto.word_recall("Договор подряда, №5", "№5 подряда договор") == 1.0
    assert auto.word_recall("раз два два три", "раз два три") == pytest.approx(0.75)
    assert auto.word_recall("", "что угодно") == 1.0


def test_box_match_counts_both_directions() -> None:
    reference = [(10, 700, 300, 712), (10, 680, 300, 692)]
    recognised = [(11, 699, 150, 713), (160, 699, 299, 713), (10, 100, 50, 110)]
    on, rec, hit, ref = auto.box_match(recognised, reference)
    assert (on, rec) == (2, 3)  # the third box is nowhere near a text-layer line
    assert (hit, ref) == (0, 2)  # each reference line is split across two engine boxes
    on, rec, hit, ref = auto.box_match([(10, 700, 300, 712)], reference)
    assert (on, hit) == (1, 1)


def test_summary_lines_only_numbers_and_ids() -> None:
    results = [
        auto.PageResult("D-0001", 1, 1000, 20, 0.97, {"inn": (2, 2), "date": (1, 2)},
                        (40, 42, 38, 40), False, 1.8),
        auto.PageResult("D-0002", 4, 500, 100, 0.80, {}, (10, 20, 9, 20), True, 2.2),
        auto.PageResult("D-0002", 5, 0, 0, 0.0, seconds=0.5, error="RuntimeError"),
    ]
    text = "\n".join(auto.summary_lines(results, 300, "tesseract 5.5.4"))
    assert "страниц 3, из них с ошибкой 1; документов 2" in text
    assert "Верных знаков (как recognize-eval, зависит от порядка строк): 92.0%" in text
    assert "Реквизиты и числа без ошибок: 75.0% (date 1/2, inn 2/2)" in text
    assert "распознанных на строке текстового слоя 80.6% (50 из 62)" in text
    assert "Флаг «низкое качество» на этих чистых страницах: 1 из 2" in text
    assert text.index("D-0002 стр. 4: 80.0%") < text.index("D-0001 стр. 1: 98.0%")
