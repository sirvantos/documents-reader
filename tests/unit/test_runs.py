import importlib.metadata
import subprocess

from docreader import runs


def test_code_version_non_empty():
    runs.code_version.cache_clear()
    assert runs.code_version().strip()


def test_code_version_falls_back_when_git_missing(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    runs.code_version.cache_clear()
    try:
        assert runs.code_version() == importlib.metadata.version("docreader")
    finally:
        runs.code_version.cache_clear()
