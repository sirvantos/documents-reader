"""Settings of the [structure] section (feature 04, data-model «Настройки», research R-10)."""

import json
from pathlib import Path

import pytest

from docreader.config import StructureSettings, load_settings
from docreader.errors import EnvironmentProblem

DEFAULT_PATTERN = r"реквизит|подписи\s+сторон|адреса\s+сторон|юридические\s+адреса"
DEFAULT_STRUCTURE = {"max_gap": 5, "requisites_pattern": DEFAULT_PATTERN}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def env_for(data_dir: Path) -> dict[str, str]:
    return {"DOCREADER_DATA_DIR": str(data_dir)}


def write_settings(data_dir: Path, text: str) -> None:
    (data_dir / "settings.toml").write_text(text, encoding="utf-8")


def structure_of(settings) -> dict:
    return {name: getattr(settings.structure, name) for name in DEFAULT_STRUCTURE}


# --- defaults and overrides ----------------------------------------------------


def test_structure_defaults_without_section(data_dir: Path) -> None:
    settings = load_settings(env_for(data_dir))
    assert isinstance(settings.structure, StructureSettings)
    assert structure_of(settings) == DEFAULT_STRUCTURE


def test_structure_defaults_match_dataclass_defaults() -> None:
    assert StructureSettings() == StructureSettings(**DEFAULT_STRUCTURE)


def test_structure_settings_is_frozen() -> None:
    with pytest.raises(AttributeError):
        StructureSettings().max_gap = 3  # type: ignore[misc]


def test_structure_overrides_applied(data_dir: Path) -> None:
    write_settings(
        data_dir,
        "[structure]\nmax_gap = 0\nrequisites_pattern = \"реквизиты сторон\"\n",
    )
    settings = load_settings(env_for(data_dir))
    assert structure_of(settings) == {"max_gap": 0, "requisites_pattern": "реквизиты сторон"}


def test_structure_max_gap_upper_bound_accepted(data_dir: Path) -> None:
    write_settings(data_dir, "[structure]\nmax_gap = 20\n")
    assert load_settings(env_for(data_dir)).structure.max_gap == 20


def test_structure_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    write_settings(data_dir, "[structure]\nmax_gap = 3\n")
    settings = load_settings(env_for(data_dir))
    assert structure_of(settings) == dict(DEFAULT_STRUCTURE, max_gap=3)


def test_empty_structure_section_gives_defaults(data_dir: Path) -> None:
    write_settings(data_dir, "[structure]\n")
    assert structure_of(load_settings(env_for(data_dir))) == DEFAULT_STRUCTURE


def test_structure_section_does_not_touch_other_sections(data_dir: Path) -> None:
    write_settings(data_dir, "[intake]\nlarge_file_pages = 3\n[structure]\nmax_gap = 4\n")
    settings = load_settings(env_for(data_dir))
    assert settings.large_file_pages == 3
    assert settings.structure.max_gap == 4


# --- unknown keys and invalid values -----------------------------------------


def test_unknown_structure_key_rejected(data_dir: Path) -> None:
    write_settings(data_dir, "[structure]\nmin_gap = 1\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


@pytest.mark.parametrize("line", ["max_gap = -1", "max_gap = 21"])
def test_structure_max_gap_out_of_range_rejected(data_dir: Path, line: str) -> None:
    write_settings(data_dir, f"[structure]\n{line}\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


@pytest.mark.parametrize("line", ["max_gap = 2.5", 'max_gap = "5"', "max_gap = true"])
def test_structure_max_gap_wrong_type_rejected(data_dir: Path, line: str) -> None:
    write_settings(data_dir, f"[structure]\n{line}\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


def test_structure_empty_pattern_rejected(data_dir: Path) -> None:
    write_settings(data_dir, '[structure]\nrequisites_pattern = "   "\n')
    with pytest.raises(EnvironmentProblem, match=r"structure\.requisites_pattern"):
        load_settings(env_for(data_dir))


def test_structure_pattern_that_does_not_compile_rejected(data_dir: Path) -> None:
    write_settings(data_dir, '[structure]\nrequisites_pattern = "("\n')
    with pytest.raises(EnvironmentProblem, match=r"structure\.requisites_pattern"):
        load_settings(env_for(data_dir))


def test_structure_pattern_wrong_type_rejected(data_dir: Path) -> None:
    write_settings(data_dir, "[structure]\nrequisites_pattern = 5\n")
    with pytest.raises(EnvironmentProblem, match=r"structure\.requisites_pattern"):
        load_settings(env_for(data_dir))


def test_structure_as_non_table_rejected(data_dir: Path) -> None:
    write_settings(data_dir, "structure = 1\n")
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


# --- settings_for_run ----------------------------------------------------------


def test_settings_for_run_contains_structure_defaults(data_dir: Path) -> None:
    resolved = load_settings(env_for(data_dir)).settings_for_run()
    assert resolved["structure"] == DEFAULT_STRUCTURE
    assert json.loads(json.dumps(resolved))["structure"] == DEFAULT_STRUCTURE


def test_settings_for_run_structure_matches_resolved_values(data_dir: Path) -> None:
    write_settings(data_dir, '[structure]\nmax_gap = 7\nrequisites_pattern = "подписи"\n')
    resolved = load_settings(env_for(data_dir)).settings_for_run()
    expected = {"max_gap": 7, "requisites_pattern": "подписи"}
    assert resolved["structure"] == expected
    assert json.loads(json.dumps(resolved["structure"])) == expected
