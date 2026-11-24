"""Settings of the [search] and [reranker] sections (feature 08, research R-9; task T002).

The loopback check of `[reranker] base_url` is a privacy guard (principle I): the
reranker may only be reached on this machine. Written by the main session.
"""

from dataclasses import asdict
from pathlib import Path

import pytest

from docreader.config import RerankerSettings, SearchSettings, load_settings
from docreader.errors import EnvironmentProblem

SEARCH_DEFAULTS = {"candidates": 30, "rrf_k": 60, "rerank_candidates": 30, "results": 8}
RERANKER_DEFAULTS = {
    "enabled": True,
    "base_url": "http://127.0.0.1:8082/v1",
    "model": "bge-reranker-v2-m3",
    "timeout_s": 60,
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


def test_defaults_without_sections(data_dir: Path) -> None:
    s = load(data_dir)
    assert asdict(s.search) == SEARCH_DEFAULTS
    assert asdict(s.reranker) == RERANKER_DEFAULTS


def test_dataclass_defaults_match() -> None:
    assert asdict(SearchSettings()) == SEARCH_DEFAULTS
    assert asdict(RerankerSettings()) == RERANKER_DEFAULTS


def test_overrides_applied(data_dir: Path) -> None:
    s = load(
        data_dir,
        "[search]\ncandidates = 10\nrrf_k = 5\nrerank_candidates = 12\nresults = 3\n"
        '[reranker]\nenabled = false\nbase_url = "http://localhost:9002/v1"\n'
        'model = "other"\ntimeout_s = 5\nmax_chars = 100\n',
    )
    assert asdict(s.search) == {
        "candidates": 10, "rrf_k": 5, "rerank_candidates": 12, "results": 3
    }
    assert asdict(s.reranker) == {
        "enabled": False,
        "base_url": "http://localhost:9002/v1",
        "model": "other",
        "timeout_s": 5,
        "max_chars": 100,
    }


def test_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    s = load(data_dir, "[search]\nresults = 5\n[reranker]\nenabled = false\n")
    assert s.search.results == 5 and s.search.candidates == 30
    assert s.reranker.enabled is False and s.reranker.model == "bge-reranker-v2-m3"


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("candidates = 1", True),
        ("candidates = 500", True),
        ("candidates = 0", False),
        ("candidates = 501", False),
        ("rrf_k = 1", True),
        ("rrf_k = 1000", True),
        ("rrf_k = 0", False),
        ("rrf_k = 1001", False),
        ("rerank_candidates = 200", True),
        ("rerank_candidates = 201", False),
        ("rerank_candidates = 0", False),
        ("results = 1", True),
        ("results = 0", False),
        ("candidates = 2.5", False),
        ("results = true", False),
    ],
)
def test_search_bounds(data_dir: Path, line: str, ok: bool) -> None:
    text = f"[search]\n{line}\n"
    if ok:
        load(data_dir, text)
    else:
        with pytest.raises(EnvironmentProblem, match="search"):
            load(data_dir, text)


def test_results_not_above_rerank_candidates(data_dir: Path) -> None:
    load(data_dir, "[search]\nrerank_candidates = 10\nresults = 10\n")
    with pytest.raises(EnvironmentProblem, match="results"):
        load(data_dir, "[search]\nrerank_candidates = 10\nresults = 11\n")
    # the default rerank_candidates (30) bounds results too
    with pytest.raises(EnvironmentProblem, match="results"):
        load(data_dir, "[search]\nresults = 31\n")


@pytest.mark.parametrize(
    ("line", "ok"),
    [
        ("timeout_s = 1", True),
        ("timeout_s = 3600", True),
        ("timeout_s = 0", False),
        ("timeout_s = 3601", False),
        ("max_chars = 1", True),
        ("max_chars = 1000000", True),
        ("max_chars = 0", False),
        ("max_chars = 1000001", False),
        ('model = ""', False),
        ('model = "   "', False),
        ('enabled = "yes"', False),
        ("enabled = 1", False),
    ],
)
def test_reranker_bounds(data_dir: Path, line: str, ok: bool) -> None:
    text = f"[reranker]\n{line}\n"
    if ok:
        load(data_dir, text)
    else:
        with pytest.raises(EnvironmentProblem, match="reranker"):
            load(data_dir, text)


@pytest.mark.parametrize(
    "url",
    [
        "http://192.168.1.5:8082/v1",
        "http://example.com/v1",
        "https://api.example.org/v1",
        "ftp://127.0.0.1/v1",
    ],
)
def test_reranker_base_url_must_be_local(data_dir: Path, url: str) -> None:
    with pytest.raises(EnvironmentProblem, match="принцип I"):
        load(data_dir, f'[reranker]\nbase_url = "{url}"\n')


@pytest.mark.parametrize("url", ["http://localhost:8082/v1", "http://[::1]:8082/v1"])
def test_reranker_local_urls_accepted(data_dir: Path, url: str) -> None:
    assert load(data_dir, f'[reranker]\nbase_url = "{url}"\n').reranker.base_url == url


@pytest.mark.parametrize("table", ["search", "reranker"])
def test_unknown_key_named(data_dir: Path, table: str) -> None:
    with pytest.raises(EnvironmentProblem, match=f"{table}.top_k"):
        load(data_dir, f"[{table}]\ntop_k = 3\n")



def test_not_recorded_in_stage_runs(data_dir: Path) -> None:
    # search writes no run (research R-10): its settings are shown by the measurement
    recorded = load(data_dir).settings_for_run()
    assert "search" not in recorded and "reranker" not in recorded
