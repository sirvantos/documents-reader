"""The recording command of feature 05 refuses anything but synthetic input (task T024).

Principle I, guard in code (tech-context «Модели в автотестах»): only files inside
tests/synthetic/, checked before settings, the database or the model are touched; the
model address only on this machine; no real model on a machine with
DOCREADER_FORBID_MODELS. Written by the main session; not to be edited by the implementer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docreader import llm
from tests.fakes.llm import request_sha256 as fakes_request_sha256
from tests.synthetic import make_pdfs, record_extraction

REFUSED = "записываются только синтетические файлы из tests/synthetic/"


@pytest.fixture
def synthetic(tmp_path: Path) -> Path:
    d = tmp_path / "synthetic"
    (d / "out").mkdir(parents=True)
    return d


@pytest.fixture
def spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls = {"load_settings": 0, "load_client": 0, "record": 0}

    def count(name):
        def spy(*args, **kwargs):
            calls[name] += 1
            raise AssertionError(f"{name} must not be called")

        return spy

    monkeypatch.setattr(record_extraction, "load_settings", count("load_settings"))
    monkeypatch.setattr(llm, "load_client", count("load_client"))
    monkeypatch.setattr(record_extraction, "record", count("record"))
    return calls


def _env(**extra: str) -> dict[str, str]:
    return {"DOCREADER_TEST_DATABASE_URL": "postgresql:///postgres", **extra}


def test_real_synthetic_dir_is_the_default() -> None:
    assert record_extraction.SYNTHETIC_DIR == Path(make_pdfs.__file__).resolve().parent
    assert record_extraction.RECORDINGS_DIR.parts[-2:] == ("recordings", "05-field-extraction")


@pytest.mark.parametrize("where", ["outside", "dotdot", "symlink"])
def test_paths_outside_synthetic_are_refused_first(
    where: str, tmp_path: Path, synthetic: Path, spies, capsys
) -> None:
    outside = make_pdfs.make_extraction_contract(tmp_path / "real.pdf")
    if where == "outside":
        path = outside
    elif where == "dotdot":
        path = synthetic / ".." / "real.pdf"
    else:
        path = synthetic / "out" / "link.pdf"
        path.symlink_to(outside)
    code = record_extraction.main([str(path)], synthetic_dir=synthetic, env=_env())
    assert code == 1
    assert REFUSED in capsys.readouterr().err
    assert spies == {"load_settings": 0, "load_client": 0, "record": 0}


def test_one_bad_path_refuses_all(tmp_path: Path, synthetic: Path, spies, capsys) -> None:
    inside = make_pdfs.make_extraction_contract(synthetic / "out" / "base.pdf")
    outside = make_pdfs.make_extraction_contract(tmp_path / "real.pdf")
    code = record_extraction.main(
        [str(inside), str(outside)], synthetic_dir=synthetic, env=_env()
    )
    assert code == 1
    assert spies["record"] == 0


def test_without_the_test_database(synthetic: Path, spies, capsys) -> None:
    code = record_extraction.main([], synthetic_dir=synthetic, env={})
    assert code == 2
    assert "DOCREADER_TEST_DATABASE_URL" in capsys.readouterr().err
    assert spies["record"] == 0


@pytest.mark.parametrize("url", ["http://10.0.0.5:8080/v1", "https://api.example.com/v1"])
def test_non_local_model_address_refused(synthetic: Path, spies, capsys, url: str) -> None:
    code = record_extraction.main(
        [], synthetic_dir=synthetic, env=_env(DOCREADER_RECORD_BASE_URL=url)
    )
    assert code == 2
    assert "DOCREADER_RECORD_BASE_URL" in capsys.readouterr().err
    assert spies == {"load_settings": 0, "load_client": 0, "record": 0}


def test_real_model_forbidden_on_this_machine(synthetic: Path, spies, capsys) -> None:
    code = record_extraction.main(
        [], synthetic_dir=synthetic, env=_env(DOCREADER_FORBID_MODELS="1")
    )
    assert code == 2
    assert "DOCREADER_FORBID_MODELS" in capsys.readouterr().err
    assert spies["record"] == 0


def test_request_sha256_is_the_one_of_the_fakes() -> None:
    assert record_extraction.request_sha256 is fakes_request_sha256


def test_request_sha256_canonical_form() -> None:
    body = {"messages": [{"role": "user", "content": "а"}], "model": "m", "temperature": 0,
            "seed": 0, "max_tokens": 10}
    assert record_extraction.request_sha256(body) == record_extraction.request_sha256(
        dict(reversed(list(body.items())))
    )
    assert record_extraction.request_sha256(body) != record_extraction.request_sha256(
        {**body, "max_tokens": 11}
    )
