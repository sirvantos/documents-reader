"""Settings of the [extraction] section (feature 05, research R-11; task T005).

The loopback check of `base_url` is a privacy guard (principle I): the language model may
only be reached on this machine.
"""

from dataclasses import asdict
from pathlib import Path

import pytest

from docreader.config import ExtractionSettings, is_local_model_url, load_settings
from docreader.errors import EnvironmentProblem

DEFAULTS = {
    "base_url": "http://127.0.0.1:8080/v1",
    "model": "qwen3.6-27b-4bit",
    "mode": "md_json",
    "max_retries": 2,
    "timeout_s": 1800,
    "max_shown_chars": 150000,
    "temperature": 0.0,
    "seed": 0,
    "max_tokens": 2048,
    "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def load(data_dir: Path, text: str | None = None):
    if text is not None:
        (data_dir / "settings.toml").write_text(text, encoding="utf-8")
    return load_settings({"DOCREADER_DATA_DIR": str(data_dir)})


# --- defaults and overrides ------------------------------------------------------------


def test_defaults_without_section(data_dir: Path) -> None:
    assert asdict(load(data_dir).extraction) == DEFAULTS


def test_dataclass_defaults_match() -> None:
    assert asdict(ExtractionSettings()) == DEFAULTS


def test_overrides_applied(data_dir: Path) -> None:
    s = load(
        data_dir,
        '[extraction]\nbase_url = "http://localhost:9000/v1"\nmodel = "m"\nmode = "json"\n'
        "max_retries = 0\ntimeout_s = 10\nmax_shown_chars = 1000\ntemperature = 0.5\n"
        "seed = 7\nmax_tokens = 256\n",
    ).extraction
    assert (s.base_url, s.model, s.mode, s.max_retries, s.timeout_s) == (
        "http://localhost:9000/v1", "m", "json", 0, 10,
    )
    assert (s.max_shown_chars, s.temperature, s.seed, s.max_tokens) == (1000, 0.5, 7, 256)


def test_extra_body_table_read(data_dir: Path) -> None:
    s = load(
        data_dir,
        "[extraction]\nextra_body = { chat_template_kwargs = { enable_thinking = false } }\n",
    ).extraction
    assert s.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}


def test_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    s = load(data_dir, "[extraction]\nseed = 3\n").extraction
    assert asdict(s) == {**DEFAULTS, "seed": 3}


@pytest.mark.parametrize("mode", ["md_json", "json", "json_schema"])
def test_each_mode_accepted(data_dir: Path, mode: str) -> None:
    assert load(data_dir, f'[extraction]\nmode = "{mode}"\n').extraction.mode == mode


@pytest.mark.parametrize(
    "line",
    [
        'model = ""',
        'model = "  "',
        'mode = "tools"',
        "max_retries = -1",
        "max_retries = 6",
        "timeout_s = 9",
        "timeout_s = 7201",
        "max_shown_chars = 999",
        "max_shown_chars = 1000001",
        "temperature = -0.1",
        "temperature = 2.1",
        "seed = -1",
        "max_tokens = 255",
        "max_tokens = 16385",
        'max_retries = "2"',
        "extra_body = 1",
        'extra_body = "x"',
    ],
)
def test_out_of_range_or_wrong_type_rejected(data_dir: Path, line: str) -> None:
    with pytest.raises(EnvironmentProblem, match=r"extraction\."):
        load(data_dir, f"[extraction]\n{line}\n")


def test_bounds_accepted(data_dir: Path) -> None:
    s = load(
        data_dir,
        "[extraction]\nmax_retries = 5\ntimeout_s = 7200\nmax_shown_chars = 1000000\n"
        "temperature = 2\nmax_tokens = 16384\n",
    ).extraction
    assert (s.max_retries, s.timeout_s, s.max_shown_chars, s.temperature, s.max_tokens) == (
        5, 7200, 1000000, 2.0, 16384,
    )


def test_unknown_key_rejected(data_dir: Path) -> None:
    with pytest.raises(EnvironmentProblem, match=r"extraction\.api_key"):
        load(data_dir, '[extraction]\napi_key = "x"\n')


# --- base_url: only this machine (principle I) ------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8080/v1",
        "http://example.com/v1",
        "https://api.openai.com/v1",
        "http://192.168.1.10:8080/v1",
        "http://127.0.0.1.example.com/v1",
        "http://user@example.com/v1",
        "ftp://127.0.0.1/v1",
        "127.0.0.1:8080/v1",
        "",
        "http:///v1",
    ],
)
def test_non_local_base_url_rejected(data_dir: Path, url: str) -> None:
    with pytest.raises(EnvironmentProblem, match=r"extraction\.base_url"):
        load(data_dir, f'[extraction]\nbase_url = "{url}"\n')


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8080/v1",
        "http://localhost:8080/v1",
        "https://localhost/v1",
        "http://[::1]:8080/v1",
        "http://127.0.0.2:1234/v1",
    ],
)
def test_local_base_url_accepted(data_dir: Path, url: str) -> None:
    assert load(data_dir, f'[extraction]\nbase_url = "{url}"\n').extraction.base_url == url


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://127.0.0.1:8080/v1", True),
        ("http://localhost/v1", True),
        ("http://[::1]/v1", True),
        ("http://10.0.0.5/v1", False),
        ("http://example.com/v1", False),
        ("file:///tmp/x", False),
        ("not a url", False),
    ],
)
def test_is_local_model_url(url: str, local: bool) -> None:
    assert is_local_model_url(url) is local


# --- run.settings ----------------------------------------------------------------------


def test_settings_for_run_has_extraction_without_base_url(data_dir: Path) -> None:
    recorded = load(data_dir).settings_for_run()["extraction"]
    assert "base_url" not in recorded
    assert recorded == {k: v for k, v in DEFAULTS.items() if k != "base_url"}


def test_extraction_section_does_not_touch_other_sections(data_dir: Path) -> None:
    s = load(data_dir, "[extraction]\nseed = 1\n")
    assert s.structure == load_settings({"DOCREADER_DATA_DIR": str(data_dir)}).structure
