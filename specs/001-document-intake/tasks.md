---
description: "Task list for feature 001: document intake and registry"
---

# Tasks: Приём документов и реестр договоров

**Input**: Design documents from `specs/001-document-intake/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md), [quickstart.md](quickstart.md)

**Tests**: требуются — часть B фичи («Тесты. Нужны синтетические файлы…») и план
(раздел Testing). Тесты пишутся первыми и должны падать до реализации.

**Organization**: задачи сгруппированы по историям пользователя (US1–US5 из spec.md).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно выполнять параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история пользователя (US1…US5)
- Пути — от корня репозитория; раскладка — plan.md, «Source Code»

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-10), data-model.md, contracts/cli.md обязательны.
- Только синтетические файлы; никакого обращения к `$DOCREADER_DATA_DIR` реальной
  машины и к реальным договорам (CLAUDE.md, принцип I).
- Языковая модель и сеть не используются.
- Сообщения пользователю — на русском, тексты причин и предупреждений — как в
  contracts/cli.md и research.md R-5.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: инициализация проекта

- [ ] T001 Create `pyproject.toml`: package `docreader` in `src/` layout, `requires-python = ">=3.11"`; dependencies `pypdfium2`, `psycopg[binary]` (3.x); dev dependency group `pytest`, `reportlab`, `pillow`; console script `docreader = "docreader.cli:main"`; package data includes `src/docreader/migrations/*.sql`; `[tool.pytest.ini_options]` with `testpaths = ["tests"]`, markers `integration` and `real_model`, and `addopts = "-m 'not real_model'"`. Then run `uv lock` and `uv sync` to produce `uv.lock`
- [ ] T002 [P] Create package and test skeleton: `src/docreader/__init__.py` (`__version__`), `src/docreader/__main__.py` (calls `docreader.cli.main()` and exits with its return code), `tests/__init__.py`, `tests/synthetic/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`
- [ ] T003 [P] Verify `.gitignore` contains Python patterns (`__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `dist/`, `*.egg-info/`, `.pytest_cache/`) and universal ones (`.DS_Store`, `*.tmp`, `*.swp`, `.vscode/`, `.idea/`); append only missing ones in `.gitignore`
- [ ] T004 Install PostgreSQL 17 on the development server from the PGDG apt repository (requires sudo — ask the analyst to confirm or run it), create a role for the current OS user with `CREATEDB`, `createdb docreader`, and confirm `psql postgresql:///postgres -c 'select version()'` works; document the value to use for `DOCREADER_TEST_DATABASE_URL` (e.g. `postgresql:///postgres`) in `specs/001-document-intake/quickstart.md` if it differs

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: настройки, база, миграции, запуски, каркас CLI, тестовая инфраструктура

**⚠️ CRITICAL**: работа над историями начинается только после этой фазы

- [ ] T005 [P] Create `src/docreader/errors.py` with `UserError` (exit code 1) and `EnvironmentProblem` (exit code 2), both carrying a one-line Russian message with a hint (contracts/cli.md «Коды завершения»)
- [ ] T006 [P] Write failing unit tests in `tests/unit/test_config.py`: missing `DOCREADER_DATA_DIR` → `EnvironmentProblem`; data dir inside the repository (resolved path under repo root) → `EnvironmentProblem`; `DOCREADER_DATABASE_URL` default `postgresql:///docreader`; allowed hosts only Unix socket (empty host or path starting with `/`), `localhost`, `127.0.0.1`, `::1`, anything else → `EnvironmentProblem`; `settings.toml` absent → defaults `page_kinds.text_min_chars = 20`, `page_kinds.full_image_coverage = 0.85`, `intake.large_file_pages = 200`; overrides applied; unknown key or out-of-range value (`text_min_chars < 1`, `full_image_coverage` outside `(0, 1]`, `large_file_pages < 1`) → `EnvironmentProblem`; `settings_for_run()` returns the resolved values as a JSON-serialisable dict
- [ ] T007 Implement `src/docreader/config.py` (research R-8) to make `tests/unit/test_config.py` pass: `Settings` dataclass, `load_settings(env=os.environ)`, repo-root detection by walking up from the package directory to the folder containing `.git`, local-DB check via `psycopg.conninfo.conninfo_to_dict`, `settings.toml` read with `tomllib`
- [ ] T008 [P] Write failing unit tests in `tests/unit/test_ids.py`: `format_document_id(1) == "D-0001"`, `format_document_id(10000) == "D-10000"`; `parse_document_id` accepts `D-0001`, `d-0001`, `D-1`, `d-1` → seq 1, rejects `D-`, `D-0`, `X-1`, `D-1a`, empty → `UserError`
- [ ] T009 Implement `src/docreader/ids.py` (research R-3) to make `tests/unit/test_ids.py` pass
- [ ] T010 Write `src/docreader/migrations/0001_intake.sql` exactly per data-model.md, including:
  - `run`: `id bigint` identity PK; `stage text NOT NULL`; `started_at timestamptz NOT NULL default now()`; `finished_at timestamptz NULL`; `code_version text NOT NULL`; `model text NULL`; `prompt_version text NULL`; `settings jsonb NOT NULL`; `label text NULL`
  - `document_counter`: `singleton boolean PK default true CHECK (singleton)`; `last_seq integer NOT NULL default 0 CHECK (last_seq >= 0)`; insert the single row
  - `document`: `id text PK CHECK (id ~ '^D-[0-9]{4,}$')`; `seq integer NOT NULL UNIQUE`; `sha256 char(64) NOT NULL UNIQUE CHECK (sha256 ~ '^[0-9a-f]{64}$')`; `original_name text NOT NULL`; `source_path text NOT NULL`; `copy_path text NOT NULL`; `size_bytes bigint NOT NULL CHECK (> 0)`; `page_count integer NOT NULL CHECK (> 0)`; `added_at timestamptz NOT NULL default now()`; `note text NULL`; `parent_document_id text NULL` FK → `document(id)` `ON DELETE SET NULL` with `CHECK (parent_document_id IS NULL)`; `intake_run_id bigint NOT NULL` FK → `run(id)` (`ON DELETE RESTRICT`); index on `lower(original_name)`
  - `page`: `document_id` FK → `document(id)` `ON DELETE CASCADE`; `page_number integer CHECK (>= 1)`; `kind text NOT NULL CHECK (kind IN ('text','scan','scan_with_text'))`; `char_count integer NOT NULL CHECK (>= 0)`; `image_coverage real NOT NULL CHECK (0 <= x <= 1)`; `invisible_text_share real NULL CHECK (0 <= x <= 1)`; `kind_run_id bigint NOT NULL` FK → `run(id)`; PK (`document_id`, `page_number`)
  - `stage_status`: `document_id` FK → `document(id)` `ON DELETE CASCADE`; `stage text CHECK (stage IN ('reading','structure','extraction','checks','indexing'))`; `state text NOT NULL default 'pending' CHECK (state IN ('pending','done','needs_review','failed'))`; `reason text NULL` with `CHECK (state IN ('pending','done') OR (reason IS NOT NULL AND btrim(reason) <> ''))`; `run_id bigint NULL` FK → `run(id)`; `updated_at timestamptz NOT NULL default now()`; PK (`document_id`, `stage`)
  - `deletion_log`: `id bigint` identity PK; `document_id text NOT NULL` (no FK); `original_name text NOT NULL`; `sha256 char(64) NOT NULL`; `deleted_at timestamptz NOT NULL default now()`
  - `schema_migrations` is created by the runner (T011), not by this file
- [ ] T011 Implement `src/docreader/db.py` (research R-6): `connect(settings)` returning a `psycopg` connection; `apply_migrations(conn) -> list[str]` that creates `schema_migrations(version text PK, applied_at timestamptz NOT NULL default now())` if missing and applies unapplied `migrations/*.sql` in name order, each in its own transaction; `ensure_schema_current(conn)` raising `EnvironmentProblem("Схема базы устарела — выполните docreader migrate")`; connection failure → `EnvironmentProblem`; constant `STAGES = ("reading", "structure", "extraction", "checks", "indexing")` matching the CHECK
- [ ] T012 Implement `src/docreader/runs.py` (research R-9): `code_version()` = `git describe --always --dirty` run in the package directory, fallback `importlib.metadata.version("docreader")`; `start_run(conn, stage, settings: dict, label) -> int`; `finish_run(conn, run_id)` setting `finished_at = now()`; `model` and `prompt_version` stay NULL
- [ ] T013 Implement CLI skeleton in `src/docreader/cli.py`: `main(argv=None) -> int` with `argparse` subcommands `migrate`, `add`, `list`, `show`, `remove`, `verify`, `reclassify`, `page-kinds-check` (all but `migrate` raise "не реализовано" for now); map `UserError` → 1, `EnvironmentProblem` → 2, `KeyboardInterrupt` → 130, messages to stderr; `migrate` prints «Применена миграция <version>» per migration or «Схема актуальна»; every non-`migrate` command calls `ensure_schema_current`
- [ ] T014 Create test infrastructure in `tests/conftest.py`: session fixture that requires `DOCREADER_TEST_DATABASE_URL` (if absent, fail with «Задайте DOCREADER_TEST_DATABASE_URL — адрес локального PostgreSQL с правом создавать базы», do not skip), creates database `docreader_test_<random>`, yields its URL, drops it at session end; per-test fixture that truncates all tables and resets `document_counter.last_seq` to 0; `data_dir` fixture on `tmp_path`; `cli` fixture that sets `DOCREADER_DATA_DIR`/`DOCREADER_DATABASE_URL` via `monkeypatch` and returns `run(*args, input=None) -> (exit_code, stdout, stderr)` calling `docreader.cli.main`; autouse guard that patches `socket.socket.connect` to fail on any non-local address (FR-013)
- [ ] T015 Implement synthetic file generators in `tests/synthetic/make_pdfs.py` (research R-10) with `reportlab` + `Pillow`, each a function `make_<kind>(path, pages=...)`: `digital` (text pages), `image_only` (full-page raster image, no text), `mixed` (text pages + last page a full-page image), `image_with_invisible_text` (full-page image + text in render mode 3), `image_strips` (full page covered by several horizontal image strips, no text), `logo_and_text` (small image + text), `blank_page`, `encrypted` (user password set), `damaged` (truncated valid PDF), `empty` (0 bytes), `no_pages` (minimal hand-written PDF with empty `/Pages`), `fake_docx` (`PK\x03\x04` zip with `word/document.xml`), `fake_doc` (`D0 CF 11 E0` header), `jpeg`, `png`, `unknown`; plus `python -m tests.synthetic.make_pdfs <dir>` writing a demo set with a nested subfolder (quickstart.md part A); Latin text only
- [ ] T016 Write integration tests in `tests/integration/test_migrate.py`: `migrate` on an empty database applies `0001_intake`, second run prints «Схема актуальна» and exits 0; `list` against a database without the schema exits 2 with the «docreader migrate» hint (use a second empty temp database)

**Checkpoint**: foundation ready — `uv run pytest tests/unit tests/integration/test_migrate.py` passes

---

## Phase 3: User Story 1 — Добавить папку договоров (Priority: P1) 🎯 MVP

**Goal**: `docreader add <путь>` регистрирует PDF, хранит побайтную копию, выдаёт отчёт с группами «добавлен / не добавлен», записывает запуск.

**Independent Test**: папка с вложенной папкой, пятью PDF и несколькими не-PDF → `add` → 5 документов `D-0001…D-0005`, отклонённые файлы с причинами, копии совпадают с исходными после удаления исходных.

### Tests for User Story 1 ⚠️ (write first, must fail)

- [ ] T017 [P] [US1] Write unit tests in `tests/unit/test_sniff.py` for every row of research R-5: hidden name → `hidden`; 0 bytes → `empty`; `%PDF-` within the first 1024 bytes → pdf; DOC header and DOCX zip → `word` with the «сохраните его в PDF» hint; JPEG, PNG, TIFF headers → `image` with the hint; anything else → `unsupported`
- [ ] T018 [P] [US1] Write unit tests in `tests/unit/test_rect_union.py` for `union_area(rects, clip)`: no rects → 0; one rect; overlapping rects counted once; rects partly outside the clip box clipped; strips covering the box exactly → full area
- [ ] T019 [P] [US1] Write integration tests in `tests/integration/test_add.py` (US1 acceptance 1–3, FR-001/002/003/004/006/009/012, edge cases): folder with nested subfolder and 5 `digital` PDFs → 5 documents with IDs `D-0001…D-0005` assigned in sorted path order, `original_name`, `page_count`, `size_bytes`, 5 `stage_status` rows in `pending` each; a single file path works; several paths in one call work; `fake_docx`, `fake_doc`, `jpeg`, `png`, `unknown`, `.DS_Store`, `encrypted`, `damaged`, `empty`, `no_pages` → `rejected` with the matching `reason_code` and others still added; after deleting the source files the copies at `copy_path` exist, are mode 0444 and have the same SHA-256; `--json` report `totals.files` equals the number of input files and every file has exactly one `status`; report saved as `reports/intake-<run_id>.json`; one `run` row with `stage = 'intake'`, non-empty `code_version`, `settings.command = 'add'` and the resolved thresholds, `finished_at` set; nonexistent path → exit 1
- [ ] T020 [P] [US1] Write integration test in `tests/integration/test_interrupted_add.py`: monkeypatch the registration step to raise after the copy was written → no `document`, `page` or `stage_status` rows, but the copy file exists; running `add` again adds the file once, reuses the existing copy (same SHA-256) and the ID is `D-0001`; a `KeyboardInterrupt` between files keeps already committed documents, exits 130, and the run's `finished_at` stays NULL

### Implementation for User Story 1

- [ ] T021 [P] [US1] Implement `src/docreader/sniff.py` (research R-5): `sniff(path) -> SniffResult(kind, reason_code, reason)` reading at most the first 1024 bytes; make `tests/unit/test_sniff.py` pass
- [ ] T022 [US1] Implement `src/docreader/pdfpages.py` (research R-1, R-2) with `pypdfium2`: `open_pdf(path)` raising typed errors for `encrypted` (password error), `damaged` (any other open/page-load error) and `no_pages`; `page_metrics(pdf) -> list[PageMetrics(page_number, char_count, image_coverage, invisible_text_share)]` where `char_count` = non-whitespace characters of the text page, `image_coverage` = `union_area` of all image object bounds (including those nested in form XObjects) clipped to the CropBox divided by the CropBox area, `invisible_text_share` = share of text objects with render mode 3 (NULL if there are none); `union_area(rects, clip)`; `classify(metrics, thresholds)` in the simplified MVP form: `char_count < text_min_chars` → `scan`, else `text`; make `tests/unit/test_rect_union.py` pass
- [ ] T023 [US1] Implement `src/docreader/intake.py` (plan «Ключевые решения» 1, research R-4): collect input files (recursive, sorted by path, directory symlinks not followed, nonexistent path → `UserError`); per file: sniff → SHA-256 (streamed) → `open_pdf` + `page_metrics` + `classify` → copy to a temp file in `<data_dir>/originals/`, `fsync`, re-hash and compare (mismatch → `rejected`, `changed_during_add`), `os.replace` to `originals/<sha256>.pdf`, chmod 0444 (if the final file already exists with the same hash, reuse it) → one transaction: `SELECT … FROM document_counter FOR UPDATE`, increment `last_seq`, insert `document` (`copy_path` relative to data dir, `intake_run_id`), `page` rows (`kind_run_id` = run), five `stage_status` rows `pending` → commit; build per-file result objects `added` / `rejected` with `warnings: []`; one `run` per invocation (`settings.command = 'add'`, thresholds from `settings_for_run()`), `finish_run` at the end; write the JSON report to `<data_dir>/reports/intake-<run_id>.json`
- [ ] T024 [US1] Implement intake report rendering in `src/docreader/render.py`: text form exactly as the contracts/cli.md example (header with run, time, version; groups «Добавлено», «Не добавлено» with counts; per document ID, name, pages, kind counts; footer with totals, elapsed time and report path) and the JSON form from contracts/cli.md
- [ ] T025 [US1] Wire `add <путь>... [--label] [--json]` in `src/docreader/cli.py`: calls `intake`, prints the report; on `KeyboardInterrupt` prints the partial report and returns 130 without committing the current file
- [ ] T026 [US1] Run `uv run pytest tests/unit tests/integration/test_add.py tests/integration/test_interrupted_add.py` and fix until green

**Checkpoint**: US1 works on its own — MVP part 1

---

## Phase 4: User Story 2 — Повторное добавление не создаёт дубликатов (Priority: P1)

**Goal**: повторный `add` распознаёт уже известные файлы по содержимому.

**Independent Test**: добавить папку дважды → во второй раз «Добавлено: 0», все файлы «Уже есть» с прежними ID.

### Tests for User Story 2 ⚠️

- [ ] T027 [P] [US2] Write integration tests in `tests/integration/test_duplicates.py` (US2 acceptance 1–3, FR-005, SC-002): adding the same folder twice → document count unchanged, every file `existing` with its original ID; same content under another name → `existing` pointing to the existing ID; same name with different content → `added` with a `name_collision` warning naming the other ID; two identical files inside one `add` call → first `added`, second `existing`

### Implementation for User Story 2

- [ ] T028 [US2] Extend `src/docreader/intake.py`: after hashing, look up `document.sha256` and the hashes already registered in the current run → `existing` with `document_id` (no copy, no transaction); before inserting, query `lower(original_name)` matches with a different hash → `name_collision` warning
- [ ] T029 [US2] Extend `src/docreader/render.py`: «Уже есть: N» group (`<name>  → D-XXXX`) and the `name_collision` warning text «имя совпадает с D-XXXX (другое содержимое)»; JSON `existing` entries per contracts/cli.md

**Checkpoint**: US1 + US2 — повторные запуски безопасны

---

## Phase 5: User Story 3 — Определение вида страниц (Priority: P1)

**Goal**: полное правило «готовый текст / скан / скан со встроенным текстом», предупреждения, подбор порогов (SC-004).

**Independent Test**: добавить цифровой, сканированный и смешанный PDF и скан с невидимым текстом → виды страниц по отдельности соответствуют US3 acceptance 1–4.

### Tests for User Story 3 ⚠️

- [ ] T030 [P] [US3] Write unit tests in `tests/unit/test_page_kind_rule.py` for the full rule (research R-2) with default thresholds 20 / 0.85: `char_count` 19 → `scan` regardless of coverage; `char_count` 20 and coverage 0.84 → `text`; `char_count` 20 and coverage 0.85 → `scan_with_text`; custom thresholds respected
- [ ] T031 [P] [US3] Write integration tests in `tests/integration/test_page_kinds.py` (US3 acceptance 1–4, FR-007): `digital` → all `text`; `image_only` → all `scan`; `mixed` → text pages `text`, image page `scan`; `image_with_invisible_text` → `scan_with_text`; `image_strips` → `scan`; `logo_and_text` → `text`; `blank_page` → `scan`; report warnings `scan_pages` with page numbers, `scan_with_text_pages`, and `large_file` when `page_count > intake.large_file_pages` (set the threshold low in `settings.toml` for the test); `page_kinds` counts in the JSON report
- [ ] T032 [P] [US3] Write integration tests in `tests/integration/test_verify_reclassify.py` for `reclassify` and `page-kinds-check`: changing `full_image_coverage` in `settings.toml` and running `reclassify` changes `page.kind` without reopening files (delete the copy first to prove it), sets `kind_run_id` to a new run with `settings.command = 'reclassify'`, resets all `stage_status` of changed documents to `pending` (set one to `done` first) and leaves unchanged documents untouched; `reclassify D-0001` limits to one document; `page-kinds-check` on a labels CSV prints accuracy and a 3×3 confusion matrix, exits 0 at ≥ 95% and 1 below; unknown document/page or bad `kind` in the CSV → exit 1 with the line number

### Implementation for User Story 3

- [ ] T033 [US3] Replace the simplified `classify` in `src/docreader/pdfpages.py` with the full rule from research R-2 (`not has_text` → `scan`; `has_text and full_image` → `scan_with_text`; otherwise `text`); make `tests/unit/test_page_kind_rule.py` pass
- [ ] T034 [US3] Add warnings in `src/docreader/intake.py` and their texts in `src/docreader/render.py`: `scan_pages` («страницы-сканы на первом этапе не читаются: стр. …»), `scan_with_text_pages` («текст стр. … получен распознаванием и может содержать ошибки», ranges collapsed like `1–9`), `large_file` («N страниц — больше M»)
- [ ] T035 [US3] Implement `reclassify(conn, settings, ids=None, label=None)` in `src/docreader/registry.py`: new run (`stage = 'intake'`, `settings.command = 'reclassify'`), recompute `kind` from stored metrics, update changed pages with the new `kind_run_id`, reset all `stage_status` of documents with changes to `pending` (reason NULL, `run_id` NULL, `updated_at = now()`), return per-document change counts
- [ ] T036 [US3] Implement `page_kinds_check(conn, csv_path)` in `src/docreader/registry.py` (contracts/cli.md): parse UTF-8 CSV with header `document_id,page_number,kind`, validate each row, compare with stored kinds, return total, accuracy, 3×3 confusion matrix and mismatches with their metrics
- [ ] T037 [US3] Wire `reclassify [<ID>...] [--label]` and `page-kinds-check <labels.csv>` in `src/docreader/cli.py` and their output in `src/docreader/render.py`; accuracy below 0.95 → `UserError` (exit 1)

**Checkpoint**: US1–US3 — полный приём и виды страниц

---

## Phase 6: User Story 4 — Посмотреть реестр (Priority: P2)

**Goal**: `list`, `show`, `verify`.

**Independent Test**: после добавления документов `list` показывает все поля, `show D-0001` — данные документа и вид каждой страницы, `verify` — «Копии в порядке».

### Tests for User Story 4 ⚠️

- [ ] T038 [P] [US4] Write integration tests in `tests/integration/test_list_show.py` (US4 acceptance 1–3, FR-008, FR-010, SC-006): `list` on an empty registry prints «Реестр пуст», exit 0; after adding, `list` shows ID, name, pages, counts per kind and all five stages as «ожидает»; names longer than 40 characters truncated with «…» in text, full in `--json`; `show d-1` equals `show D-0001`; `show` prints SHA-256, absolute copy path that exists, source path, size, added date, intake run and per-page kind with metrics; unknown ID → exit 1; a `stage_status` row set to `needs_review` with a reason shows «требует просмотра» and the reason
- [ ] T039 [US4] Add `verify` tests to `tests/integration/test_verify_reclassify.py`: all copies intact → «Копии в порядке: N», exit 0; a copy modified (chmod + write) or deleted → listed, exit 1; `verify D-0002` checks only that document; no run row is created

### Implementation for User Story 4

- [ ] T040 [US4] Implement `list_documents(conn)` and `show_document(conn, seq)` in `src/docreader/registry.py` returning plain dicts with the fields from contracts/cli.md (`page_kinds`, `stages{stage: {state, reason}}`, pages with metrics)
- [ ] T041 [US4] Implement `verify(conn, settings, ids=None)` in `src/docreader/registry.py`: re-hash each copy, report missing and mismatched
- [ ] T042 [US4] Implement list/show/verify rendering in `src/docreader/render.py`: table columns «ID, Имя, Стр., Текст, Скан, Скан+т, Чтение, Структура, Извлеч., Проверки, Индекс.», state names «ожидает / готово / требует просмотра / ошибка», JSON forms per contracts/cli.md
- [ ] T043 [US4] Wire `list [--json]`, `show <ID> [--json]`, `verify [<ID>...]` in `src/docreader/cli.py`

**Checkpoint**: US1–US4 — реестр виден целиком

---

## Phase 7: User Story 5 — Удалить документ (Priority: P3)

**Goal**: удаление с подтверждением, журнал удалений.

**Independent Test**: добавить документ, удалить с подтверждением → его нет в `list`, копии нет, запуск и запись в журнале есть.

### Tests for User Story 5 ⚠️

- [ ] T044 [P] [US5] Write integration tests in `tests/integration/test_remove.py` (US5 acceptance 1–3, FR-011, FR-003): `remove D-0001 --yes` → no `document`, `page`, `stage_status` rows for it, copy file gone, `run` rows unchanged, one `deletion_log` row with ID, original name, SHA-256; confirmation by typing the ID via `input=` works; wrong or empty input → «Удаление отменено», exit 1, nothing changed; non-TTY stdin without `--yes` → exit 1, nothing changed; re-adding the same file after removal → new document with the next ID (removing the last document and adding a new one never reuses its number); copy-file deletion failure (make the folder read-only) → warning, exit 0, rows deleted

### Implementation for User Story 5

- [ ] T045 [US5] Implement `remove(conn, settings, seq)` in `src/docreader/registry.py`: one transaction inserting into `deletion_log` and `DELETE FROM document WHERE id = …` (cascade), commit, then unlink the copy; unlink failure returned as a warning
- [ ] T046 [US5] Wire `remove <ID> [--yes]` in `src/docreader/cli.py`: print ID, name, pages, copy path; require typing the ID unless `--yes`; refuse when stdin is not a TTY and `--yes` is absent

**Checkpoint**: все истории реализованы

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T047 Add `--note ТЕКСТ` to `add` (FR-006) in `src/docreader/cli.py` and `src/docreader/intake.py` (stored in `document.note`, shown by `show`), with a test in `tests/integration/test_add.py`
- [ ] T048 [P] Add a «Commands» section to `CLAUDE.md`: `uv sync`, `uv run pytest`, required `DOCREADER_TEST_DATABASE_URL`, `uv run docreader --help`
- [ ] T049 Run the full suite `uv run pytest` and fix failures; confirm no test needs the network or a real model
- [ ] T050 Validate quickstart.md part A on the development server (synthetic demo set: two `add` runs, `list`, `show`, `remove`, `verify`) and correct quickstart.md where actual output differs; part B is left to the analyst on the Mac

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies; T004 needs the analyst (sudo)
- **Foundational (Phase 2)**: after Setup; blocks all stories. Inside: T005 → T006 → T007; T008 → T009; T010 → T011 → T012 → T013; T014 needs T007, T011, T013; T015 independent; T016 needs T013, T014
- **US1 (Phase 3)**: after Foundational
- **US2 (Phase 4)**: after US1 (extends `intake.py`, `render.py`)
- **US3 (Phase 5)**: after US1 (extends `pdfpages.py`, `intake.py`); do it after US2 because both edit `intake.py`
- **US4 (Phase 6)**: after US1; T039 after T032 (same test file)
- **US5 (Phase 7)**: after US1; T045 after T040 (same `registry.py`)
- **Polish (Phase 8)**: after all stories

### Within Each User Story

- Tests first and failing, then implementation
- `sniff.py`, `pdfpages.py` before `intake.py`; `intake.py` before `render.py` and CLI wiring
- `registry.py`, `render.py`, `cli.py` are shared files — tasks touching them run sequentially

### Parallel Opportunities

- Phase 1: T002, T003
- Phase 2: T005, T006, T008, T010 (different files); T015 at any time
- US1: T017, T018, T019, T020 together; T021 alongside T022
- US2: T027 can be written while US1 implementation is in progress (needs T015)
- US3: T030, T031, T032 together
- US4: T038 in parallel with any US3 implementation task; T039 only after T032 (same file)
- US5: T044 in parallel with US4 implementation

---

## Parallel Example: User Story 1

```text
Task: "Write unit tests for sniff in tests/unit/test_sniff.py"                    (T017)
Task: "Write unit tests for union_area in tests/unit/test_rect_union.py"          (T018)
Task: "Write integration tests in tests/integration/test_add.py"                  (T019)
Task: "Write interrupted-add test in tests/integration/test_interrupted_add.py"   (T020)
```

---

## Model Routing (CLAUDE.md «Model routing»)

| Who | Tasks | Why |
|---|---|---|
| Main session, Opus (not delegated) | T007, T010, T011, T022, T023, T028, T033, T045 | privacy guards, schema and migrations, page metrics and classification rule, atomic intake, dedup, transactional delete |
| `implementer` with `model: "haiku"` | T001, T002, T003, T005, T024, T029, T042, T043, T048 | scaffolding, config, output formatting, simple CLI wiring |
| `implementer` (Sonnet, default) | all other tasks | tests and ordinary implementation |
| Analyst | T004 (sudo), quickstart part B | needs root / real data on the Mac |

---

## Implementation Strategy

### MVP (сквозной прототип, spec «Минимальная версия»)

1. Phase 1 + Phase 2
2. Phase 3 (US1) — includes the simplified page kind («есть текст / нет текста»)
3. Phase 4 (US2)
4. From Phase 6 only `list` (list part of T040, table part of T042, `list` part of T043)
5. **STOP and VALIDATE**: `add` twice on the synthetic set, then `list`

### Incremental Delivery

1. MVP → прототип может идти к фиче 03
2. US3 → полный вид страниц и замер SC-004 аналитиком на ноутбуке
3. US4 → `show`, `verify`
4. US5 + Polish → удаление, заметки, проверка quickstart

---

## Notes

- Commit after each task or logical group (the main session commits, not the implementer)
- Tests never touch real data or real models; no `real_model` tests in this feature
- Stop at any checkpoint to validate the story independently
