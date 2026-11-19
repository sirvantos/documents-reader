"""Guards that keep the recognition engine off this server (research R-4, task T009)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from docreader import ocr_engines
from docreader.config import RecognitionSettings
from docreader.errors import EnvironmentProblem

FORBID = "DOCREADER_FORBID_MODELS"
OFFLINE_VARS = (
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "HF_HUB_DISABLE_TELEMETRY",
    "DISABLE_TELEMETRY",
)


class _Spy:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.calls = 0
        self.result = result
        self.error = error
        self.env_seen: dict[str, str | None] = {}

    def __call__(self, settings: RecognitionSettings, data_dir: Path):
        self.calls += 1
        self.env_seen = {name: os.environ.get(name) for name in OFFLINE_VARS}
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> _Spy:
    factory = _Spy(result=object())
    monkeypatch.setitem(ocr_engines.ENGINES, "spy", factory)
    for name in OFFLINE_VARS:
        monkeypatch.delenv(name, raising=False)  # restored after the test
    return factory


def _settings(engine: str) -> RecognitionSettings:
    return RecognitionSettings(engine=engine)


def test_empty_engine_name_is_not_chosen(tmp_path: Path, spy: _Spy) -> None:
    with pytest.raises(EnvironmentProblem) as err:
        ocr_engines.load_engine(_settings(""), tmp_path)
    assert str(err.value) == (
        "Не выбран движок распознавания — укажите [recognition] engine в settings.toml "
        "(выбор — замером, quickstart Б1)"
    )
    assert spy.calls == 0


def test_unknown_engine_lists_the_known_names(tmp_path: Path, spy: _Spy) -> None:
    with pytest.raises(EnvironmentProblem) as err:
        ocr_engines.load_engine(_settings("bogus"), tmp_path)
    assert "bogus" in str(err.value)
    for name in ocr_engines.ENGINES:
        assert name in str(err.value)


def test_fixture_forbids_models_in_every_ordinary_test() -> None:
    assert os.environ.get(FORBID) == "1"


@pytest.mark.parametrize("name", [*ocr_engines.ENGINES, "spy"])
def test_forbidden_on_this_machine_for_every_engine(
    name: str, tmp_path: Path, spy: _Spy
) -> None:
    with pytest.raises(EnvironmentProblem) as err:
        ocr_engines.load_engine(_settings(name), tmp_path)
    assert str(err.value) == (
        "На этой машине движок распознавания не запускается (DOCREADER_FORBID_MODELS)"
    )
    assert spy.calls == 0


def test_forbid_variable_with_any_non_empty_value_forbids(
    tmp_path: Path, spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FORBID, "yes")
    with pytest.raises(EnvironmentProblem):
        ocr_engines.load_engine(_settings("spy"), tmp_path)
    assert spy.calls == 0


def test_without_the_guard_the_factory_runs_offline(
    tmp_path: Path, spy: _Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(FORBID)

    engine = ocr_engines.load_engine(_settings("spy"), tmp_path)

    assert engine is spy.result
    assert spy.calls == 1
    assert spy.env_seen == dict.fromkeys(OFFLINE_VARS, "1")


def test_import_error_becomes_an_environment_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(FORBID)
    monkeypatch.setitem(
        ocr_engines.ENGINES, "spy", _Spy(error=ImportError("No module named 'tesserocr'"))
    )
    with pytest.raises(EnvironmentProblem) as err:
        ocr_engines.load_engine(_settings("spy"), tmp_path)
    assert "spy" in str(err.value) and "не установлен" in str(err.value)
    assert "uv sync --group ocr" in str(err.value)


def test_factory_hint_is_passed_through(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FORBID)
    hint = EnvironmentProblem("движок spy: нет языковых данных в /x — установите их")
    monkeypatch.setitem(ocr_engines.ENGINES, "spy", _Spy(error=hint))
    with pytest.raises(EnvironmentProblem) as err:
        ocr_engines.load_engine(_settings("spy"), tmp_path)
    assert err.value is hint
