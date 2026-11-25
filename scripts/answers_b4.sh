#!/bin/sh
# Quickstart Б4 of feature 09 on the Mac in one command: checks the three model servers,
# asks the questions of $DOCREADER_DATA_DIR/questions/answers-09.toml (or --questions FILE)
# and saves the answers and the summary next to the questions file.
# Extra arguments go to scripts/quickstart_answers.py (for example --json).
set -eu
cd "$(dirname "$0")/.."
exec uv run --env-file .env python scripts/quickstart_answers.py "$@"
