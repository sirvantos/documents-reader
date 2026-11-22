"""The part of the text shown to the model (feature 05, research R-4; task T010).

Preamble, main text and requisites: the text before the first line inside the tail that
starts with the word «Приложение». Critical rule (CLAUDE.md «Model routing»).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from docreader import extraction_text
from docreader.extraction_text import APPENDIX_LINE, shown_end

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "survey_fields.py"

MAIN = "Договор подряда\n1. Предмет\n1.1. Работы выполняются согласно Приложению № 2.\n"
TAIL = "5. Адреса и реквизиты сторон\nЗаказчик: ООО «Альфа»\n"
APPENDIX = "Приложение № 1\nВедомость цены\n"


def test_appendix_line_in_the_tail_is_the_boundary() -> None:
    text = MAIN + TAIL + APPENDIX
    assert shown_end(text, len(MAIN)) == len(MAIN + TAIL)


def test_upper_case_appendix_line() -> None:
    text = MAIN + TAIL + "ПРИЛОЖЕНИЕ № 1\nВедомость\n"
    assert shown_end(text, len(MAIN)) == len(MAIN + TAIL)


def test_indented_appendix_line() -> None:
    text = MAIN + TAIL + "   Приложение 1\n"
    assert shown_end(text, len(MAIN)) == len(MAIN + TAIL)


def test_appendix_word_alone_on_a_line() -> None:
    text = MAIN + TAIL + "Приложение\nк договору\n"
    assert shown_end(text, len(MAIN)) == len(MAIN + TAIL)


def test_list_of_appendices_is_not_a_boundary() -> None:
    listing = "Приложения: 1. Ведомость цены.\n"
    text = MAIN + TAIL + listing + APPENDIX
    assert shown_end(text, len(MAIN)) == len(MAIN + TAIL + listing)


def test_appendix_word_inside_a_line_is_not_a_boundary() -> None:
    text = MAIN + TAIL + "Подписи и Приложение № 1 прилагаются\n"
    assert shown_end(text, len(MAIN)) == len(text)


def test_appendix_line_before_the_tail_is_ignored() -> None:
    main = "1. Предмет\nПриложение № 3 является частью договора.\n"
    text = main + TAIL + APPENDIX
    assert shown_end(text, len(main)) == len(main + TAIL)


def test_appendix_line_starting_exactly_at_the_tail() -> None:
    # a tail that begins with the appendix: nothing of it is shown
    text = MAIN + APPENDIX
    assert shown_end(text, len(MAIN)) == len(MAIN)


def test_no_appendix_line_in_the_tail() -> None:
    text = MAIN + TAIL
    assert shown_end(text, len(MAIN)) == len(text)


def test_no_tail_shows_the_whole_text() -> None:
    text = MAIN + APPENDIX
    assert shown_end(text, None) == len(text)


def test_empty_text() -> None:
    assert shown_end("", None) == 0


def test_survey_uses_the_same_expression() -> None:
    spec = importlib.util.spec_from_file_location("survey_fields_for_t010", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.APPENDIX_LINE is extraction_text.APPENDIX_LINE
    assert APPENDIX_LINE.pattern == r"(?m)^\s*приложение(?:\s|$)"
