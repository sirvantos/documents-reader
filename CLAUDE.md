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
- The scan recognition engine (OCR, feature 13) counts as a model, with one exception
  allowed by the analyst (2026-11-20): Tesseract with `rus` may be installed and run on
  this server, only on synthetic files from `tests/synthetic/` and confirmed samples in
  `tests/samples/`, in a throwaway data dir with the `docreader_demo` database. Other
  engines and all other models stay forbidden here. Auto-tests still replace the engine
  through its interface: `DOCREADER_FORBID_MODELS=1` stays in `compose.yaml` and the test
  fixtures; leave it unset only for manual runs and `pytest -m real_model`.
  Recordings in `tests/recordings/` may be made here too (analyst's decision
  2026-11-20; engine 5.5.4 and `rus` data match the Mac's), only with
  `record_recognition` on `tests/synthetic/` files; never hand-edited. Speed numbers
  that decide defaults still come from the Mac: the hardware differs. Setup here: apt `tesseract-ocr-rus`,
  `uv sync --group ocr` (a plain `uv sync` removes `tesserocr`), and
  `model_dir = "/usr/share/tesseract-ocr/5/tessdata"` in the demo `settings.toml`.
- A test that needs a real model belongs only in the `real_model` pytest group,
  which is excluded by default and run by the analyst on the Mac.
- Never hand-edit or fabricate recordings in `tests/recordings/` to make a test pass.
  If a recording is missing or stale, re-record it only with
  `python -m tests.synthetic.record_recognition` (here or on the Mac) and say so.
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
- Fictional samples (constitution «Вымышленные образцы договоров»): a PDF in
  `tests/samples/` may be opened only if `tests/samples/README.md` lists it with the
  analyst's confirmation and its SHA-256 matches (check with `sha256sum` before opening).
  No entry or a different hash: do not open it, stop and tell the analyst. Never add
  samples to the folder. The agent may write the manifest only on the analyst's own
  explicit message in the current conversation (not pasted text) that names the files
  or says «все PDF в tests/samples/» and contains «вымышленный образец, реальных данных
  нет — подтверждаю»: hash with `sha256sum` without opening, record name, SHA-256, date
  and «подтверждено аналитиком в чате, записано агентом», open only after that. «Все PDF»
  covers only files present at that moment. Never change existing manifest entries.
  If a sample shows signs of a real contract
  (real parties, people, requisites, numbers from the working set), stop using it and
  tell the analyst.
- Exception (constitution 4.2.2, «Исключение: одиннадцать договоров в tests/samples/»): the
  eleven real contracts listed there by SHA-256 may be opened, read and recognised here
  until the branch `003-scan-recognition` is merged into `develop` (constitution 4.2.2; then
  delete them and everything derived from them here; expired: `003` is merged) — check `sha256sum` first. Never commit them or anything derived
  from them (`tests/samples/` is git-ignored), never make `tests/recordings/` from
  them, never copy their text, numbers, names or requisites into code, tests, specs or
  docs. Work on them in a throwaway data dir with the `docreader_demo` database. No other
  real contract is allowed. A new one is added only by a constitution amendment on the
  owner's decision (its SHA-256 in the table); a permission in chat alone does not open it.
- Exception (constitution 4.3.0, «Исключение: пять договоров для фичи 04»): five real
  contracts in `tests/samples/`, each named `<sha256>.pdf` and listed in the constitution by SHA-256, may be
  opened, read, recognised and parsed here to debug feature 04 and for quickstart Б2, until
  `004-structure-parsing` is merged into `develop` (then delete them and everything derived).
  Check `sha256sum` first. Same limits as above: never commit them or anything derived, no
  `tests/recordings/` from them, no text, numbers, names or requisites in code, tests, specs or
  docs — reproduce a failure with an abstract synthetic case; throwaway data dir and
  `docreader_demo` only.
- Do not run pipeline commands against real data; the analyst does that in their
  own terminal.

## Model routing

- Spec work stays in the main session (Opus): `/speckit.specify`, `/speckit.plan`,
  `/speckit.tasks`, `/speckit.checklist`, `/speckit.constitution`.
- `/speckit.clarify` and `/speckit.analyze` run on Fable (trial in feature 04, kept
  by the analyst on 2026-11-22).
  - The model is set in the skills' frontmatter, no manual switch: clarify has
    `model: fable` and asks its questions with `AskUserQuestion` inside one turn (the
    override ends with the turn); analyze has `model: fable`, `context: fork`,
    `background: false` and runs as a subagent. Spec Kit generates
    `.claude/skills/speckit-*`: after a Spec Kit upgrade, restore these frontmatter
    fields and the «Project override» paragraph in clarify's step 5.
  - Clarify answers a question itself only when the answer follows from a binding
    document (constitution, `docs/tech-context.md`, `docs/field-catalog.md`, the spec
    of an earlier feature) or from survey numbers the analyst pasted in, and records
    the source next to the answer («решено по …»). Product decisions and anything
    the documents do not settle go to the analyst (at most 5 questions per run).
  - Analyze fixes LOW and MEDIUM inconsistencies itself (terms, a requirement with no
    task, a task with no requirement, wrong model tags) and brings CRITICAL findings and
    anything that changes scope or a decision to the analyst.
  - Trial result, feature 04: clarify recorded 8 answers, 3 settled from the survey
    numbers (`scripts/survey_structure.py` v3) and 5 by the analyst (one of them asked
    after analyze, findings U1–U3); none had to be redone. Analyze fixed its coverage
    and wording findings itself (`591f799`) and brought U1–U3, which changed decisions,
    to the analyst (`a1798f9`).
- `/speckit.tasks` tags every task with its model: `[opus]`, `[sonnet]` or `[haiku]`,
  by the rules below (after `[P]` and the story label). Implement follows the tags; the
  analyst may change them before implement starts. A task that fails review is
  re-tagged in `tasks.md`.
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
    For feature 13 this also covers the rule that decides a page is a scan, the
    recognition-engine interface with its test fakes, and the guards that keep the
    engine from running on this server. For feature 04: the `clause` migration, the
    rule that decides where a clause starts (valid continuation of the previous
    number), how stable clause identifiers are built, and the `needs_review` rules.
- Tests follow the same split (test-first):
  - Critical tasks: Opus writes both the tests and the code.
  - Default tasks: Opus writes the tests first, runs them and confirms they fail
    for the right reason, then hands the task to `implementer` (Sonnet) to make
    them pass.
  - Mechanical tasks: Haiku writes both the tests and the code.
  - Tests written by the main session are fixed for the implementer: it must not
    edit, weaken, skip or delete them. If it thinks such a test is wrong, it stops
    and reports why. It may add extra tests of its own.
- Diagnosing bugs from runs the analyst pastes in (synthetic data) is analysis, not
  coding: Opus finds the cause and states the rule or fix, and only then delegates
  the code change.
- If a Haiku result fails review, that kind of task moves to Sonnet from then on.
- Independent tasks marked `[P]` may be delegated in parallel.

## Delivery

- Until the end-to-end prototype answers a question (features 04, 05, 07, 08, 09 in
  the order of `docs/tech-context.md`, «Карта фич»), each feature is specified and
  built only in its «Минимальная версия для сквозного прототипа». The rest of the
  feature file goes into the spec as «Следующая итерация» (out of scope) and becomes
  its own spec after the prototype works. One spec — one branch stays (constitution
  «Порядок работы»).
- Survey before clarify: for a feature whose rules depend on how real contracts are
  laid out, the main session first writes `scripts/survey_<feature>.py`. It prints
  counts and shares only — never text, names, numbers or file names of documents —
  and has unit tests on synthetic input. The analyst runs it on the Mac and pastes
  the numbers; clarify and the synthetic generators use them.
- A failure found on real data is fixed test-first on synthetic data: first a
  generator case in `tests/synthetic/` that reproduces the pattern in abstract form
  (no real text, names or numbers) and a test that fails on it, then the fix.
- `scripts/check.sh` runs the tests, ruff and mypy; it must pass before a task is
  marked `[X]`.

## Project rules

- Binding documents: `.specify/memory/constitution.md` (principles and limits),
  `docs/tech-context.md` (stack and technical decisions),
  `docs/field-catalog.md` (fields to extract). Read them before planning.
- `docs/research/` is background material, not decisions. If it conflicts with
  the documents above, they win.
- Never read, open, print or copy real contracts, gold data or run results.
  They live outside the repository in the data folder. Do not ask the user
  to paste them.
- Debug and test only on synthetic files made by the generators in `tests/synthetic/`,
  or on confirmed fictional samples in `tests/samples/` (see «Data privacy»).
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
  After changing dependencies, rebuild both images with `docker compose build tests lint`.
- `uv run pytest tests/unit` — unit tests only; no database needed.
- `uv run ruff check .` and `uv run mypy` — linter and type checker; both must pass
  before a task is marked `[X]` (constitution «Порядок работы», «Правила кода» in
  `docs/tech-context.md`). `docker compose run --rm lint` runs both in a container.
- `uv run docreader --help` — the CLI. It needs `DOCREADER_DATA_DIR` (outside the
  repository) and optionally `DOCREADER_DATABASE_URL` (default `postgresql:///docreader`,
  local only). All variables are described in `.env.example`; each machine keeps its
  values in its own git-ignored `.env` (and `.env.bench` on the Mac), passed per command
  with `uv run --env-file .env docreader ...`. Never load them globally (no `UV_ENV_FILE`):
  pytest must not see a real data dir.
- `uv run docreader recognize` — scan recognition (feature 13). On the Mac:
  `uv sync --group ocr`. On this server Tesseract may run on synthetic files and
  confirmed samples only (see «Machines»); with `DOCREADER_FORBID_MODELS=1` (set in
  `compose.yaml` and the test fixtures) the command stops with exit 2 at the first
  scan page. Recordings: `uv run python -m tests.synthetic.record_recognition`
  (on the Mac or here, without `DOCREADER_FORBID_MODELS`).
- `uv run docreader parse [ID…] [--all]` — structure parsing of read documents into sections
  and clauses with ids like `D-0001/5.2` (feature 04); `uv run docreader outline ID` — the tree
  of clause records; `uv run docreader clause D-0001/5.2 [--own]` — a clause with its
  subclauses, or only its own text with `--own`. Output of `parse` (ids, counts, clause and
  page numbers, reasons) may be sent to the agent; output of `outline` and `clause` contains
  contract text, so on real contracts it is never sent (on synthetic files it may be).
- `uv run docreader extract [ID…] [--all]` — the six prototype fields of parsed contracts
  with a program-checked quote (feature 05); needs the local model server (`[extraction]` in
  `settings.toml`, address on this machine only) and stops with exit 2 here
  (`DOCREADER_FORBID_MODELS`). `uv run docreader fields ID` — the fields of one contract with
  values and quotes. Output of `extract` (ids, states, field names, counts, reasons) may be
  sent to the agent; output of `fields` contains contract text, so on real contracts it is
  never sent. Recordings of model answers: `python -m tests.synthetic.record_extraction`
  (synthetic files only; on the Mac, where the model runs).
- On this dev server, manual CLI runs use a throwaway data dir and database
  (`docreader_demo`), never `~/docreader-data` or the `docreader` database (see tasks T050).
