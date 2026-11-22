"""Prepare and upload the contracts of the feature 04 exception to the dev server (Mac side).

The owner's decision of 2026-11-22: these documents may be examined by the agent on the
dev server to debug structure parsing (feature 04), on the terms of the constitution
section for feature 04 (no commits, nothing derived in code, tests or docs; deleted
after `004-structure-parsing` is merged into `develop`).

Run on the analyst's Mac, from the repository root:

    uv run python scripts/export_samples_04.py --dest USER@HOST:PATH/tests/samples/
    uv run python scripts/export_samples_04.py            # prepare only, print the scp command

For each document: takes its stored copy (`docreader show ID --json` → `copy_path`), checks
its SHA-256 against the registry, copies it as `<sha256>.pdf` (the file name carries no
site names) into `$DOCREADER_DATA_DIR/reports/feature04-samples/`, and writes
`feature04-samples.txt` — lines «D-0001 <sha256>». Then uploads the folder with `scp`.
Printed: document ids and SHA-256 only (may be sent to the agent).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

DOCUMENTS = ("D-0001", "D-0027", "D-0055", "D-0054", "D-0056")
FOLDER = "feature04-samples"
MANIFEST = "feature04-samples.txt"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage(doc_id: str, copy_path: Path, expected_sha: str, folder: Path) -> Path:
    """Copy the stored file as `<sha256><suffix>` after checking its hash."""
    actual = sha256_of(copy_path)
    if actual != expected_sha:
        raise SystemExit(f"{doc_id}: SHA-256 файла не совпадает с реестром — файл не выгружен")
    target = folder / f"{actual}{copy_path.suffix.lower() or '.pdf'}"
    shutil.copyfile(copy_path, target)
    return target


def manifest_text(entries: Sequence[tuple[str, str]]) -> str:
    return "".join(f"{doc_id} {sha}\n" for doc_id, sha in entries)


def data_dir(env_file: str) -> str:
    for raw in Path(env_file).read_text(encoding="utf-8").splitlines():
        line = raw.strip().removeprefix("export ").strip()
        if line.startswith("DOCREADER_DATA_DIR="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(f"В {env_file} нет DOCREADER_DATA_DIR")


def _show(env_file: str, doc_id: str) -> dict:
    command = ["uv", "run", "--env-file", env_file, "docreader", "show", doc_id, "--json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"docreader show {doc_id}: код {result.returncode}\n{result.stderr}")
    data: dict = json.loads(result.stdout)
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--dest", help="scp target: user@host:PATH/tests/samples/")
    parser.add_argument("--docs", nargs="+", default=list(DOCUMENTS))
    args = parser.parse_args(argv)

    folder = Path(data_dir(args.env_file)).expanduser() / "reports" / FOLDER
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    entries: list[tuple[str, str]] = []
    for doc_id in args.docs:
        doc = _show(args.env_file, doc_id)
        stage(doc_id, Path(doc["copy_path"]), doc["sha256"], folder)
        entries.append((doc_id, doc["sha256"]))
    (folder / MANIFEST).write_text(manifest_text(entries), encoding="utf-8")

    print(manifest_text(entries), end="")
    files = sorted(str(p) for p in folder.iterdir())
    if not args.dest:
        print(f"\nФайлы подготовлены в {folder}. Выгрузка:\n  scp {folder}/* USER@HOST:PATH/")
        return 0
    result = subprocess.run(["scp", *files, args.dest], check=False)
    if result.returncode != 0:
        print(f"scp: код {result.returncode}", file=sys.stderr)
        return 1
    print(f"\nВыгружено файлов: {len(files)} → {args.dest}. Список выше можно прислать агенту.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
