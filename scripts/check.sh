#!/usr/bin/env bash
# Run the checks that must pass before a task is marked [X]: tests, ruff, mypy.
# Extra arguments go to pytest (e.g. scripts/check.sh -k clause -x).
# Integration tests need a local PostgreSQL role with CREATEDB; the default
# below can be overridden by setting DOCREADER_TEST_DATABASE_URL.
set -euo pipefail

cd "$(dirname "$0")/.."

export DOCREADER_TEST_DATABASE_URL="${DOCREADER_TEST_DATABASE_URL:-postgresql:///postgres}"

echo "== pytest"
uv run pytest "$@"
echo "== ruff"
uv run ruff check .
echo "== mypy"
uv run mypy
echo "== all checks passed"
