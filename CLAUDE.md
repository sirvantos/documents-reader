# documents-reader

Local PoC: reading, field extraction, search and answers over Russian contracts.
Governing documents: `.specify/memory/constitution.md` (highest priority),
`docs/tech-context.md`, `docs/field-catalog.md`. Features are developed with Spec Kit
(`/speckit.*` commands, artifacts in `specs/<NNN-feature>/`).

## Machines

- **This machine is the development server**: a weak VPS (Ubuntu 24.04, x86_64,
  2 cores, ~4 GB RAM). Code is written and auto-tests run here.
- No real models run here: never download model weights, start a model server, or
  add tests that need one. Auto-tests use fake models: hand-written stubs and answers
  recorded from the real model on synthetic contracts (test levels and rules:
  "Модели в автотестах" in `docs/tech-context.md`).
- The scan recognition engine (OCR, feature 13) counts as a model: never install its
  language data or weights or run it here; tests replace it through its interface.
- A test that needs a real model belongs only in the `real_model` pytest group,
  which is excluded by default and run by the analyst on the Mac.
- Never hand-edit or fabricate recordings in `tests/recordings/` to make a test pass.
  If a recording is missing or stale, stop and ask the analyst to re-record it on the Mac.
- Output of runs on synthetic data that the analyst pastes in may be used for
  debugging; never ask for output of runs on real contracts.
- Real-model runs, quality/speed measurements and anything on real contracts happen
  only on the analyst's Mac (Apple M3 Pro, 36 GB). Commands for that are written here
  but run there by the analyst.
- Code must work on both macOS (Apple Silicon) and Linux x86_64.

## Data privacy (constitution, principle I)

- Never read, print, list or copy anything from the data directory
  (`$DOCREADER_DATA_DIR`) or any real contract, gold set or run result.
- Debug and test only on synthetic files that live in the repository.
- Do not run pipeline commands against real data; the analyst does that in their
  own terminal.

## Model routing

- Spec work stays in the main session (Opus): `/speckit.specify`, `/speckit.clarify`,
  `/speckit.plan`, `/speckit.tasks`, `/speckit.analyze`, `/speckit.checklist`,
  `/speckit.constitution`.
- During `/speckit.implement` the main session coordinates and delegates the work.
  It reads `tasks.md`, hands each task (or a small group of tightly related tasks)
  to the `implementer` subagent, reviews the result, runs the tests, ruff and mypy, then marks the
  task `[X]`.
  - Default: `implementer` on its own model (Sonnet).
  - Mechanical tasks: pass `model: "haiku"`. These are project scaffolding and config,
    CLI argument wiring, output formatting, and synthetic test-file generators.
  - Critical tasks: the main session does these itself on Opus instead of delegating.
    These are database schema and migrations, atomic file intake (copy and
    transaction ordering), classification and other decision rules, anything touching
    the privacy guards, and any task whose first delegated attempt failed review.
- Independent tasks marked `[P]` may be delegated in parallel.

## Project rules

- Binding documents: `.specify/memory/constitution.md` (principles and limits),
  `docs/tech-context.md` (stack and technical decisions),
  `docs/field-catalog.md` (fields to extract). Read them before planning.
- `docs/research/` is background material, not decisions. If it conflicts with
  the documents above, they win.
- Never read, open, print or copy real contracts, gold data or run results.
  They live outside the repository in the data folder. Do not ask the user
  to paste them.
- Debug and test only on synthetic files made by the generators in `tests/synthetic/`.
- Never send document content to any external service. All models run locally.
- Code, identifiers, commit messages and code comments are in English.
  Specs and project docs are in Russian.

## Commands

- `uv sync` — install dependencies (including the dev group).
- `DOCREADER_TEST_DATABASE_URL=postgresql:///postgres uv run pytest` — full test suite.
  Integration tests need this variable: a local PostgreSQL role with CREATEDB. Each run
  creates and drops a throwaway `docreader_test_*` database. Without the variable the
  integration tests fail. `real_model` tests are excluded by default.
- `docker compose run --rm tests` — full test suite in containers (throwaway PostgreSQL 17
  in memory, no internet access, repo mounted read-only); extra pytest arguments go at the
  end (`docker compose run --rm tests -k note -x`); `docker compose down` stops the database.
  After changing dependencies, rebuild with `docker compose build tests`.
- `uv run pytest tests/unit` — unit tests only; no database needed.
- `uv run ruff check .` and `uv run mypy` — linter and type checker; both must pass
  before a task is marked `[X]` (constitution «Порядок работы», «Правила кода» in
  `docs/tech-context.md`). `docker compose run --rm lint` runs both in a container.
- `uv run docreader --help` — the CLI. It needs `DOCREADER_DATA_DIR` (outside the
  repository) and optionally `DOCREADER_DATABASE_URL` (default `postgresql:///docreader`,
  local only).
- On this dev server, manual CLI runs use a throwaway data dir and database
  (`docreader_demo`), never `~/docreader-data` or the `docreader` database (see tasks T050).
