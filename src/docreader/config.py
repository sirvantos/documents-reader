"""Settings and privacy guards (research R-8; principle I of the constitution).

- DOCREADER_DATA_DIR is required and must lie outside the repository.
- DOCREADER_DATABASE_URL must point to a local PostgreSQL (Unix socket or loopback).
- Optional $DOCREADER_DATA_DIR/settings.toml holds the thresholds.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict

from docreader.errors import EnvironmentProblem

DEFAULT_DATABASE_URL = "postgresql:///docreader"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SETTINGS_FILE = "settings.toml"


def _find_git_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


# Repository that contains this package (None when installed outside a checkout).
REPO_ROOT = _find_git_root(Path(__file__).resolve().parent)


@dataclass(frozen=True)
class ReadingSettings:
    """Thresholds of the [reading] section (data-model «Настройки», research R-13)."""

    header_band: float = 0.1
    header_min_share: float = 0.5
    header_min_pages: int = 3
    non_russian_min_letters: int = 3
    unreadable_min_letter_share: float = 0.6
    unreadable_max_bad_share: float = 0.05
    unreadable_max_vowelless_share: float = 0.4
    column_min_lines: int = 3
    column_min_gap: float = 20.0
    column_gap_tolerance: float = 15.0
    wide_gap_factor: float = 2.5
    rotated_min_angle: float = 5.0


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    text_min_chars: int = 20
    full_image_coverage: float = 0.85
    large_file_pages: int = 200
    reading: ReadingSettings = field(default_factory=ReadingSettings)

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    def settings_for_run(self) -> dict:
        """Resolved values recorded in run.settings (principle VI)."""
        return {
            "page_kinds": {
                "text_min_chars": self.text_min_chars,
                "full_image_coverage": self.full_image_coverage,
            },
            "intake": {"large_file_pages": self.large_file_pages},
            "reading": asdict(self.reading),
        }


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    data_dir = _resolve_data_dir(env)
    database_url = env.get("DOCREADER_DATABASE_URL", "").strip() or DEFAULT_DATABASE_URL
    _check_local_database(database_url, env)
    return Settings(data_dir=data_dir, database_url=database_url, **_read_settings_file(data_dir))


# --- data folder -------------------------------------------------------------


def _resolve_data_dir(env: Mapping[str, str]) -> Path:
    raw = env.get("DOCREADER_DATA_DIR", "").strip()
    if not raw:
        raise EnvironmentProblem(
            "Не задана папка данных — укажите DOCREADER_DATA_DIR (папка вне репозитория)"
        )
    data_dir = Path(raw).expanduser().resolve()

    repos = {r for r in (REPO_ROOT, _find_git_root(Path.cwd().resolve())) if r is not None}
    for repo in repos:
        if data_dir == repo or data_dir.is_relative_to(repo):
            raise EnvironmentProblem(
                f"Папка данных {data_dir} лежит внутри репозитория {repo} — "
                "укажите в DOCREADER_DATA_DIR папку вне репозитория"
            )

    if data_dir.exists() and not data_dir.is_dir():
        raise EnvironmentProblem(
            f"DOCREADER_DATA_DIR указывает на файл, а не на папку: {data_dir}"
        )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EnvironmentProblem(
            f"Не удалось создать папку данных {data_dir}: {exc.strerror} — "
            "проверьте DOCREADER_DATA_DIR"
        ) from exc
    return data_dir


# --- database address ----------------------------------------------------------


def _is_local_host(host: str) -> bool:
    # Empty host or a path means a Unix socket; "@" prefix is a Linux abstract socket.
    return host == "" or host.startswith(("/", "@")) or host in LOCAL_HOSTS


def _check_local_database(url: str, env: Mapping[str, str]) -> None:
    try:
        params = conninfo_to_dict(url)
    except psycopg.ProgrammingError as exc:
        raise EnvironmentProblem(
            f"Не удалось разобрать DOCREADER_DATABASE_URL: {exc} — проверьте адрес базы"
        ) from exc

    # libpq falls back to these environment variables for keys missing in the URL.
    host = params.get("host") or env.get("PGHOST", "")
    hostaddr = params.get("hostaddr") or env.get("PGHOSTADDR", "")
    service = params.get("service") or env.get("PGSERVICE", "")

    problems = [h for h in str(host).split(",") if not _is_local_host(h.strip())]
    problems += [h for h in str(hostaddr).split(",") if h.strip() and h.strip() not in LOCAL_HOSTS]
    if service:
        problems.append(f"service={service}")
    if problems:
        raise EnvironmentProblem(
            "База данных должна быть локальной (Unix-сокет, localhost, 127.0.0.1 или ::1), "
            f"получено: {', '.join(problems)} — исправьте DOCREADER_DATABASE_URL / PGHOST"
        )


# --- settings.toml ---------------------------------------------------------------

# table -> key -> (field name, type, validator, description of the allowed range)
_SCHEMA: dict[str, dict[str, tuple[str, type, Callable[[Any], bool], str]]] = {
    "page_kinds": {
        "text_min_chars": ("text_min_chars", int, lambda v: v >= 1, "целое ≥ 1"),
        "full_image_coverage": (
            "full_image_coverage",
            float,
            lambda v: 0 < v <= 1,
            "число в (0, 1]",
        ),
    },
    "intake": {
        "large_file_pages": ("large_file_pages", int, lambda v: v >= 1, "целое ≥ 1"),
    },
    # Keys of [reading] map one-to-one to ReadingSettings fields.
    "reading": {
        "header_band": ("header_band", float, lambda v: 0 < v <= 1, "число в (0, 1]"),
        "header_min_share": ("header_min_share", float, lambda v: 0 < v <= 1, "число в (0, 1]"),
        "header_min_pages": ("header_min_pages", int, lambda v: v >= 1, "целое ≥ 1"),
        "non_russian_min_letters": (
            "non_russian_min_letters",
            int,
            lambda v: v >= 1,
            "целое ≥ 1",
        ),
        "unreadable_min_letter_share": (
            "unreadable_min_letter_share",
            float,
            lambda v: 0 < v <= 1,
            "число в (0, 1]",
        ),
        "unreadable_max_bad_share": (
            "unreadable_max_bad_share",
            float,
            lambda v: 0 < v <= 1,
            "число в (0, 1]",
        ),
        "unreadable_max_vowelless_share": (
            "unreadable_max_vowelless_share",
            float,
            lambda v: 0 < v <= 1,
            "число в (0, 1]",
        ),
        "column_min_lines": ("column_min_lines", int, lambda v: v >= 2, "целое ≥ 2"),
        "column_min_gap": ("column_min_gap", float, lambda v: v >= 0, "число ≥ 0"),
        "column_gap_tolerance": ("column_gap_tolerance", float, lambda v: v >= 0, "число ≥ 0"),
        "wide_gap_factor": ("wide_gap_factor", float, lambda v: v > 0, "число > 0"),
        "rotated_min_angle": (
            "rotated_min_angle",
            float,
            lambda v: 0 <= v < 90,
            "число в [0, 90)",
        ),
    },
}
READING_TABLE = "reading"


def _read_settings_file(data_dir: Path) -> dict:
    path = data_dir / SETTINGS_FILE
    if not path.exists():
        return {}

    def bad(detail: str) -> EnvironmentProblem:
        return EnvironmentProblem(f"Ошибка в {path} (settings.toml): {detail}")

    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise bad(f"файл не разобран — {exc}") from exc

    values: dict = {}
    reading_values: dict = {}
    for table, entries in doc.items():
        if table not in _SCHEMA:
            raise bad(f"неизвестный раздел [{table}]")
        if not isinstance(entries, dict):
            raise bad(f"«{table}» должен быть разделом [{table}]")
        target = reading_values if table == READING_TABLE else values
        for key, value in entries.items():
            if key not in _SCHEMA[table]:
                raise bad(f"неизвестный ключ {table}.{key}")
            field, kind, valid, allowed = _SCHEMA[table][key]
            expected = (int, float) if kind is float else int
            if isinstance(value, bool) or not isinstance(value, expected):
                raise bad(f"{table}.{key} = {value!r}: нужно {allowed}")
            value = kind(value)
            if not valid(value):
                raise bad(f"{table}.{key} = {value!r}: нужно {allowed}")
            target[field] = value
    if READING_TABLE in doc:
        values["reading"] = ReadingSettings(**reading_values)
    return values
