"""Helpers of scripts/export_samples_04.py on synthetic files."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "export_samples_04", ROOT / "scripts" / "export_samples_04.py"
)
assert _spec is not None and _spec.loader is not None
ex = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ex)


def test_stage_names_the_copy_by_its_hash(tmp_path: Path) -> None:
    source = tmp_path / "Участок Энск договор.PDF"
    source.write_bytes(b"%PDF-1.4 synthetic")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    folder = tmp_path / "out"
    folder.mkdir()
    target = ex.stage("D-0001", source, sha, folder)
    assert target.name == f"{sha}.pdf"  # no original name on the server
    assert target.read_bytes() == source.read_bytes()


def test_stage_refuses_a_file_with_another_hash(tmp_path: Path) -> None:
    source = tmp_path / "a.pdf"
    source.write_bytes(b"x")
    with pytest.raises(SystemExit):
        ex.stage("D-0001", source, "0" * 64, tmp_path)


def test_manifest_has_ids_and_hashes_only() -> None:
    assert ex.manifest_text([("D-0001", "a" * 64), ("D-0027", "b" * 64)]) == (
        f"D-0001 {'a' * 64}\nD-0027 {'b' * 64}\n"
    )


def test_data_dir_from_env_file(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# x\nexport DOCREADER_DATA_DIR='/x/data'\n", encoding="utf-8")
    assert ex.data_dir(str(env)) == "/x/data"
