"""Keys of the review page (feature 02, converge T054): a third choice must not clash with
the fixed keys «3» (другое значение), «4» (отсутствует) and «0» (пропустить)."""

from __future__ import annotations

import re

from docreader.review_page import render_html


def _script(page: str) -> str:
    return page.split("<script>", 1)[1]


def test_extra_choices_have_keys_apart_from_the_fixed_ones() -> None:
    script = _script(render_html("b1", []))
    m = re.search(r"const CHOICE_KEYS = \[([^\]]*)\]", script)
    assert m, "the page names the keys of the choices"
    keys = re.findall(r"'([^']+)'", m.group(1))
    assert keys[:2] == ["1", "2"] and len(keys) >= 4  # a model plus several rules values
    assert not {"3", "4", "0"} & set(keys)
    assert len(set(keys)) == len(keys)


def test_choice_buttons_and_hint_use_the_same_keys() -> None:
    page = render_html("b1", [])
    script = _script(page)
    assert "CHOICE_KEYS[k]" in script  # the button label
    assert "CHOICE_KEYS.indexOf" in script  # the key handler
    assert "<kbd>3</kbd> другое" in page and "<kbd>Q</kbd>" in page  # hint row
