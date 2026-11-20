"""Settings of the [recognition] section (feature 13, data-model «Настройки»)."""

import json
from pathlib import Path

import pytest

from docreader.config import ReadingSettings, RecognitionSettings, load_settings
from docreader.errors import EnvironmentProblem

DEFAULT_RECOGNITION = {
    "engine": "tesseract",
    "dpi": 300,
    "try_rotations": True,
    "page_min_quality": 0.80,
    "line_min_confidence": 0.60,
    "max_low_line_share": 0.20,
    "blank_max_ink_share": 0.003,
    "model_dir": "",
}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def env_for(data_dir: Path) -> dict[str, str]:
    return {"DOCREADER_DATA_DIR": str(data_dir)}


def write_settings(data_dir: Path, text: str) -> None:
    (data_dir / "settings.toml").write_text(text, encoding="utf-8")


def recognition_of(settings) -> dict:
    return {name: getattr(settings.recognition, name) for name in DEFAULT_RECOGNITION}


# --- defaults and overrides ----------------------------------------------------


def test_recognition_defaults_without_section(data_dir: Path) -> None:
    settings = load_settings(env_for(data_dir))
    assert isinstance(settings.recognition, RecognitionSettings)
    assert recognition_of(settings) == DEFAULT_RECOGNITION


def test_recognition_dataclass_defaults_match_data_model() -> None:
    assert RecognitionSettings() == RecognitionSettings(**DEFAULT_RECOGNITION)


def test_recognition_settings_is_frozen() -> None:
    with pytest.raises(AttributeError):
        RecognitionSettings().dpi = 200  # type: ignore[misc]


def test_recognition_overrides_applied(data_dir: Path) -> None:
    write_settings(
        data_dir,
        "[recognition]\n"
        'engine = "engine-a"\n'
        "dpi = 240\n"
        "try_rotations = false\n"
        "page_min_quality = 0.7\n"
        "line_min_confidence = 0.5\n"
        "max_low_line_share = 0.1\n"
        "blank_max_ink_share = 0.01\n"
        'model_dir = "/models"\n',
    )
    settings = load_settings(env_for(data_dir))
    assert recognition_of(settings) == {
        "engine": "engine-a",
        "dpi": 240,
        "try_rotations": False,
        "page_min_quality": 0.7,
        "line_min_confidence": 0.5,
        "max_low_line_share": 0.1,
        "blank_max_ink_share": 0.01,
        "model_dir": "/models",
    }


def test_recognition_float_fields_accept_integers(data_dir: Path) -> None:
    write_settings(data_dir, "[recognition]\npage_min_quality = 1\nmax_low_line_share = 0\n")
    settings = load_settings(env_for(data_dir))
    assert settings.recognition.page_min_quality == 1.0
    assert settings.recognition.max_low_line_share == 0.0
    assert isinstance(settings.recognition.page_min_quality, float)


def test_recognition_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    write_settings(data_dir, "[recognition]\ndpi = 150\n")
    settings = load_settings(env_for(data_dir))
    assert recognition_of(settings) == dict(DEFAULT_RECOGNITION, dpi=150)


def test_empty_recognition_section_gives_defaults(data_dir: Path) -> None:
    write_settings(data_dir, "[recognition]\n")
    assert recognition_of(load_settings(env_for(data_dir))) == DEFAULT_RECOGNITION


def test_recognition_section_does_not_touch_other_sections(data_dir: Path) -> None:
    write_settings(data_dir, "[intake]\nlarge_file_pages = 3\n[recognition]\ndpi = 200\n")
    settings = load_settings(env_for(data_dir))
    assert settings.large_file_pages == 3
    assert settings.recognition.dpi == 200
    assert settings.reading == ReadingSettings()


def test_engine_name_is_not_checked_here(data_dir: Path) -> None:
    write_settings(data_dir, '[recognition]\nengine = "any-name-at-all"\n')
    assert load_settings(env_for(data_dir)).recognition.engine == "any-name-at-all"


def test_dpi_bounds_accepted(data_dir: Path) -> None:
    write_settings(data_dir, "[recognition]\ndpi = 72\n")
    assert load_settings(env_for(data_dir)).recognition.dpi == 72
    write_settings(data_dir, "[recognition]\ndpi = 1200\n")
    assert load_settings(env_for(data_dir)).recognition.dpi == 1200


@pytest.mark.parametrize(
    "line",
    [
        "page_min_quality = 0",
        "page_min_quality = 1",
        "line_min_confidence = 0",
        "line_min_confidence = 1",
        "max_low_line_share = 0",
        "max_low_line_share = 1",
        "blank_max_ink_share = 0",
        "blank_max_ink_share = 1",
    ],
)
def test_share_bounds_accepted(data_dir: Path, line: str) -> None:
    write_settings(data_dir, f"[recognition]\n{line}\n")
    load_settings(env_for(data_dir))


# --- type errors ---------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "dpi = true",
        "dpi = 300.0",
        'dpi = "300"',
        "page_min_quality = true",
        'page_min_quality = "0.8"',
        "line_min_confidence = false",
        "max_low_line_share = \"0.2\"",
        "blank_max_ink_share = true",
        "try_rotations = 1",
        'try_rotations = "true"',
        "try_rotations = 0.0",
        "engine = 1",
        "engine = true",
        'engine = ["a"]',
        "model_dir = 1.5",
        "model_dir = false",
    ],
)
def test_recognition_wrong_type_rejected(data_dir: Path, line: str) -> None:
    write_settings(data_dir, f"[recognition]\n{line}\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


# --- ranges ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "dpi = 71",
        "dpi = 1201",
        "dpi = 0",
        "dpi = -300",
        "page_min_quality = -0.1",
        "page_min_quality = 1.01",
        "line_min_confidence = -0.5",
        "line_min_confidence = 2",
        "max_low_line_share = -1",
        "max_low_line_share = 1.5",
        "blank_max_ink_share = -0.001",
        "blank_max_ink_share = 1.001",
    ],
)
def test_recognition_out_of_range_rejected(data_dir: Path, line: str) -> None:
    write_settings(data_dir, f"[recognition]\n{line}\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


# --- unknown keys and sections ---------------------------------------------------


def test_unknown_recognition_key_rejected(data_dir: Path) -> None:
    write_settings(data_dir, "[recognition]\nthreshold = 0.5\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


def test_recognition_as_non_table_rejected(data_dir: Path) -> None:
    write_settings(data_dir, "recognition = 1\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


# --- settings_for_run ----------------------------------------------------------


def test_settings_for_run_contains_recognition_defaults(data_dir: Path) -> None:
    resolved = load_settings(env_for(data_dir)).settings_for_run()
    assert resolved["recognition"] == DEFAULT_RECOGNITION
    assert json.loads(json.dumps(resolved))["recognition"] == DEFAULT_RECOGNITION


def test_settings_for_run_recognition_matches_resolved_values(data_dir: Path) -> None:
    write_settings(data_dir, '[recognition]\ndpi = 400\ntry_rotations = false\nengine = "x"\n')
    resolved = load_settings(env_for(data_dir)).settings_for_run()
    expected = dict(DEFAULT_RECOGNITION, dpi=400, try_rotations=False, engine="x")
    assert resolved["recognition"] == expected
    assert json.loads(json.dumps(resolved["recognition"])) == expected
