"""Settings of the [reading] section (feature 02, data-model «Настройки», research R-13)."""

import json
from pathlib import Path

import pytest

from docreader.config import ReadingSettings, load_settings
from docreader.errors import EnvironmentProblem

DEFAULT_READING = {
    "header_band": 0.1,
    "header_min_share": 0.5,
    "header_min_pages": 3,
    "non_russian_min_letters": 3,
    "unreadable_min_letter_share": 0.6,
    "unreadable_max_bad_share": 0.05,
    "unreadable_max_vowelless_share": 0.4,
    "column_min_lines": 3,
    "column_min_gap": 20.0,
    "column_gap_tolerance": 15.0,
    "wide_gap_factor": 2.5,
    "rotated_min_angle": 5.0,
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


def reading_of(settings) -> dict:
    return {name: getattr(settings.reading, name) for name in DEFAULT_READING}


# --- defaults and overrides ----------------------------------------------------


def test_reading_defaults_without_section(data_dir: Path) -> None:
    settings = load_settings(env_for(data_dir))
    assert isinstance(settings.reading, ReadingSettings)
    assert reading_of(settings) == DEFAULT_READING


def test_reading_defaults_without_settings_file_match_dataclass_defaults() -> None:
    assert ReadingSettings() == ReadingSettings(**DEFAULT_READING)


def test_reading_settings_is_frozen() -> None:
    with pytest.raises(AttributeError):
        ReadingSettings().header_band = 0.2  # type: ignore[misc]


def test_reading_overrides_applied(data_dir: Path) -> None:
    write_settings(
        data_dir,
        "[reading]\n"
        "header_band = 0.2\n"
        "header_min_share = 0.7\n"
        "header_min_pages = 5\n"
        "non_russian_min_letters = 4\n"
        "unreadable_min_letter_share = 0.5\n"
        "unreadable_max_bad_share = 0.1\n"
        "unreadable_max_vowelless_share = 0.3\n"
        "column_min_lines = 4\n"
        "column_min_gap = 30.5\n"
        "column_gap_tolerance = 10\n"
        "wide_gap_factor = 3\n"
        "rotated_min_angle = 7.5\n",
    )
    settings = load_settings(env_for(data_dir))
    assert reading_of(settings) == {
        "header_band": 0.2,
        "header_min_share": 0.7,
        "header_min_pages": 5,
        "non_russian_min_letters": 4,
        "unreadable_min_letter_share": 0.5,
        "unreadable_max_bad_share": 0.1,
        "unreadable_max_vowelless_share": 0.3,
        "column_min_lines": 4,
        "column_min_gap": 30.5,
        "column_gap_tolerance": 10.0,
        "wide_gap_factor": 3.0,
        "rotated_min_angle": 7.5,
    }


def test_reading_float_fields_accept_integers(data_dir: Path) -> None:
    write_settings(data_dir, "[reading]\nheader_band = 1\nrotated_min_angle = 0\n")
    settings = load_settings(env_for(data_dir))
    assert settings.reading.header_band == 1.0
    assert settings.reading.rotated_min_angle == 0.0


def test_reading_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    write_settings(data_dir, "[reading]\ncolumn_min_lines = 2\n")
    settings = load_settings(env_for(data_dir))
    expected = dict(DEFAULT_READING, column_min_lines=2)
    assert reading_of(settings) == expected


def test_empty_reading_section_gives_defaults(data_dir: Path) -> None:
    write_settings(data_dir, "[reading]\n")
    assert reading_of(load_settings(env_for(data_dir))) == DEFAULT_READING


def test_reading_section_does_not_touch_other_sections(data_dir: Path) -> None:
    write_settings(data_dir, "[intake]\nlarge_file_pages = 3\n[reading]\nheader_min_pages = 4\n")
    settings = load_settings(env_for(data_dir))
    assert settings.large_file_pages == 3
    assert settings.reading.header_min_pages == 4


# --- unknown keys and invalid values -----------------------------------------


def test_unknown_reading_key_rejected(data_dir: Path) -> None:
    write_settings(data_dir, "[reading]\nheader_colour = 1\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


@pytest.mark.parametrize(
    "line",
    [
        "header_band = 0",
        "header_band = 1.01",
        "header_band = -0.1",
        "header_min_share = 0",
        "header_min_share = 1.5",
        "header_min_pages = 0",
        "non_russian_min_letters = 0",
        "unreadable_min_letter_share = 0",
        "unreadable_min_letter_share = 2",
        "unreadable_max_bad_share = 0",
        "unreadable_max_bad_share = 1.5",
        "unreadable_max_vowelless_share = 0",
        "unreadable_max_vowelless_share = 1.01",
        "column_min_lines = 1",
        "column_min_gap = -1",
        "column_gap_tolerance = -0.5",
        "rotated_min_angle = -1",
        "rotated_min_angle = 90",
        "rotated_min_angle = 100",
    ],
)
def test_reading_out_of_range_rejected(data_dir: Path, line: str) -> None:
    write_settings(data_dir, f"[reading]\n{line}\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


@pytest.mark.parametrize(
    "line",
    [
        "header_min_pages = true",
        "non_russian_min_letters = true",
        "column_min_lines = true",
        "column_min_lines = 2.5",
        "header_min_pages = \"3\"",
        "header_band = true",
        "column_min_gap = \"20\"",
    ],
)
def test_reading_wrong_type_rejected(data_dir: Path, line: str) -> None:
    write_settings(data_dir, f"[reading]\n{line}\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


def test_reading_as_non_table_rejected(data_dir: Path) -> None:
    write_settings(data_dir, "reading = 1\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


# --- settings_for_run ----------------------------------------------------------


def test_settings_for_run_contains_reading_defaults(data_dir: Path) -> None:
    resolved = load_settings(env_for(data_dir)).settings_for_run()
    assert resolved["reading"] == DEFAULT_READING
    assert json.loads(json.dumps(resolved))["reading"] == DEFAULT_READING


def test_settings_for_run_reading_matches_resolved_values(data_dir: Path) -> None:
    write_settings(data_dir, "[reading]\nheader_min_pages = 6\ncolumn_min_gap = 25\n")
    resolved = load_settings(env_for(data_dir)).settings_for_run()
    expected = dict(DEFAULT_READING, header_min_pages=6, column_min_gap=25.0)
    assert resolved["reading"] == expected
    assert json.loads(json.dumps(resolved["reading"])) == expected
