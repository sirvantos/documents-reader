"""Settings of the [answer] section (feature 09, research R-2; task T002).

The connection to the language model is `[extraction]` (one model server on the Mac);
`[answer]` holds only what the answer has of its own. Written by the main session: the
implementer must not edit, weaken, skip or delete these tests (CLAUDE.md «Model routing»).
"""

from dataclasses import asdict
from pathlib import Path

import pytest

from docreader.config import AnswerSettings, load_settings
from docreader.errors import EnvironmentProblem

ANSWER_DEFAULTS = {"passages": 8, "max_tokens": 2048, "max_retries": 2}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def load(data_dir: Path, text: str | None = None):
    if text is not None:
        (data_dir / "settings.toml").write_text(text, encoding="utf-8")
    return load_settings({"DOCREADER_DATA_DIR": str(data_dir)})


def test_defaults_without_section(data_dir: Path) -> None:
    assert asdict(load(data_dir).answer) == ANSWER_DEFAULTS


def test_dataclass_defaults_match() -> None:
    assert asdict(AnswerSettings()) == ANSWER_DEFAULTS


def test_settings_are_frozen() -> None:
    with pytest.raises(AttributeError):
        AnswerSettings().passages = 3  # type: ignore[misc]  # frozen on purpose


def test_overrides_applied(data_dir: Path) -> None:
    s = load(data_dir, "[answer]\npassages = 4\nmax_tokens = 1024\nmax_retries = 0\n")
    assert asdict(s.answer) == {"passages": 4, "max_tokens": 1024, "max_retries": 0}


def test_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    s = load(data_dir, "[answer]\npassages = 5\n")
    assert s.answer.passages == 5
    assert s.answer.max_tokens == 2048 and s.answer.max_retries == 2


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("passages = 1", True),
        ("passages = 30", True),
        ("passages = 0", False),
        ("max_tokens = 64", True),
        ("max_tokens = 32768", True),
        ("max_tokens = 63", False),
        ("max_tokens = 32769", False),
        ("max_retries = 0", True),
        ("max_retries = 5", True),
        ("max_retries = -1", False),
        ("max_retries = 6", False),
        ("passages = 8.0", False),
        ("passages = true", False),
        ('max_tokens = "2048"', False),
    ],
)
def test_answer_bounds(data_dir: Path, line: str, ok: bool) -> None:
    text = f"[answer]\n{line}\n"
    if ok:
        load(data_dir, text)
    else:
        with pytest.raises(EnvironmentProblem, match="answer"):
            load(data_dir, text)


def test_passages_not_above_rerank_candidates(data_dir: Path) -> None:
    # the default [search] rerank_candidates (30) bounds passages
    with pytest.raises(EnvironmentProblem, match="passages"):
        load(data_dir, "[answer]\npassages = 31\n")
    load(data_dir, "[answer]\npassages = 12\n[search]\nrerank_candidates = 12\nresults = 8\n")
    with pytest.raises(EnvironmentProblem, match="passages"):
        load(data_dir, "[answer]\npassages = 13\n[search]\nrerank_candidates = 12\nresults = 8\n")
    # the order of the sections in the file does not matter
    with pytest.raises(EnvironmentProblem, match="passages"):
        load(data_dir, "[search]\nrerank_candidates = 12\nresults = 8\n[answer]\npassages = 13\n")


def test_unknown_key_named(data_dir: Path) -> None:
    with pytest.raises(EnvironmentProblem, match=r"answer\.model"):
        load(data_dir, '[answer]\nmodel = "other"\n')


def test_error_is_environment_problem_code_2(data_dir: Path) -> None:
    with pytest.raises(EnvironmentProblem) as info:
        load(data_dir, "[answer]\npassages = 0\n")
    assert info.value.exit_code == 2
