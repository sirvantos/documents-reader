---
description: "Task list for feature 13 (branch 003): scan page recognition"
---

# Tasks: Распознавание страниц-сканов

**Input**: Design documents from `specs/003-scan-recognition/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/engine.md](contracts/engine.md), [quickstart.md](quickstart.md)

**Tests**: обязательны. Этого требуют план (раздел Testing), research R-13
и quickstart А. Тесты пишутся раньше кода, по правилам CLAUDE.md, «Model routing»:

- критичные задачи: и тесты, и код пишет главная сессия (Opus);
- обычные задачи: Opus пишет тесты, запускает их и убеждается, что они падают
  по нужной причине. Затем `implementer` (Sonnet) доводит их до зелёного;
- механические задачи: и тесты, и код пишет Haiku.

Исполнитель не меняет тесты, написанные главной сессией.

**Organization**: фазы следуют шагам 1–5 из «Порядка поставки» в plan.md, как
в фиче 03. Задачи помечены историями пользователя из spec.md (US1…US7). Шаг 1
(Phase 3) — минимальная версия для сквозного прототипа: его можно влить без
остальных шагов. Реальный набор с ним можно распознать только после шага 2, когда
выбран движок.

## Format: `[ID] [P?] [Story] Description — executor`

- **[P]**: задачу можно выполнять параллельно с другими: она меняет другие файлы
  и не зависит от незавершённых задач
- **[Story]**: история пользователя (US1…US7)
- **executor** (CLAUDE.md, «Model routing»):
  - `opus` — главная сессия сама, без делегирования. Сюда относятся:
    - критичные задачи: схема и миграция, правила решений (флаги, состояния,
      сброс чтения), транзакция на страницу, интерфейс движка и его подмены,
      защиты, которые не дают движку запуститься на сервере;
    - все тесты к задачам `sonnet`;
  - `sonnet` — `implementer` на своей модели: делает зелёными тесты, которые
    написал Opus;
  - `haiku` — `implementer` с `model: "haiku"`: механические задачи (зависимости
    и конфиг, раздел настроек, аргументы CLI, вывод, CSV, генераторы синтетических
    сканов). Тесты и код он пишет сам;
  - `analyst` — аналитик на Mac, без агента. Агенту он передаёт только цифры
    или вывод по синтетике
- Пути указаны от корня репозитория. Раскладка — в plan.md, раздел «Source Code».

## Общие правила для всех задач

- Решения из plan.md, research.md (R-1…R-14), data-model.md и contracts/ обязательны.
- **Движок распознавания на этом сервере не устанавливается и не запускается**
  (CLAUDE.md, «Machines»; research R-4). Языковые данные и веса не скачиваются.
  Настоящий движок вызывает только `tests/real_model/`, а эта группа по умолчанию
  исключена. Остальные тесты используют подмены из `tests/fakes/ocr.py`: их передаёт
  параметр `engine_factory` функции `recognize_documents`.
- Используются только синтетические файлы. Их создают в фикстурах (`tmp_path`)
  генераторы `tests/synthetic/make_pdfs.py` и `tests/synthetic/make_scans.py`.
  `$DOCREADER_DATA_DIR` настоящей машины и реальные договоры не трогаются, сами PDF
  в репозиторий не кладутся.
- Файлы в `tests/recordings/` не правятся вручную и не придумываются. Если записи нет
  или она устарела, работа останавливается, и аналитика просят перезаписать её на Mac.
- Сетевой сторож из `tests/conftest.py` остаётся включённым.
- `ocr.py`, `pagetext.py`, `quality.py` и расчётные функции `recognition_eval.py`
  остаются чистыми функциями без базы, поэтому их модульным тестам в `tests/unit/`
  PostgreSQL не нужен.
- Копия файла открывается только для чтения. Изображение страницы на диск
  не пишется (FR-007, R-5).
- В `page_recognition` текст хранится ровно таким, каким его отдал движок (FR-010).
  Знаки приводит только чтение, по правилам фичи 03.
- Одинаковый вход даёт одинаковый результат. Отпечатки и текст не зависят от времени,
  порядка словарей и случайности.
- Сообщения пользователю — на русском, как в contracts/cli.md. Код, идентификаторы
  и комментарии — на английском.
- Прежде чем отметить задачу `[X]`, главная сессия запускает полный набор тестов,
  `uv run ruff check .` и `uv run mypy`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: `Pillow` становится основной зависимостью; папка синтетики попадает
в `.gitignore`; первые два слоя запрета движка на сервере (R-4)

- [X] T001 Move `pillow` from the `dev` dependency group to `[project] dependencies` in `pyproject.toml` (keep it in no other group), run `uv lock` and `uv sync`; add `tests/synthetic/out/` to `.gitignore`; `docker compose build tests` and check `docker compose run --rm tests -x -q` stays green — executor: haiku
- [X] T002 [P] Guard layers 2–3 of research R-4: (a) add `DOCREADER_FORBID_MODELS: "1"` to the `environment` of the `tests` and `lint` services in `compose.yaml`; (b) add an autouse fixture to `tests/conftest.py` that sets `DOCREADER_FORBID_MODELS=1` via `monkeypatch.setenv` for every test **not** marked `real_model` (check `request.node.get_closest_marker("real_model")`) and leaves the environment untouched for `real_model` tests; (c) add `tests/unit/test_forbid_models_fixture.py` asserting the variable is `"1"` inside an ordinary test — executor: opus

**Checkpoint**: полный набор зелёный, как до фичи; в `docker compose run --rm tests`
задано `DOCREADER_FORBID_MODELS=1`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: то, на чём стоят шаги 1–5: схема, этап, настройки, интерфейс движка
с подменами, чистые функции для изображения и координат, генератор сканов

**⚠️ CRITICAL**: работа над шагами начинается только после этой фазы

- [X] T003 Write failing tests for the migration in `tests/integration/test_migrate.py` and the stage list in `tests/unit/test_stages.py` — executor: opus
  - `0003_recognition` listed as applied; re-run of `migrate` is a no-op
  - a document added before `0003` is applied (apply `0001` and `0002`, add a document, then `0003`) gets a `stage_status` row `('recognition', 'pending')`; a document added after the migration gets it from `stages.create_pending`
  - `page_text.source` defaults to `'pdf'` for old rows; `'other'` rejected
  - `page_flag.code` accepts `'low_recognition_quality'` and `'scan_no_text'`, still rejects unknown codes
  - `page_recognition` rejects: `turn = 45`; `dpi = 50`; `quality = 1.5`; `ink_share = -0.1`; `error = ''`; `error` not null with non-empty `lines`; `error` not null with `quality` not null; `result_sha256` not 64 hex chars; `seconds < 0`; deleting a referenced `run` (RESTRICT); deleting the document removes its rows (CASCADE via `page`); `orientation_unknown` defaults to `false`
  - `Stage` equals the `stage_status.stage` CHECK, in order `recognition, reading, structure, extraction, checks, indexing`; `RunStage.RECOGNITION == "recognition"`; `later_stages(Stage.READING)` unchanged
- [X] T004 Make T003 pass: write `src/docreader/migrations/0003_recognition.sql` exactly per data-model.md; in `src/docreader/stages.py` add `Stage.RECOGNITION = "recognition"` as the **first** member, `RunStage.RECOGNITION`, and `reset_stage(conn, doc_id, stage, reason, run_id)` (sets `pending` with the reason and run only when the current state is not `pending`; one `UPDATE`, no transaction of its own); extend the `tests/conftest.py` cleanup to empty `page_recognition` — executor: opus
  - `page_recognition`: `document_id text`, `page_number integer`, PK (`document_id`, `page_number`), FK (`document_id`, `page_number`) → `page` `ON DELETE CASCADE`; `engine text NOT NULL CHECK (btrim(engine) <> '')`; `engine_version text NOT NULL CHECK (btrim(engine_version) <> '')`; `dpi smallint NOT NULL CHECK (dpi BETWEEN 72 AND 1200)`; `turn smallint NOT NULL CHECK (turn IN (0, 90, 180, 270))`; `orientation_unknown boolean NOT NULL DEFAULT false`; `lines jsonb NOT NULL CHECK (jsonb_typeof(lines) = 'array')`; `quality real NULL CHECK (quality BETWEEN 0 AND 1)`; `ink_share real NULL CHECK (ink_share BETWEEN 0 AND 1)`; `result_sha256 char(64) NOT NULL CHECK (result_sha256 ~ '^[0-9a-f]{64}$')`; `seconds real NOT NULL CHECK (seconds >= 0)`; `error text NULL CHECK (error IS NULL OR btrim(error) <> '')`; `run_id bigint NOT NULL` FK → `run` `ON DELETE RESTRICT`; `recognized_at timestamptz NOT NULL DEFAULT now()`; `CHECK (error IS NULL OR (jsonb_array_length(lines) = 0 AND quality IS NULL))`
  - `stage_status`: replace the stage CHECK with `stage IN ('recognition', 'reading', 'structure', 'extraction', 'checks', 'indexing')`; `INSERT INTO stage_status (document_id, stage) SELECT id, 'recognition' FROM document`
  - `page_text`: `ADD COLUMN source text NOT NULL DEFAULT 'pdf' CHECK (source IN ('pdf', 'recognized'))`
  - `page_flag`: replace the code CHECK with `code IN ('scan_unread', 'ocr_text', 'unreadable', 'maybe_not_russian', 'empty', 'reading_order_unknown', 'low_recognition_quality', 'scan_no_text')`
- [X] T005 [P] Add `RecognitionSettings` and the `[recognition]` section to `src/docreader/config.py`, with tests in `tests/unit/test_config_recognition.py`: defaults exactly as data-model.md «Настройки» (`engine = ""`, `dpi = 300`, `try_rotations = true`, `page_min_quality = 0.80`, `line_min_confidence = 0.60`, `max_low_line_share = 0.20`, `blank_max_ink_share = 0.003`, `model_dir = ""`); the settings parser now accepts `str` (`engine`, `model_dir`) and `bool` (`try_rotations`) values — a bool is still rejected for numeric keys and a number for string/bool keys; ranges: `dpi` 72–1200, shares and confidences in `[0, 1]`; unknown key → `EnvironmentProblem`; `settings_for_run()` gets key `recognition` with the resolved values and stays JSON-serialisable; existing `tests/unit/test_config*.py` stay green. Do not check `engine` against the engine table here (T010 does) — executor: haiku
- [X] T006 Define the engine interface and the hand-written fakes (contracts/engine.md; critical per CLAUDE.md): types `EngineLine`, `EngineOutput` and protocol `RecognitionEngine` in `src/docreader/ocr.py` (types only in this task); `tests/fakes/__init__.py` and `tests/fakes/ocr.py` with `ScriptedEngine(outputs)` (returns the given `EngineOutput`s by call number, records the size of every image it gets), `FailingEngine(fail_calls, inner)` (raises `RuntimeError("engine failed")` on the given call numbers, otherwise delegates), `InterruptingEngine(after, inner)` (raises `KeyboardInterrupt` on call `after`), each with `name` and `version` attributes; unit tests of the fakes in `tests/unit/test_ocr_fakes.py` — executor: opus
- [X] T007 [P] Write failing unit tests for the pure image and coordinate functions of `src/docreader/ocr.py` (research R-5, R-6, R-9, R-10, R-11) — executor: opus
  - `tests/unit/test_ocr_coords.py`: `image_box_to_pdf(box, *, scale, turn, rotation, crop)` for every `rotation` in 0/90/180/270 × every `turn` in 0/90/180/270 on a 595×842 page: image corners map to page corners; a known inner box maps to its hand-computed PDF box; a CropBox with origin `(10, 20)` shifts the result; the result is `(left, bottom, right, top)` with `left < right` and `bottom < top`; a skewed box gives the enclosing box
  - `tests/unit/test_ocr_quality.py`: `page_quality(lines)` — mean confidence weighted by non-space chars over lines with at least one letter or digit; lines of only `_`, dashes, dots and other marks (form blanks, underlines) are left out, so adding a low-confidence `__________` line does not change the value; `None` without lines or with only such lines; a line «"___" __________ 2024 г.» is counted (it has digits); `ink_share(image)` — white image → 0.0, a black square of known size → its share, a black border of 3% is ignored; `result_sha256(lines, turn, orientation_unknown, quality, ink_share)` — stable for equal input, changes when a text, a bbox beyond 0.01 pt, a confidence beyond 0.001, `turn`, `orientation_unknown`, `quality` or `ink_share` changes, unchanged by noise below the rounding; `orientation_score(lines)` (R-6) — Cyrillic words with a vowel score higher than mirrored or garbage text
- [X] T008 Make T007 pass: implement in `src/docreader/ocr.py` `render_page(pdf_page, dpi) -> PIL.Image.Image` (`page.render(scale=dpi / 72).to_pil().convert("L")`, nothing written to disk), `image_box_to_pdf`, `page_quality`, `ink_share`, `result_sha256` (canonical JSON with `sort_keys=True`, `ensure_ascii=False`, rounding as research R-11), `orientation_score`; move the display→PDF point mapping out of `pagetext._pdf_point` into a helper shared by both modules, keeping `pagetext` behaviour identical (existing `tests/unit/test_pagetext_lines.py` and `tests/unit/test_columns_tables.py` stay green unchanged) — executor: sonnet
- [X] T009 [P] Write failing tests for the engine guards in `tests/unit/test_ocr_engines_guard.py` (research R-4; critical) — executor: opus
  - `load_engine` with `engine = ""` → `EnvironmentProblem` «Не выбран движок распознавания — укажите [recognition] engine в settings.toml (выбор — замером, quickstart Б1)»
  - unknown name → `EnvironmentProblem` listing the known names
  - with `DOCREADER_FORBID_MODELS=1` (set by the conftest fixture) → `EnvironmentProblem` «На этой машине движок распознавания не запускается (DOCREADER_FORBID_MODELS)» for **every** name in `ENGINES`, and the factory is never called (register a spy factory under a test name with `monkeypatch.setitem`)
  - without the variable and with a factory raising `ImportError` → `EnvironmentProblem` with the hint from the factory
  - before the factory runs, `HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, `HF_HUB_DISABLE_TELEMETRY` and `DISABLE_TELEMETRY` are `"1"` in `os.environ`
- [X] T010 Make T009 pass: `src/docreader/ocr_engines.py` with `EngineFactory`, `ENGINES: dict[str, EngineFactory] = {}` (the adapters come in T031) and `load_engine(settings, data_dir)` running the checks in the order of contracts/engine.md «Загрузка»; this is the only place that reads `DOCREADER_FORBID_MODELS` — executor: opus
- [X] T011 [P] Write `tests/synthetic/make_scans.py` (research R-13) with its own tests in `tests/unit/test_make_scans.py` — executor: haiku
  - pipeline: draw a page with `reportlab` and DejaVu Sans (reuse the helpers and `CONTRACT_RU_PAGES` of `tests/synthetic/make_pdfs.py`), render it with `pypdfium2` at 200 dpi, alter it with Pillow, embed it as one full-page image into a new PDF without a text layer
  - variants in this task: `clean`; `mixed` (text pages from `make_contract_ru` with scan pages between them); `faded_noisy` (lower contrast, Gaussian noise with a fixed seed); `page_rotate_90` (a scan page with `/Rotate 90`); `requisites_two_columns` (customer and contractor requisites side by side: names, ИНН, КПП, ОГРН, bank details)
  - each generator returns the path and writes `<name>.truth.json`: for each page the exact line texts in reading order and each line's box in PDF page coordinates `[left, bottom, right, top]`; module constant `SCAN_GENERATOR_VERSION = 1`
  - `python -m tests.synthetic.make_scans DIR` writes all variants plus one text-only contract (`make_contract_ru`) into `DIR`
  - tests: with the default thresholds `docreader.pdfpages` classifies every page of a scan variant as `scan` and the text pages of `mixed` as `text`; `truth.json` boxes lie inside the page; two runs with the same arguments give byte-identical output
- [X] T012 Add `TruthEngine(truth, page_of_call)` to `tests/fakes/ocr.py`: returns the exact truth lines of the page, with their PDF boxes converted to pixels of the image it receives (inverse of `image_box_to_pdf` with `turn = 0`, using the page `rotation`; `scale` from the image size), `confidence = 0.99`, `orientation = None`, one line per truth line; unit test in `tests/unit/test_ocr_fakes.py` that `image_box_to_pdf` applied to its output gives back the truth boxes within 0.5 pt — executor: opus
- [X] T013 Write and pass `tests/integration/test_render_scan.py` (research R-5, no engine; a failure caused by `ocr.py` goes back to T008 for sonnet): a synthetic PDF with a black rectangle at a known PDF position on pages with `/Rotate` 0/90/180/270 and a page with a CropBox offset; `ocr.render_page` at 100 dpi; find the rectangle by its pixels; map it back with `image_box_to_pdf` → equals the drawn rectangle within 1 pt — executor: opus

**Checkpoint**: `migrate` применяет `0003_recognition`, полный набор зелёный. Без
движка уже есть интерфейс, подмены, координаты и синтетические сканы.

---

## Phase 3: Шаг 1 — минимальная версия для сквозного прототипа (US1, US2, US3) 🎯 MVP

**Goal**:

- `docreader recognize` распознаёт страницы-сканы переданным движком: транзакция
  на страницу, продолжение после прерывания, сброс чтения, состояние этапа;
- `read` строит текст страниц-сканов из распознанных строк;
- флаг `low_recognition_quality` с предварительным порогом;
- `show` и `text --page` показывают, что текст получен распознаванием.

**Independent Test**: на синтетике `clean`, `mixed`, `faded_noisy`
и `requisites_two_columns` с `TruthEngine` и `ScriptedEngine` выполнить `recognize`,
затем `read`. Ожидается:

- `text --find` находит фразу через перенос строки, её `bbox` совпадает
  с `truth.json`;
- если прервать распознавание на 3-й странице и запустить снова, результат
  совпадает с непрерывным прогоном;
- бледная страница получает флаг, документ — состояние «требует просмотра».

### Tests for Шаг 1 ⚠️

> Пишутся первыми и должны падать до реализации

- [X] T014 [P] [US1] Write failing integration tests in `tests/integration/test_recognize.py` (call `recognition.recognize_documents(conn, settings, seqs, ..., engine_factory=...)`; for exit codes and output use `cli.main`) — executor: opus
  - US1-1, FR-001…FR-003: an all-scan `clean` document with `TruthEngine` → one `page_recognition` row per page, `error IS NULL`, `lines` with `i`, `text`, `bbox` inside the page and `confidence`; `quality` set; `engine`, `engine_version`, `dpi`, `turn = 0`, `seconds >= 0` and `run_id` filled
  - US1-2: `mixed` → rows only for scan pages; the engine got exactly as many images as there are scan pages
  - US1-3: text-only document → state `done`, `engine_factory` never called (spy), exit 0
  - open question 1 (default): a `scan_with_text` page (`make_image_with_invisible_text`) is not recognised — no `page_recognition` row, the engine not called for it, the document `done`; after `read` the page keeps `ocr_text` and `source = 'pdf'`
  - US1-5, FR-007: SHA-256 of the copy unchanged; nothing written under `$DOCREADER_DATA_DIR` outside `reports/` (walk the tree before and after)
  - US1-6, FR-013: `InterruptingEngine(after=3)` on a 5-page document → 2 rows saved, `interrupted = True`, recognition state not `done`; a second run without IDs recognises only pages 3–5; the final rows equal those of an uninterrupted run on a fresh database (compare `result_sha256`), no duplicates
  - US1-7, FR-011, SC-008: after a full run, `recognize` without IDs → «Нечего распознавать…», no new `run`, `stage_status` rows unchanged; `recognize D-0001` without `--force` recognises 0 pages
  - FR-012: a document read **before** recognition (`read` → pages `scan_unread`) → after `recognize`, `reading` is `pending` with reason «распознанный текст изменён» and the recognition `run_id`; `structure`…`indexing` untouched; a document whose `reading` is already `pending` keeps its old reason
  - FR-014: every scan page saved → `done`; `FailingEngine` on page 2 → the other pages saved, state `needs_review` with reason «стр. 2: ошибка распознавания — RuntimeError: engine failed»; the row of page 2 has `error`, empty `lines` and `quality IS NULL`
  - FR-016: copy deleted for one of two documents → that one `failed` with a reason naming `docreader verify`, the other recognised, exit 0
  - environment: `engine_factory` raising `EnvironmentProblem` → exit 2 with its message; pages saved before stay
  - FR-015: one `run` per command with `stage = 'recognition'`, `model = '<name> <version>'`, `settings.recognition` including `engine_version` and the platform; `--label` stored; `model IS NULL` when no page needed the engine
  - selection: `--all` with IDs → exit 1; unknown ID → exit 1 and nothing recognised
- [X] T015 [P] [US2] Write failing unit tests in `tests/unit/test_recognized_layout.py` for `pagetext.lines_from_recognized(lines, *, rotation, width, height, settings, continues_columns=False)` (no `crop`: the boxes are in the same space as PDF chars) (research R-7) — executor: opus
  - fragments whose vertical extents overlap by at least half the smaller height become one `Line` with the fragments as segments, left to right; lines go top to bottom in display space
  - input like `requisites_two_columns` (two fragments per row with a steady x gap) → all left-column lines, then all right-column lines, `column` 1 and 2
  - three-cell table rows → the cells of one row are adjacent in one line, `table` is null; more than `UNRESOLVED_MIN_LINES` such rows outside a column area → counted in `unresolved_lines`
  - `/Rotate 90` input in unrotated PDF boxes → correct display order
  - `Line.to_json()` contains `confidence` for recognised lines, and lines built from PDF chars do **not** contain the key
  - text normalised by R-5 of feature 03 exactly once
- [X] T016 [P] [US3] Write failing unit tests in `tests/unit/test_recognition_flags.py` for `quality.recognition_flags(lines, quality, ink_share, orientation_unknown, settings)` (research R-8, R-9; critical) — executor: opus
  - `quality < page_min_quality` → `low_recognition_quality` with reason «оценка 0,71 < 0,80»
  - share of lines with `confidence < line_min_confidence` above `max_low_line_share` → the same flag with reason «9 из 31 строки с уверенностью < 0,60»; when both conditions hold, both parts are joined with «; »
  - lines without any letter or digit are left out of the low-confidence share, both numerator and denominator (research R-9): a page of good text plus ten low-confidence `__________` lines gets no flag, and the reason counts only the remaining lines; a page with only such lines → no `low_recognition_quality`
  - exactly at a threshold → no flag; no lines → no `low_recognition_quality` (T041 adds `scan_no_text` and `empty`)
  - `FLAG_NAMES` has «низкое качество распознавания» and «текст на скане не найден»; `document_state` treats `low_recognition_quality` as non-neutral
  - `scan_unread` reasons: «распознавание не выполнено — docreader recognize D-0003» and «ошибка распознавания: <error>»
  - numbers in reasons use a decimal comma
- [X] T017 [US2] Write failing integration tests in `tests/integration/test_recognize_reading.py` (recognise with fakes, then `read`) — executor: opus
  - US2-1, FR-004, FR-009: recognised scan pages → `page_text.source = 'recognized'`, lines with `confidence`, no `scan_unread`; text pages of `mixed` → `source = 'pdf'`; page order of `document_text` follows the document
  - US2-2: a scan page without a `page_recognition` row → `scan_unread` with «распознавание не выполнено — docreader recognize D-…», the other pages read; a row with `error` → `scan_unread` «ошибка распознавания: …»
  - US2-3: `text --find` with a phrase spanning a line break on a `clean` page → found once; its `bbox` equals the truth box of that line within 1 pt; `page` and `line` correct
  - US2-4: the same header line on every page → `role = header`, absent from `document_text`; a word hyphenated across two recognised lines → joined in `document_text`
  - US2-5: after `recognize` resets `reading` to `pending`, `read` without arguments re-reads the document
  - US2-6: `ScriptedEngine` returns «Подрядчик обязуется выполнитъ» → `textnorm.locate(text, "Подрядчик обязуется выполнить")` finds nothing; the stored text is unchanged
  - US3-1, US3-2: `ScriptedEngine` with low confidences on page 2 → `low_recognition_quality` with numbers, the page text stored, `reading` = `needs_review` with «стр. 2: низкое качество распознавания»
  - US3-3: all pages recognised with confidence 0.99 → `reading` = `done`, no flags
  - `requisites_two_columns` with `TruthEngine` → left-column lines before right-column lines in `document_text`
  - `run.settings` of the reading run contains the `recognition` thresholds
  - edge case «буквы не русского алфавита»: `ScriptedEngine` returns a line with three Kazakh letters (`kazakh_ru_lines(3)` from `make_pdfs`) → `maybe_not_russian` after `read`, the letters stored unchanged
  - regression: the existing feature 03 tests (`tests/integration/test_read*.py`, `tests/unit/test_pagetext_lines.py`, `tests/unit/test_columns_tables.py`) stay green unchanged; in addition, for `make_contract_ru` the `document_text.text` equals the text built from the generator's known lines exactly as `tests/integration/test_read.py` already asserts, and `page_text.source = 'pdf'` on every page
- [X] T018 [P] [US1] Write failing integration tests in `tests/integration/test_recognize_show.py` for US1-4 (contracts/cli.md «Изменения в существующих подкомандах») — executor: opus
  - `show D-…`: «Распознавание: готово» under «Этапы»; a recognised scan page shows `распознано <engine> <version>, <dpi> dpi, <дата время>, оценка 0,99`; a page with an error shows `ошибка распознавания: …`; in `show --json` each page has a `recognition` object or `null`
  - `text D-… --page N`: `Источник: распознано (<engine> <version>, оценка 0,99)` or `Источник: текстовый слой PDF`; confidence per recognised line; `--json` has `source` and `confidence`

### Implementation for Шаг 1

- [X] T019 [US1] Implement `src/docreader/recognition.py` to make T014 pass (research R-11, data-model «Порядок записи»; critical: transaction and reset rule) — executor: opus
  - `recognize_documents(conn, settings, seqs, *, all_documents=False, force=False, pages=None, label=None, engine_factory=ocr_engines.load_engine, progress=None) -> RecognizeResult` (dataclasses, not dicts — tech-context «Правила кода»); the `pages` and `force` parameters exist now, their CLI flags come in T029
  - selection per the R-11 table; scan page = `kind = 'scan' AND image_coverage > 0`; «successful» = a row with `error IS NULL`
  - the engine is loaded lazily, once per run, at the first page that needs it; the `run` is started before the first document; `run.model` is set when the engine loads
  - per page: `render_page` → `ink_share` → `engine.recognize` → `image_box_to_pdf` for every line → `page_quality` → `result_sha256` → one `with conn.transaction()`: `stages.lock(..., Stage.RECOGNITION)`, previous `result_sha256 … FOR UPDATE`, `INSERT … ON CONFLICT (document_id, page_number) DO UPDATE`, and `stages.reset_stage(conn, doc_id, Stage.READING, "распознанный текст изменён", run_id)` when the fingerprint changed or is new
  - an engine exception on a page → a row with `error` (`f"{type(exc).__name__}: {exc}"`, first line, at most 500 chars), empty `lines`, `quality NULL`, the fingerprint of the empty result; `EnvironmentProblem` propagates
  - per document, after its last page: delete rows of pages that are no longer scans; write the state per R-11 (`done` / `needs_review` with «стр. N, M: ошибка распознавания — …» / `failed`) in its own short transaction
  - `KeyboardInterrupt` → the current page is rolled back, the result has `interrupted = True`, the document state is not written; `finish_run` always runs
  - progress per page goes through the `progress` callback; the logic prints nothing
  - turning (R-6) is **not** in this task (T043): `turn = 0`, `orientation_unknown = false`
- [X] T020 [US1] (after T019 and T022) Add `recognize [<ID>...] [--all] [--label МЕТКА] [--json]` to `src/docreader/cli.py` (dispatch, exit 130 on interruption, a progress callback writing to stderr) and the `recognize` text and JSON output to `src/docreader/render.py` exactly as contracts/cli.md (the «низкое качество / без текста / пустых» counts come from `quality.recognition_flags`; the «Чтение сброшено…» line; «Итого…» with seconds per page; decimal comma), with tests in `tests/unit/test_render_recognition.py` — executor: haiku
- [X] T021 [US2] Implement `pagetext.lines_from_recognized` to make T015 pass: split `layout_page` into «chars → lines» and «lines with segments → reading order and columns», so both sources share `_column_areas`, `_column_part` and the unresolved count; recognised fragments become `Segment`s in display space; `Line` gets an optional `confidence` (the minimum of its fragments), written by `to_json()` only when set; `has_table = False` for recognised pages; existing pagetext tests stay green unchanged — executor: sonnet
- [X] T022 [US3] Implement `quality.recognition_flags`, the two new `FLAG_NAMES` entries and the new `scan_unread` reasons to make T016 pass (only the `low_recognition_quality` part; `scan_no_text` and `empty` by ink come in T042) — executor: opus
- [X] T023 [US2] Change `src/docreader/reading.py` to make T017 pass: load the document's `page_recognition` rows once; for a scan page with a successful row, build lines with `lines_from_recognized`, set `source = 'recognized'`, and flags = `content_flags(..., map_errors=0)` (no `ocr_text` for kind `scan`) + `layout_flag` + `recognition_flags`; without a row or with `error` → `scan_unread` with the new reasons; write `page_text.source`; add the `recognition` settings to the reading `run.settings`. Everything else (cleanup, `document_text`, spans, reset of later stages, state) stays as it is — executor: sonnet
- [X] T024 [US1] Make T018 pass: recognition facts for `show` in `src/docreader/registry.py` (one `LEFT JOIN page_recognition`), `source` and `confidence` in `text --page` in `src/docreader/textview.py`, rendering in `src/docreader/render.py`, and the «Распознавание» stage name in the stage labels — executor: sonnet
- [X] T025 [US1] Checkpoint for Шаг 1: full suite, `ruff`, `mypy`, `docker compose run --rm tests`; manual quickstart А2 on this server in a throwaway data dir with the `docreader_demo` database. Expect: exit 2 «На этой машине движок распознавания не запускается…» on the first scan document, `done` for the text contract, and `scan_unread` with «распознавание не выполнено…» after `read` — executor: opus

**Checkpoint (шаг 1 можно влить)**: с подменами работает весь путь «распознано →
прочитано → найдено». Чтобы распознать реальный набор, нужен шаг 2.

---

## Phase 4: Шаг 2 — замер и выбор движка (US5 частично, US6)

**Goal**:

- `--force` и `--pages` для замера на выбранных страницах;
- `recognize-eval`: доля верных знаков, реквизиты, контрольные строки, пропуски
  и повторы строк;
- адаптеры `tesseract` и `apple_vision`;
- замер на Mac, выбор движка записан.

**Independent Test**: на синтетике с `TruthEngine` и `ScriptedEngine` (одна
подменённая цифра):

- `recognize-eval` с текстами из `truth.json` даёт ожидаемые доли;
- `--pages 2-3` распознаёт только эти страницы;
- `--force` с тем же результатом не сбрасывает чтение.

### Tests for Шаг 2 ⚠️

- [X] T026 [P] [US6] Add failing tests to `tests/integration/test_recognize.py` — executor: opus
  - US6-1: `--force` with an engine giving the same output → same `result_sha256`, one row per page, `reading` state unchanged (was `done`)
  - US6-2: `--force` with a different output (`ScriptedEngine`) → `reading` = `pending` «распознанный текст изменён»; `page_text`, `document_text` and the `structure`…`indexing` rows unchanged until `read`
  - US6-3: `recognize D-0001 --pages 2-3` → only pages 2 and 3 recognised (engine call count, `recognized_at`), the others untouched; `--pages 3` (one page) works
  - errors (exit 1, nothing recognised): `--pages` without an ID or with two IDs → «--pages указывается для одного документа»; page 9 of 5 → «В документе D-0001 нет страницы 9 (страниц: 5)»; a text page of `mixed` → «Стр. 1 документа D-0001 — не скан (вид: готовый текст); распознаются только страницы-сканы»; malformed ranges `3-1` and `a` → exit 1
  - `recognize --json` page entries have `result_sha256` and `changed`
- [X] T027 [P] [US5] Write failing tests for `recognize-eval` (research R-12) — executor: opus
  - `tests/unit/test_recognition_eval.py`: `levenshtein(a, b)` on known pairs (empty, equal, one substitution, insertion, deletion, Cyrillic); `char_accuracy(expected, got)` after `textnorm` and whitespace collapse (line break vs space is not an error); `extract_values(text)` finds ИНН (10/12 digits), КПП (9), ОГРН (13/15), amounts with kopecks («1 234 567,89»), dates `12.03.2024` and «„12“ марта 2024», clause numbers at line start (`5.2.`, `5.2.1.`), and nothing in ordinary prose; `missing_lines` and `repeated_lines` on hand-made pages
  - `tests/integration/test_recognize_eval.py`: synthetic `clean` and `requisites_two_columns` recognised with `TruthEngine`, except one `ScriptedEngine` page with one wrong digit in an ИНН; `pages/D-0001-p001.txt` written from `truth.json` into a folder inside the test data dir; `control.csv` with a number, an amount and that ИНН → char accuracy, values and control strings exactly as expected (the ИНН counted as not found); the report file `reports/recognition-eval-*.json` has the recognition and reading `run_id`s per page, `engine`, `engine_version`, `dpi` and `settings.recognition`; the CSV has no text; without `--diff` stdout has no contract text; a folder outside `$DOCREADER_DATA_DIR` → exit 1 «Папка замера должна лежать в папке данных…»; a bad CSV row → exit 1 naming the file and line; a page without a recognition row → listed under «Не распознаны» and not counted

### Implementation for Шаг 2

- [X] T028 [US6] Make T026 pass in `src/docreader/recognition.py`: `force` and `pages` selection and validation (`UserError` messages from contracts/cli.md) — executor: sonnet
- [X] T029 [P] [US6] Add `--pages N[-M]` and `--force` to `recognize` in `src/docreader/cli.py` (range parsing; errors → `UserError`), with a unit test of the range parser in `tests/unit/test_cli_pages.py` — executor: haiku
- [X] T030 [US5] Make T027 pass: `src/docreader/recognition_eval.py` — the pure calculation functions plus `run_eval(conn, settings, folder, label, diff) -> EvalResult`, which reads the folder, `page_recognition`, `page_text` and `document_text` and writes the JSON and CSV report files atomically into `settings.reports_dir`; `recognize-eval <ПАПКА> [--label] [--diff] [--json]` in `src/docreader/cli.py`; output in `src/docreader/render.py` exactly as contracts/cli.md. `flags.csv` is T044 — executor: sonnet
- [X] T031 Write the queue-1 adapters (research R-1, R-3; contracts/engine.md; critical) in `src/docreader/ocr_engines.py` — executor: opus
  - `_load_tesseract`: `tesserocr.PyTessBaseAPI(lang="rus")`, line-level iterator, word confidences (0–100) averaged per line and divided by 100; version `"<tesseract> rus <traineddata date or hash>"`; data path from `model_dir` or the library default; missing `rus.traineddata` → `EnvironmentProblem` with the searched path
  - `_load_apple_vision`: `VNRecognizeTextRequest` with `recognitionLanguages = ["ru-RU"]`, accurate level, language correction **off** (FR-010); normalised boxes → pixels with the top-left origin; version from the OS; on non-macOS → `EnvironmentProblem` «движок apple_vision работает только на macOS»
  - register both in `ENGINES`; the guard test T009 now covers both names
  - the `ocr` dependency group in `pyproject.toml`: `tesserocr; sys_platform == 'darwin'`, `pyobjc-framework-Vision; sys_platform == 'darwin'`, **not** in `default-groups`; `uv lock` (never `uv sync --group ocr` here)
  - the conversion from native results to `EngineLine` lives in pure helpers, tested in `tests/unit/test_ocr_adapters.py` on hand-made records shaped like the native ones (no engine import)
- [X] T032 Checkpoint for Шаг 2 on this server: full suite, `ruff`, `mypy`, `docker compose build tests && docker compose run --rm tests`; the image must not contain the engines (`docker compose run --rm --entrypoint /opt/venv/bin/python tests -c "import tesserocr"` fails); commit; tell the analyst the branch is ready for quickstart Б0–Б1 — executor: opus
- [ ] T033 Quickstart Б0–Б1 on the Mac: install the `ocr` group and Tesseract with `rus`; build the bench database; verify 5–10 pages; run both candidates at 300 dpi and the better one also at 200 and 400 dpi; check the boxes on 3 pages and the column order; measure time and memory; check reproducibility. Send the agent **only** the table of numbers from quickstart Б1 п. 5 — executor: analyst
- [ ] T034 Record the choice after T033. If a queue-1 candidate passes SC-002, SC-004 and 25 s/page: set the `engine` and `dpi` defaults of `RecognitionSettings` in `src/docreader/config.py` (plus `tests/unit/test_config_recognition.py`, data-model.md and contracts/cli.md) and write items 1–2 of plan.md «Что записать в docs/tech-context.md» into `docs/tech-context.md`. If none passes: stop, add a task for the queue-2 adapter (research R-1) instead, then repeat T033 — executor: opus

**Checkpoint**: движок выбран и записан в tech-context. Сквозной прототип можно
продолжать с фичей 04.

---

## Phase 5: Шаг 3 — записи (уровень 2) и реальный движок (уровень 3)

**Goal**: все варианты синтетических сканов; команда записи с защитой путей; тесты
на записях выбранного движка; тест `real_model`.

**Independent Test**:

- на сервере: команда записи отказывается от пути вне `tests/synthetic/`; тесты
  уровня 2 до Б3 падают с подсказкой «записи нет или она устарела», после Б3
  проходят;
- на Mac: проходит `pytest -m real_model`.

- [X] T035 [P] Add the remaining variants to `tests/synthetic/make_scans.py`: `rotated_90` and `rotated_180` (image content turned, page `/Rotate 0`), `skew_3deg`, `table` (a three-column price list with ruling lines drawn into the image), `stamp_over_text` (a round blue «печать» over the requisites), `stamp_only`, `blank` (white page with a few noise pixels below `blank_max_ink_share`); bump `SCAN_GENERATOR_VERSION` to 2; extend `tests/unit/test_make_scans.py` (scan kind; truth present, empty for `stamp_only` and `blank`; deterministic) — executor: haiku
- [X] T036 Write `tests/synthetic/record_recognition.py` and `tests/integration/test_record_guard.py` (research R-13; critical: privacy guard in code) — executor: opus
  - `python -m tests.synthetic.record_recognition [ПУТЬ...]`; without paths it generates all variants into `tests/synthetic/out/`
  - every given path, after `resolve()` (symlinks resolved), must lie inside `<repo>/tests/synthetic/`; otherwise exit 1 «записываются только синтетические файлы из tests/synthetic/», before any engine is loaded
  - the engine comes from `ocr_engines.load_engine` with the current `[recognition]` settings (on this server it stops on the forbid guard)
  - writes `tests/recordings/13-scan-recognition/<engine>/<variant>.json` with `engine`, `engine_version`, `dpi`, `recorded_at`, `generator_version`, `variant`, and for each page the `EngineOutput` in pixels plus the image size
  - tests: a path in `tmp_path`, a path `tests/synthetic/../../x.pdf`, and a symlink inside `tests/synthetic/out/` that points outside are all refused without calling the engine; a path inside with a spy engine factory writes a file of the documented shape
- [ ] T037 Add `RecordedEngine(path, settings)` to `tests/fakes/ocr.py` and write `tests/integration/test_recognize_recorded.py` (level 2) — executor: opus
  - for each variant: recognise with the recording of the configured engine, then read; assert structure, not exact text
  - `clean`: char accuracy vs `truth.json` ≥ 0.95, and every truth box overlaps a recognised line box
  - `requisites_two_columns`: left column before right; `faded_noisy`: `quality` lower than on `clean`; `stamp_over_text`: `quality` lower than on `clean`, and the truth lines outside the stamp area are found with char accuracy ≥ 0.9; `blank`: `empty`; `rotated_180`: `turn = 180` (after T043)
  - a recording whose `(engine, engine_version, dpi, generator_version)` differs from the settings and `SCAN_GENERATOR_VERSION`, or a missing recording, **fails** with «запись устарела (или отсутствует) — перезапишите её на ноутбуке: uv run python -m tests.synthetic.record_recognition (quickstart Б3)»; never `skip` or `xfail`
- [X] T038 Write `tests/real_model/__init__.py` and `tests/real_model/test_ocr_engine.py`, marked `real_model` (research R-13, level 3); locally only check that it is collected and excluded by default (`uv run pytest --collect-only -m real_model` lists it, plain `pytest` does not run it) — executor: opus
  - the configured engine loads; on `clean` it returns lines inside the image, confidence in `[0, 1]`, and char accuracy ≥ 0.95 vs `truth.json`
  - during load and recognition `socket.socket.connect` and `socket.create_connection` are replaced by a trap that fails the test
  - with `model_dir` pointing to an empty folder → `EnvironmentProblem`
- [ ] T039 Quickstart Б2–Б3 on the Mac: `pytest -m real_model`, `python -m tests.synthetic.record_recognition`, commit and push `tests/recordings/13-scan-recognition/`. The output on synthetic data may be pasted to the agent — executor: analyst
- [ ] T040 After T039: pull, run `tests/integration/test_recognize_recorded.py` green on this server and in Docker; check with `git log -p` that the recordings were committed by the analyst's command only (no hand edits) — executor: opus

---

## Phase 6: Шаг 4 — страницы без текста, довороты, пересчёт флагов (US4, US5)

**Goal**:

- флаги `scan_no_text` и `empty` по доле тёмных точек;
- перебор доворотов (R-6);
- пересчёт флагов после смены порога через `read --all`;
- сверка флага с ручной отметкой в `recognize-eval`.

**Independent Test**:

- `stamp_only` → `scan_no_text`, `blank` → `empty`;
- `ScriptedEngine` с плохим результатом при 0° и хорошим при 180° →
  `turn = 180`, координаты верные;
- после смены порога `read --all` меняет флаги, движок при этом не вызывается.

### Tests for Шаг 4 ⚠️

- [ ] T041 [P] [US4] Write failing tests — executor: opus
  - `tests/unit/test_recognition_flags.py`: no lines and `ink_share >= blank_max_ink_share` → `scan_no_text` «строк нет, тёмных точек 4,1%»; no lines and below the threshold → `empty` «скан без текста, тёмных точек 0,2%»; `empty` stays neutral, `scan_no_text` gives `needs_review`; `orientation_unknown = true` with a low quality → the `low_recognition_quality` reason ends with «; ориентация не определена: 0°, 90°, 180°, 270° ниже порога»
  - `tests/integration/test_recognize_reading.py`: US4-1 — `stamp_only` and `blank` with an engine returning no lines → flags as above; the `blank` page does not send the document to review. US4-2 — change `page_min_quality` in `settings.toml`, `read --all` → `low_recognition_quality` appears or disappears, the engine factory spy is not called, `page_recognition` rows unchanged
  - `tests/integration/test_recognize.py` (R-6): the engine reports `orientation = 180` → the second call gets the turned image, `turn = 180`, boxes equal the truth within 1 pt; no `orientation`, `try_rotations = true`, `ScriptedEngine` low at 0° and high at 90° → at most 4 calls, `turn = 90`; all four low → `turn = 0`, `orientation_unknown = true`; `try_rotations = false` → one call, `turn = 0`, `orientation_unknown = false`; `seconds` covers all attempts
  - `tests/integration/test_recognize_eval.py` (US5, SC-007): `flags.csv` with marks for flagged and unflagged pages → accuracy, false positives and false negatives as expected; file absent → `flags: null`

### Implementation for Шаг 4

- [ ] T042 [US4] Make the `recognition_flags` part of T041 pass in `src/docreader/quality.py` (`scan_no_text` and `empty` by `ink_share`, the orientation part of the reason) and pass `orientation_unknown` from `page_recognition` in `src/docreader/reading.py` — executor: opus
- [ ] T043 [US4] Implement turning in `src/docreader/recognition.py` per research R-6 to make the R-6 part of T041 pass: `orientation` from the engine first, otherwise the trial with `orientation_score`; store `turn` and `orientation_unknown`; coordinates via `image_box_to_pdf(..., turn=...)` — executor: sonnet
- [ ] T044 [US5] Add `flags.csv` to `src/docreader/recognition_eval.py` and its output line to `src/docreader/render.py` to make the SC-007 part of T041 pass — executor: sonnet
- [ ] T045 [US4] Re-run `tests/integration/test_recognize_recorded.py` with the new variants. If the `rotated_180`, `blank` or `stamp_only` recordings are missing or stale (T035 came after T039), ask the analyst to re-record (quickstart Б4); do not edit recordings — executor: opus

---

## Phase 7: Шаг 5 — отчёт и список на просмотр (US7)

**Goal**: `recognize-report` с ключами `--review` и `--csv`; столбец «Распозн.»
в `list`; два новых столбца в `read-report`.

**Independent Test**: распознать несколько синтетических документов: в одном
ошибка, в другом флаг низкого качества, в третьем страница без текста. Сверить
цифры отчёта, порядок списка на просмотр и CSV.

### Tests for Шаг 5 ⚠️

- [ ] T046 [P] [US7] Write failing integration tests in `tests/integration/test_recognize_report.py` — executor: opus
  - US7-1: per document — scan pages, recognised, errors, pages per flag (from stored values and current thresholds, the same numbers `read` would give), mean quality, seconds, state; a totals row; documents without scans are absent
  - US7-2: `--csv` → UTF-8 with BOM, `;`, last row `Итого;…`; default path `reports/recognition-ГГГГММДД-ЧЧММСС.csv`; message «Отчёт сохранён: <путь>»; no contract text in the file (assert no truth line appears)
  - US7-3: `--review` → errors first, then the rest by quality ascending; each row has the id, page, flag name and reason; `--review --csv` uses the default name `recognition-review-…`; `--json` shapes per contracts/cli.md
  - `list` shows a «Распозн.» column before «Чтение»; `read-report` has «Низк. кач.» and «Без текста» columns with the right counts

### Implementation for Шаг 5

- [ ] T047 [US7] Implement the report and review queries in `src/docreader/textview.py` (one query per report over `page`, `page_recognition` and `stage_status`; flags through `quality.recognition_flags` on the stored values), returning dataclasses — executor: sonnet
- [ ] T048 [P] [US7] Add `recognize-report [--review] [--csv [ПУТЬ]] [--json]` to `src/docreader/cli.py`, the table, CSV and JSON rendering in `src/docreader/render.py`, the «Распозн.» column in `list` and the two `read-report` columns, with tests in `tests/unit/test_render_recognition.py` — executor: haiku
- [ ] T049 [US7] Make `tests/integration/test_recognize_report.py` pass end to end — executor: sonnet

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T050 Update the project docs with the decisions of this plan (items 5–7 of plan.md «Что записать…») — executor: opus
  - `docs/tech-context.md`: the data model sketch (`page_recognition`, stage `recognition` first, `page_text.source`, `confidence`, the new flags, `ocr_text` only for scans with embedded text); «Договорённости между этапами» (the reset rule; thresholds applied by reading); «Оборудование» and «Модели в автотестах» (the `ocr` group darwin-only, `DOCREADER_FORBID_MODELS`, the recording command, the staleness key)
  - `docs/features/03-pdf-text-reading.md` and `specs/002-pdf-text-reading/spec.md`: change the wording «скан помечается и не обрабатывается» to point to feature 13
  - `CLAUDE.md` «Commands»: `docreader recognize` and `DOCREADER_FORBID_MODELS`
- [ ] T051 [P] Review pass over the whole feature diff: `ruff`, `mypy`, the full suite locally and in Docker; check that every new `except Exception` sits at the one-page or one-document boundary and stores a reason; every `zip` has `strict=`; no new modules beyond those in plan.md; no test writes outside `tmp_path`; run quickstart А2 again — executor: opus
- [ ] T052 Quickstart Б5 on the Mac: recognise the whole set (time per page; total ≤ 12 h — SC-006); `read` ≤ 10 min and a second `recognize` says «Нечего распознавать» (SC-008); `recognize-report --csv`; the share of documents available to later stages (SC-009 ≥ 95%); SC-001. Send the agent only the numbers — executor: analyst
- [ ] T053 Quickstart Б6 on the Mac: verify ≥ 20 pages from ≥ 10 documents; fill `control.csv` and `flags.csv` (20 + 20 pages); run `recognize-eval`; tune the `[recognition]` thresholds by SC-007 with `read --all` (no re-recognition); SC-005 on 10 pages. Send the agent only the final shares and thresholds — executor: analyst
- [ ] T054 After T052–T053: set the tuned threshold defaults in `src/docreader/config.py` (plus the tests, data-model.md and contracts/cli.md); write items 3, 4 and 8 of plan.md «Что записать…» into `docs/tech-context.md` (remove **[проверить]** from the assumption «Сканы достаточно чёткие…» and record the result); set the spec status — executor: opus

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: T001 ∥ T002.
- **Foundational (Phase 2)**: after Setup; blocks every step.
  - T003 → T004; T005 ∥ T004.
  - T006 → T007 → T008; T006 → T009 → T010; T011 ∥ T006.
  - T008 + T011 → T012; T008 → T013.
- **Шаг 1 (Phase 3)**: after Phase 2.
  - Tests first: T014, T015, T016, T018 in parallel; T017 after them.
  - Then T019 (needs T014), T021 (T015), T022 (T016).
  - T023 after T017, T019, T021 and T022; T024 after T018 and T023; T020 after T019 and T022.
  - T025 last.
- **Шаг 2 (Phase 4)**: after Шаг 1.
  - T026 → T028; T029 ∥ T028; T027 → T030; T031 ∥ T026–T030.
  - T032 after all of them; T033 (analyst) after T032; T034 after T033.
- **Шаг 3 (Phase 5)**:
  - T035, T036 and T038 after Phase 2 (may start during Шаг 2).
  - T037 after T034: the staleness key needs the chosen engine.
  - T039 (analyst) after T035–T038 are pushed; T040 after T039.
- **Шаг 4 (Phase 6)**: after Шаг 1. T041 first; T042 ∥ T043; T044 after T030; T045 after T043 and T039.
- **Шаг 5 (Phase 7)**: after Шаг 4 (needs all flags). T046 → T047 → T049; T048 ∥ T047.
- **Polish (Phase 8)**: T050 and T051 after the steps being delivered; T052–T053 (analyst) after T051; T054 after T052–T053.

### Within each step

- Tests first, confirmed to fail for the right reason (a missing function or behaviour, not an import typo); then the implementation; then the checkpoint.
- Pure modules (`ocr.py`, `pagetext.py`, `quality.py`) come before `recognition.py` and `reading.py`; logic comes before CLI and rendering.
- An `analyst` task blocks only the tasks that name it; server work on later steps may go on meanwhile.

### Same-file sequencing (no [P] between these)

- `src/docreader/recognition.py`: T019 → T028 → T043
- `src/docreader/ocr.py`: T006 → T008
- `src/docreader/ocr_engines.py`: T010 → T031
- `src/docreader/pagetext.py`: T008 → T021
- `src/docreader/quality.py`: T022 → T042
- `src/docreader/reading.py`: T023 → T042
- `src/docreader/cli.py`: T020 → T029 → T030 → T048
- `src/docreader/render.py`: T020 → T024 → T030 → T044 → T048
- `src/docreader/textview.py`: T024 → T047
- `src/docreader/config.py`: T005 → T034 → T054
- `tests/fakes/ocr.py`: T006 → T012 → T037
- `tests/synthetic/make_scans.py`: T011 → T035
- `tests/integration/test_recognize.py`: T014 → T026 → T041
- `tests/integration/test_recognize_reading.py`: T017 → T041
- `tests/unit/test_recognition_flags.py`: T016 → T041
- `tests/integration/test_recognize_eval.py`: T027 → T041
- `tests/unit/test_render_recognition.py`: T020 → T048
- `pyproject.toml`: T001 → T031
- `tests/conftest.py`: T002 → T004

## Parallel Examples

```text
# Phase 1
T001 (Pillow, haiku)  ∥  T002 (forbid guard, opus)

# Phase 2
T003 → T004 (migration, opus)  ∥  T005 (config, haiku)  ∥  T011 (scan generator, haiku)
T006 (interface + fakes, opus) → T007 (tests, opus) ∥ T009 (guard tests, opus)

# Шаг 1 — tests (all opus)
T014 (recognize)  ∥  T015 (layout)  ∥  T016 (flags)  ∥  T018 (show/text); then T017

# Шаг 1 — implementation
T019 (recognition, opus)  ∥  T021 (pagetext, sonnet)  ∥  T022 (quality, opus); then T020 (CLI, haiku) ∥ T023 (reading, sonnet)

# Шаг 2
T026 (tests) ∥ T027 (tests) ∥ T031 (adapters, opus); then T028 (sonnet) ∥ T029 (haiku) ∥ T030 (sonnet)

# Шаг 3 (can overlap Шаг 2)
T035 (generator, haiku)  ∥  T036 (record guard, opus)  ∥  T038 (real_model test, opus)
```

## Implementation Strategy

### MVP first (Шаг 1 + Шаг 2)

1. Phase 1, затем Phase 2.
2. Phase 3 (Шаг 1). Контрольная точка: путь с подменами зелёный, quickstart А2
   проходит. После этого шаг можно влить.
3. Phase 4 (Шаг 2). Аналитик выбирает движок (T033), выбор записывается (T034).
   С этого момента набор можно распознать, и сквозной прототип идёт к фиче 04.

### Incremental delivery

1. Шаг 3 — записи и уровень 3; влить.
2. Шаг 4 — `scan_no_text` и `empty`, довороты, пересчёт флагов; влить.
3. Шаг 5 — отчёт и список на просмотр; влить.
4. Phase 8, затем Б5–Б6 у аналитика. Пороги и цифры записываются в tech-context,
   в таблицу результатов они попадут вместе с фичей 02.

## Notes

- Коммит делается после каждой задачи или логической группы задач. Главная сессия
  проверяет каждый делегированный результат, запускает тесты, `ruff` и `mypy`
  и отмечает задачу `[X]`.
- Если первая делегированная попытка не прошла проверку, задачу переделывает
  главная сессия на Opus. Если проверку не прошёл результат Haiku, задачи этого
  вида дальше отдаются Sonnet (CLAUDE.md).
- Ни один тест не зависит от реальных договоров, папки данных или настоящего
  движка. Исключение — `tests/real_model/`, а эта группа по умолчанию не запускается.
