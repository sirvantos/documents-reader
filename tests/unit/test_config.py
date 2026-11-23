"""Settings and privacy guards (research R-8, R-6 «Защита принципа I», FR-013)."""

import json
from pathlib import Path

import pytest

from docreader.config import REPO_ROOT, load_settings
from docreader.errors import EnvironmentProblem


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


def env_for(data_dir: Path, **extra: str) -> dict[str, str]:
    return {"DOCREADER_DATA_DIR": str(data_dir), **extra}


def write_settings(data_dir: Path, text: str) -> None:
    (data_dir / "settings.toml").write_text(text, encoding="utf-8")


# --- data folder -----------------------------------------------------------


def test_missing_data_dir_variable() -> None:
    with pytest.raises(EnvironmentProblem, match="DOCREADER_DATA_DIR"):
        load_settings({})


def test_empty_data_dir_variable() -> None:
    with pytest.raises(EnvironmentProblem, match="DOCREADER_DATA_DIR"):
        load_settings({"DOCREADER_DATA_DIR": "  "})


def test_repo_root_is_detected() -> None:
    assert REPO_ROOT is not None
    assert (REPO_ROOT / ".git").exists()
    assert (REPO_ROOT / "pyproject.toml").exists()


@pytest.mark.parametrize("inside", [".", "data", "tests/some/deep/folder"])
def test_data_dir_inside_repository_rejected(inside: str) -> None:
    # The path does not have to exist: the check runs before anything is created.
    with pytest.raises(EnvironmentProblem, match="репозитор"):
        load_settings({"DOCREADER_DATA_DIR": str(REPO_ROOT / inside)})


def test_data_dir_inside_repository_via_relative_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT / "tests")
    with pytest.raises(EnvironmentProblem, match="репозитор"):
        load_settings({"DOCREADER_DATA_DIR": "../somewhere"})


def test_data_dir_inside_git_repo_of_cwd_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Guard also holds when the package is installed outside the repository:
    # a data folder inside the git checkout the command is run from is rejected.
    other_repo = tmp_path / "checkout"
    (other_repo / ".git").mkdir(parents=True)
    monkeypatch.chdir(other_repo)
    with pytest.raises(EnvironmentProblem, match="репозитор"):
        load_settings({"DOCREADER_DATA_DIR": str(other_repo / "data")})


def test_data_dir_outside_repository_accepted(data_dir: Path) -> None:
    settings = load_settings(env_for(data_dir))
    assert settings.data_dir == data_dir.resolve()


def test_data_dir_tilde_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = load_settings({"DOCREADER_DATA_DIR": "~/docreader-data"})
    assert settings.data_dir == (tmp_path / "docreader-data").resolve()


def test_missing_data_dir_is_created(tmp_path: Path) -> None:
    target = tmp_path / "new" / "data"
    settings = load_settings({"DOCREADER_DATA_DIR": str(target)})
    assert target.is_dir()
    assert settings.data_dir == target.resolve()


def test_data_dir_that_is_a_file_rejected(tmp_path: Path) -> None:
    f = tmp_path / "file"
    f.write_text("x")
    with pytest.raises(EnvironmentProblem, match="DOCREADER_DATA_DIR"):
        load_settings({"DOCREADER_DATA_DIR": str(f)})


# --- database address --------------------------------------------------------


def test_database_url_default(data_dir: Path) -> None:
    assert load_settings(env_for(data_dir)).database_url == "postgresql:///docreader"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql:///docreader",
        "postgresql://%2Fvar%2Frun%2Fpostgresql/docreader",
        "postgresql:///docreader?host=/tmp",
        "postgresql://localhost/docreader",
        "postgresql://localhost:5433/docreader",
        "postgresql://user:pw@127.0.0.1/docreader",
        "postgresql://[::1]/docreader",
        "host=localhost dbname=docreader",
        "dbname=docreader",
    ],
)
def test_local_database_accepted(data_dir: Path, url: str) -> None:
    settings = load_settings(env_for(data_dir, DOCREADER_DATABASE_URL=url))
    assert settings.database_url == url


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://db.example.com/docreader",
        "postgresql://10.0.0.5/docreader",
        "postgresql://localhost,db.example.com/docreader",
        "postgresql:///docreader?host=db.example.com",
        "postgresql:///docreader?hostaddr=10.0.0.5",
        "host=192.168.1.10 dbname=docreader",
        "postgresql:///docreader?service=remote",
    ],
)
def test_remote_database_rejected(data_dir: Path, url: str) -> None:
    with pytest.raises(EnvironmentProblem, match="локальн"):
        load_settings(env_for(data_dir, DOCREADER_DATABASE_URL=url))


@pytest.mark.parametrize(
    "var, value",
    [("PGHOST", "db.example.com"), ("PGHOSTADDR", "10.0.0.5"), ("PGSERVICE", "remote")],
)
def test_remote_database_via_libpq_environment_rejected(
    data_dir: Path, var: str, value: str
) -> None:
    # libpq falls back to PGHOST/PGHOSTADDR/PGSERVICE when the URL names no host.
    with pytest.raises(EnvironmentProblem, match="локальн"):
        load_settings(env_for(data_dir, **{var: value}))


def test_local_pghost_accepted(data_dir: Path) -> None:
    load_settings(env_for(data_dir, PGHOST="/var/run/postgresql"))


def test_unparseable_database_url_rejected(data_dir: Path) -> None:
    with pytest.raises(EnvironmentProblem, match="DOCREADER_DATABASE_URL"):
        load_settings(env_for(data_dir, DOCREADER_DATABASE_URL="postgresql://[bad"))


# --- settings.toml -----------------------------------------------------------


def test_defaults_without_settings_file(data_dir: Path) -> None:
    s = load_settings(env_for(data_dir))
    assert s.text_min_chars == 20
    assert s.full_image_coverage == 0.85
    assert s.large_file_pages == 200


def test_overrides_applied(data_dir: Path) -> None:
    write_settings(
        data_dir,
        "[page_kinds]\ntext_min_chars = 5\nfull_image_coverage = 1\n"
        "[intake]\nlarge_file_pages = 3\n",
    )
    s = load_settings(env_for(data_dir))
    assert (s.text_min_chars, s.full_image_coverage, s.large_file_pages) == (5, 1.0, 3)


def test_partial_override_keeps_other_defaults(data_dir: Path) -> None:
    write_settings(data_dir, "[page_kinds]\nfull_image_coverage = 0.9\n")
    s = load_settings(env_for(data_dir))
    assert (s.text_min_chars, s.full_image_coverage, s.large_file_pages) == (20, 0.9, 200)


@pytest.mark.parametrize(
    "text",
    [
        "[page_kinds]\ntext_min_chars = 0\n",
        "[page_kinds]\ntext_min_chars = 2.5\n",
        "[page_kinds]\ntext_min_chars = true\n",
        "[page_kinds]\nfull_image_coverage = 0\n",
        "[page_kinds]\nfull_image_coverage = 1.01\n",
        "[page_kinds]\nfull_image_coverage = \"0.8\"\n",
        "[intake]\nlarge_file_pages = 0\n",
        "[page_kinds]\nunknown_key = 1\n",
        "[unknown_table]\nx = 1\n",
        "page_kinds = 1\n",
        "this is not toml",
    ],
)
def test_bad_settings_rejected(data_dir: Path, text: str) -> None:
    write_settings(data_dir, text)
    with pytest.raises(EnvironmentProblem, match=r"settings\.toml"):
        load_settings(env_for(data_dir))


def test_settings_for_run_is_json_serialisable(data_dir: Path) -> None:
    write_settings(data_dir, "[page_kinds]\ntext_min_chars = 7\n")
    resolved = load_settings(env_for(data_dir)).settings_for_run()
    assert json.loads(json.dumps(resolved)) == {
        "page_kinds": {"text_min_chars": 7, "full_image_coverage": 0.85},
        "intake": {"large_file_pages": 200},
        "reading": {
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
        },
        "recognition": {
            "engine": "tesseract",
            "dpi": 300,
            "try_rotations": True,
            "page_min_quality": 0.9,
            "line_min_confidence": 0.6,
            "max_low_line_share": 0.2,
            "blank_max_ink_share": 0.003,
            "model_dir": "",
        },
        "structure": {
            "max_gap": 5,
            "requisites_pattern": r"реквизит|подписи\s+сторон|адреса\s+сторон|юридические\s+адреса",
        },
        "extraction": {  # feature 05; base_url is not recorded
            "model": "qwen3.6-27b-4bit",
            "mode": "md_json",
            "max_retries": 2,
            "timeout_s": 1800,
            "max_shown_chars": 150000,
            "temperature": 0.0,
            "seed": 0,
            "max_tokens": 2048,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    }
