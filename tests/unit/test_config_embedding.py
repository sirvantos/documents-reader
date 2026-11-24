"""Settings of the [embedding] section (feature 07, research R-9; task T005).

The loopback check of `base_url` is a privacy guard (principle I): the search model may
only be reached on this machine. Written by the main session.
"""

from dataclasses import asdict
from pathlib import Path

import pytest

from docreader.config import EmbeddingSettings, ExtractionSettings, load_settings
from docreader.errors import EnvironmentProblem

DEFAULTS = {
    "base_url": "http://127.0.0.1:8081/v1",
    "model": "bge-m3",
    "timeout_s": 120,
    "batch_size": 16,
    "max_chars": 16000,
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


def test_defaults_without_section(data_dir: Path) -> None:
    assert asdict(load(data_dir).embedding) == DEFAULTS


def test_dataclass_defaults_match() -> None:
    assert asdict(EmbeddingSettings()) == DEFAULTS


def test_overrides_applied(data_dir: Path) -> None:
    s = load(
        data_dir,
        '[embedding]\nbase_url = "http://localhost:9001/v1"\nmodel = "frida"\n'
        "timeout_s = 5\nbatch_size = 1\nmax_chars = 100\n",
    ).embedding
    assert asdict(s) == {
        "base_url": "http://localhost:9001/v1",
        "model": "frida",
        "timeout_s": 5,
        "batch_size": 1,
        "max_chars": 100,
    }


def test_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    s = load(data_dir, "[embedding]\nbatch_size = 4\n").embedding
    assert asdict(s) == {**DEFAULTS, "batch_size": 4}


@pytest.mark.parametrize(
    "line",
    [
        "timeout_s = 0",
        "timeout_s = -1",
        "batch_size = 0",
        "max_chars = 0",
        "max_chars = -5",
        'model = ""',
        'model = "  "',
        'batch_size = "16"',
        "max_chars = 1.5",
        "timeout_s = true",
    ],
)
def test_out_of_range_or_wrong_type_rejected(data_dir: Path, line: str) -> None:
    with pytest.raises(EnvironmentProblem, match=r"embedding\."):
        load(data_dir, f"[embedding]\n{line}\n")


def test_unknown_key_rejected(data_dir: Path) -> None:
    with pytest.raises(EnvironmentProblem, match=r"embedding\.api_key"):
        load(data_dir, '[embedding]\napi_key = "x"\n')


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5:8081/v1",
        "https://api.example.com/v1",
        "http://user@127.0.0.1:8081/v1",
        "ftp://127.0.0.1/v1",
        "127.0.0.1:8081",
    ],
)
def test_non_local_base_url_rejected(data_dir: Path, url: str) -> None:
    with pytest.raises(EnvironmentProblem, match=r"embedding\.base_url"):
        load(data_dir, f'[embedding]\nbase_url = "{url}"\n')


def test_settings_for_run_has_embedding_without_base_url(data_dir: Path) -> None:
    recorded = load(data_dir).settings_for_run()["embedding"]
    assert recorded == {k: v for k, v in DEFAULTS.items() if k != "base_url"}


def test_embedding_section_does_not_touch_other_sections(data_dir: Path) -> None:
    s = load(data_dir, "[embedding]\nbatch_size = 2\n")
    assert s.extraction == ExtractionSettings()
