"""The recording command of feature 09 refuses anything but synthetic input (task T017).

Principle I, guard in code (tech-context «Модели в автотестах»): the contracts are written
only inside tests/synthetic/, checked before settings, the database or the model are
touched; the model address only on this machine; no real model on a machine with
DOCREADER_FORBID_MODELS. Written by the main session; not to be edited by the implementer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from docreader import llm
from tests.synthetic import make_pdfs, record_answers

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

    monkeypatch.setattr(record_answers, "load_settings", count("load_settings"))
    monkeypatch.setattr(llm, "load_client", count("load_client"))
    monkeypatch.setattr(record_answers, "record", count("record"))
    return calls


def _env(**extra: str) -> dict[str, str]:
    return {"DOCREADER_TEST_DATABASE_URL": "postgresql:///postgres", **extra}


def test_defaults() -> None:
    assert record_answers.SYNTHETIC_DIR == Path(make_pdfs.__file__).resolve().parent
    assert record_answers.RECORDINGS_DIR.parts[-2:] == ("recordings", "09-text-answers")


def test_out_dir_outside_synthetic_refused(tmp_path, synthetic, spies, capsys) -> None:
    code = record_answers.main(
        ["--out", str(tmp_path / "elsewhere")], synthetic_dir=synthetic, env=_env()
    )
    assert code == 1
    assert REFUSED in capsys.readouterr().err
    assert spies == {"load_settings": 0, "load_client": 0, "record": 0}


def test_out_dir_escaping_with_dots_refused(synthetic, spies, capsys) -> None:
    code = record_answers.main(
        ["--out", str(synthetic / "out" / ".." / "..")], synthetic_dir=synthetic, env=_env()
    )
    assert code == 1
    assert REFUSED in capsys.readouterr().err


def test_symlink_out_of_synthetic_refused(tmp_path, synthetic, spies, capsys) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = synthetic / "link"
    link.symlink_to(target, target_is_directory=True)
    code = record_answers.main(["--out", str(link)], synthetic_dir=synthetic, env=_env())
    assert code == 1
    assert REFUSED in capsys.readouterr().err


def test_without_test_database_refused(synthetic, spies, capsys) -> None:
    code = record_answers.main([], synthetic_dir=synthetic, env={})
    assert code == 2
    assert "DOCREADER_TEST_DATABASE_URL" in capsys.readouterr().err
    assert spies["record"] == 0


def test_non_loopback_model_address_refused(synthetic, spies, capsys) -> None:
    code = record_answers.main(
        [], synthetic_dir=synthetic, env=_env(DOCREADER_RECORD_BASE_URL="http://10.0.0.5:8080/v1")
    )
    assert code == 2
    assert "принцип I" in capsys.readouterr().err
    assert spies["record"] == 0


def test_forbidden_machine_without_a_transport_refused(synthetic, spies, capsys) -> None:
    code = record_answers.main(
        [], synthetic_dir=synthetic, env=_env(DOCREADER_FORBID_MODELS="1")
    )
    assert code == 2
    assert "DOCREADER_FORBID_MODELS" in capsys.readouterr().err
    assert spies["record"] == 0


def test_unknown_variant_refused(synthetic, spies) -> None:
    with pytest.raises(SystemExit):
        record_answers.main(["nonsense"], synthetic_dir=synthetic, env=_env())
    assert spies["record"] == 0
