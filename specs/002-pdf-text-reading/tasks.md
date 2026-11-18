---
description: "Task list for feature 03 (branch 002): PDF text reading and quality checks"
---

# Tasks: Чтение текста из PDF и проверка его качества

**Input**: Design documents from `specs/002-pdf-text-reading/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md), [quickstart.md](quickstart.md)

**Tests**: требуются — план (раздел Testing) и quickstart А. Тесты пишутся до кода
модуля и должны падать до реализации.

**Organization**: фазы идут по таблице «Порядок поставки» в plan.md (шаги 1–5); внутри
шага задачи помечены историями пользователя US1…US5 из spec.md. Шаг 1 — минимальная
версия для сквозного прототипа: её можно сдать и влить без шагов 2–5.

## Format: `[ID] [P?] [Story] Description — executor`

- **[P]**: можно выполнять параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история пользователя (US1…US5)
- **executor** (CLAUDE.md, «Model routing»):
  - `opus` — главная сессия сама, без делегирования (критичное: миграция и порядок записи
    в транзакции, сброс следующих этапов, правила флагов и причины состояния, удаление);
  - `haiku` — `implementer` с `model: "haiku"` (механическое: зависимости, раздел
    настроек, аргументы CLI, вывод, CSV, генераторы синтетических PDF);
  - `sonnet` — `implementer` на своей модели (остальное);
  - `analyst` — аналитик на Mac, без агента.
- Пути — от корня репозитория; раскладка — plan.md, «Source Code».

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-13), data-model.md, contracts/cli.md обязательны.
- Только синтетические PDF, создаваемые в фикстурах генераторами `tests/synthetic/make_pdfs.py`;
  никакого обращения к `$DOCREADER_DATA_DIR` реальной машины и к реальным договорам
  (CLAUDE.md, принцип I). Сами PDF в репозиторий не кладутся.
- Языковая модель и сеть не используются нигде (FR-010); поддельные модели и записи
  в `tests/recordings/` не нужны. Сетевой сторож из `tests/conftest.py` остаётся включён.
- `pagetext.py`, `cleanup.py`, `quality.py`, `textnorm.py` — чистые функции без базы;
  их модульные тесты в `tests/unit/` не требуют PostgreSQL. На вход им подаются простые
  записи (знаки, строки, сведения о странице), а не объекты pypdfium2; чтение PDFium —
  отдельная тонкая функция в `pagetext.py`.
- `textnorm.py` — только приведение знаков (R-5). Буквы-двойники к кириллице не
  приводятся, «ё» не меняется (вне рамок, фичи 02 и 07); значения (даты, суммы, ИНН)
  не разбираются.
- Копия файла открывается только на чтение и не меняется (FR-014).
- Одинаковый вход — одинаковый результат (FR-010, SC-005): никаких зависимостей
  от времени, порядка словарей или случайности в тексте и диапазонах.
- Сообщения пользователю — на русском, как в contracts/cli.md; код, идентификаторы
  и комментарии — на английском.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: зависимость `pymorphy3` (пометка **[проверить]** в tech-context) и
инфраструктура кириллических синтетических PDF

- [X] T001 Verify `pymorphy3` install (research R-6, tech-context «Русская морфология» **[проверить]**): `uv add pymorphy3 pymorphy3-dicts-ru` (updates `pyproject.toml` and `uv.lock`), `uv sync`; with a short throwaway script in the session scratchpad (not committed) measure `pymorphy3.MorphAnalyzer()` load time and print `word_is_known` for «монтажные», «строительномонтажные», «работы», «изыскательские», and how to obtain the dictionary version (e.g. `analyzer.dictionary.meta` or `pymorphy3_dicts_ru` package version); then `docker compose build tests` and repeat the check inside the container with no network. Record the result (Linux x86_64 and Docker: pass/fail, load time, the four answers, how the dictionary version is read) in `docs/tech-context.md` (row «Русская морфология»: Linux checked, macOS still **[проверить]** until T056) and in `specs/002-pdf-text-reading/research.md` R-6. If the answers are unexpected (compound word known, real word unknown), stop and report to the analyst before continuing — executor: haiku
- [X] T002 [P] Add the font for Cyrillic synthetic PDFs (R-12): copy `DejaVuSans.ttf` from the system package `fonts-dejavu-core` (`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`) to `tests/synthetic/fonts/DejaVuSans.ttf` and its license text (`/usr/share/doc/fonts-dejavu-core/copyright`, Bitstream Vera / DejaVu license) to `tests/synthetic/fonts/LICENSE`; make sure `.gitignore` does not exclude `*.ttf` — executor: haiku
- [X] T003 Add the Cyrillic base to `tests/synthetic/make_pdfs.py`: register DejaVu Sans from `tests/synthetic/fonts/` with `reportlab` (path relative to the module file, so it works on macOS, Linux and in Docker); helper `_ru_page(c, lines, *, x=..., y_top=..., size=..., leading=...)` that draws Russian lines at known positions; generator `make_contract_ru(path, pages=3)` — an ordinary one-column contract («Договор подряда № 123/45-У», numbered clauses 1.1, 1.2, a blank `«___» __________ 2024 г.` line) whose exact lines per page are exposed (return value or module constant) so tests compare the read text with them; add it to `make_demo_set`. Do not change existing generators — executor: haiku

**Checkpoint**: `uv run pytest` проходит как до фичи; `uv run python -m tests.synthetic.make_pdfs <scratchpad dir>` создаёт кириллический договор

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: настройки `[reading]` и схема хранения — одна для всех шагов (plan,
«Ключевые решения», п. 5)

**⚠️ CRITICAL**: работа над шагами 1–5 начинается только после этой фазы

- [X] T004 [P] Write failing unit tests in `tests/unit/test_config_reading.py`: `settings.toml` without `[reading]` → defaults exactly as data-model.md «Настройки» (`header_band = 0.1`, `header_min_share = 0.5`, `header_min_pages = 3`, `non_russian_min_letters = 3`, `unreadable_min_letter_share = 0.6`, `unreadable_max_bad_share = 0.05`, `unreadable_max_vowelless_share = 0.4`, `column_min_lines = 3`, `column_min_gap = 20.0`, `column_gap_tolerance = 15.0`, `rotated_min_angle = 5.0`); overrides applied; unknown key in `[reading]` → `EnvironmentProblem`; out-of-range values → `EnvironmentProblem` (shares and `header_band` outside `(0, 1]`, `header_min_pages < 1`, `non_russian_min_letters < 1`, `column_min_lines < 2`, negative distances or angle, angle `>= 90`); `settings_for_run()` contains the resolved values under key `reading` and stays JSON-serialisable — executor: haiku
- [X] T005 Implement `ReadingSettings` and the `[reading]` section in `src/docreader/config.py` (research R-13) to make `tests/unit/test_config_reading.py` and the existing `tests/unit/test_config.py` pass; follow the validation style of the feature 01 sections — executor: haiku
- [X] T006 Write `src/docreader/migrations/0002_reading.sql` exactly per data-model.md, and extend `tests/integration/test_migrate.py` (migration listed as applied, re-run is a no-op, constraints reject bad rows) — executor: opus
  - `page_text`: `document_id text`, `page_number integer`, PK (`document_id`, `page_number`), FK (`document_id`, `page_number`) → `page` `ON DELETE CASCADE`; `rotation smallint NOT NULL CHECK (rotation IN (0, 90, 180, 270))`; `width real NOT NULL CHECK (width > 0)`, `height real NOT NULL CHECK (height > 0)`; `lines jsonb NOT NULL CHECK (jsonb_typeof(lines) = 'array')`; `has_table boolean NOT NULL`; `run_id bigint NOT NULL` FK → `run` `ON DELETE RESTRICT`
  - `page_flag`: PK (`document_id`, `page_number`, `code`), FK (`document_id`, `page_number`) → `page_text` `ON DELETE CASCADE`; `code text NOT NULL CHECK (code IN ('scan_unread', 'ocr_text', 'unreadable', 'maybe_not_russian', 'empty', 'reading_order_unknown'))`; `reason text NOT NULL CHECK (btrim(reason) <> '')`
  - `document_text`: `document_id text` PK, FK → `document` `ON DELETE CASCADE`; `text text NOT NULL`; `text_sha256 char(64) NOT NULL CHECK (text_sha256 ~ '^[0-9a-f]{64}$')`; `read_pages integer NOT NULL CHECK (read_pages >= 0)`; `run_id bigint NOT NULL` FK → `run` `ON DELETE RESTRICT`
  - `text_span`: PK (`document_id`, `start`), FK `document_id` → `document_text` `ON DELETE CASCADE`; `start integer NOT NULL CHECK (start >= 0)`; `end_ integer NOT NULL CHECK (end_ > start)`; `page_number integer NOT NULL`; `line_index integer NOT NULL CHECK (line_index >= 0)`; index on (`document_id`, `end_`)
  - feature 01 tables are not changed
- [X] T007 Update `tests/conftest.py` so the per-test cleanup also empties `page_text`, `page_flag`, `document_text`, `text_span` (extend `REGISTRY_TABLES` or the truncate statement, children before parents or `TRUNCATE … CASCADE`); full suite stays green — executor: opus

**Checkpoint**: `DOCREADER_TEST_DATABASE_URL=postgresql:///postgres uv run pytest` зелёный; `docreader migrate` применяет `0002_reading`

---

## Phase 3: Шаг 1 — минимальная версия для сквозного прототипа (US1 + флаги `scan_unread`, `empty`) 🎯 MVP

**Goal**: `docreader read` читает документы реестра (выбор: без аргументов / ID / `--all`),
сохраняет строки по знакам с прямоугольниками в порядке сверху вниз, флаги `scan_unread`
и `empty`, очищенный текст «строки как есть» с `text_span`, состояние этапа `reading`;
`docreader text ID` и `text ID --page N` показывают результат. Сценарии US1-1…4,
US2-1, US2-7, US2-8 (частично).

**Independent Test**: добавить синтетический кириллический договор, изображение и пустую
страницу; `read` → текст страниц совпадает с ожидаемыми строками генератора, у каждой
строки прямоугольник внутри страницы; повторный `read ID` даёт тот же `text_sha256`
без дублей; сканы и пустые страницы помечены, состояния `done`/`needs_review` верны.

### Tests for Шаг 1 ⚠️

> Пишутся первыми и должны падать до реализации

- [X] T008 [P] [US1] Write failing unit tests in `tests/unit/test_pagetext_lines.py` on hand-made char records (code point, box `[left, bottom, right, top]`, angle, `generated`, `map_error`): chars → segments (break when the x gap exceeds `1.5 × char height` or on a generated line break, R-2) → lines (vertical overlap at least half the height); lines ordered top to bottom, segments left to right; line `bbox` is the union of its chars; line indices `i` from 0; generated spaces kept as spaces; empty input → no lines — executor: sonnet
- [X] T009 [P] [US2] Write failing unit tests in `tests/unit/test_quality_flags.py` for the step-1 rules (research R-7): `empty` when `char_count = 0` and `image_coverage = 0`; `scan_unread` when `kind = scan` and `image_coverage > 0` (text not stored); page of kind `scan` without images and with text → read normally, no flag; document state: no read line on any page → `needs_review` with reason «нет прочитанного текста»; any flag other than `empty` → `needs_review` with a reason listing pages per flag in the format «стр. 3, 5: скан, не прочитана; стр. 7: …» (flag order as in FR-006, pages ascending); only `empty` flags or none → `done` with no reason — executor: opus
- [X] T010 [P] [US1] Write failing unit tests in `tests/unit/test_cleanup.py` for the minimal document text builder: body lines of all pages joined with `\n` (pages also separated by `\n`, R-4); one `text_span` per line with `[start, end)`, page number and line index; spans ascending, non-overlapping, covering every non-empty line; empty lines produce no span; `text_sha256` is the SHA-256 of the UTF-8 text; `read_pages` counts pages with at least one line — executor: sonnet
- [X] T011 [US1] Write failing integration tests in `tests/integration/test_read.py` on synthetic PDFs added with `docreader add` — executor: sonnet
  - US1-1, FR-001, FR-002: `make_contract_ru` → `page_text.lines` text per page equals the generator's lines in order; every `bbox` lies inside `[0, 0, width, height]`; `rotation = 0`
  - US1-2: `text D-0001 --page 2` prints the page's lines and flags; `text D-0001` prints the whole text with `── стр. N ──` before each page; `--json` shapes per contracts/cli.md; unread document → exit 1 with «Документ D-0001 ещё не прочитан — выполните docreader read D-0001»; page out of range → exit 1
  - US1-3, FR-012, SC-005: second `read D-0001` → same `text_sha256`, same row counts in `page_text` and `text_span`, `structure`…`indexing` states unchanged
  - US1-4, FR-009: `read` without arguments reads `pending` and `failed`, leaves `done` and `needs_review` untouched; `read D-0002` reads it in any state; `--all` reads all; `--all` with IDs → exit 1; unknown ID → exit 1 and nothing read; nothing to read → «Нечего читать: все документы прочитаны (перечитать: docreader read --all)», exit 0
  - US2-1, US2-7, US2-8: mixed document (`make_mixed`) → image pages flagged `scan_unread`, text pages read, state `needs_review` with the page list; blank page (`make_blank_page`) → `empty`, state `done`; image-only document → `needs_review` «нет прочитанного текста», `read_pages = 0`, empty text
  - SC-002: every page of every document has a `page_text` row; missing copy (file deleted from `originals/`) → that document `failed` with a reason, the others read, exit 0
  - FR-013: one `run` with `stage = 'reading'`, `code_version`, `settings.reading`; `--label` stored
  - FR-014: SHA-256 of the copy is unchanged after reading

### Implementation for Шаг 1

- [X] T012 [US1] Implement `src/docreader/pagetext.py` (R-2): char record and line dataclasses; `read_page_chars(pdf_page)` via `pypdfium2.raw` (`FPDFText_GetUnicode`, `FPDFText_GetCharBox`, `FPDFText_GetCharAngle`, `FPDFText_IsGenerated`, `FPDFText_HasUnicodeMapError`), closing every PDFium handle; `build_lines(chars)` and top-to-bottom ordering to make `tests/unit/test_pagetext_lines.py` pass; line dict shape exactly as data-model.md `lines` element (`i`, `text`, `bbox`, `role` = `body`, `column` = null, `table` = null) — executor: sonnet
- [X] T013 [P] [US2] Implement the step-1 flag rules and the document state in `src/docreader/quality.py` (R-7) to make `tests/unit/test_quality_flags.py` pass; flag names and reason texts in Russian exactly as research R-7 — executor: opus
- [X] T014 [P] [US1] Implement the minimal builder in `src/docreader/cleanup.py` (`build_document_text(pages) -> (text, spans, sha256, read_pages)`) to make `tests/unit/test_cleanup.py` pass — executor: sonnet
- [X] T015 [US1] Implement `src/docreader/reading.py` (R-9, R-10, data-model «Порядок записи»): select documents (no IDs → `reading` in `pending`/`failed`; IDs → those, via the `registry` ID helpers; `--all` → all); start one `run` (`stage = 'reading'`, `settings_for_run()` incl. `reading`, label); per document: open the copy read-only; for each page use `page.kind`/`char_count`/`image_coverage` from feature 01 → for `scan_unread`/`empty` only the flag and a row with empty `lines`, else chars → lines → flags; build the document text; then one transaction: (1) `SELECT text_sha256 … FOR UPDATE`, (2) `DELETE` `page_text` (cascades `page_flag`) and `text_span`, (3) `INSERT` `page_text`, `page_flag`, upsert `document_text`, `INSERT` `text_span`, (5) update `stage_status` for `reading` (state, reason, `run_id`); step (4) is T029. Exception in a document → roll back its transaction, then a separate short transaction sets `failed` with the error text; continue with the rest. Ctrl-C → roll back the current document, return the partial result, exit 130. `finish_run` at the end. Returns `{run_id, documents: [...], totals}` per contracts/cli.md — executor: opus
- [X] T016 [P] [US1] Add `read [<ID>...] [--all] [--label МЕТКА] [--json]` and `text <ID> [--page N] [--json]` to `src/docreader/cli.py` (argument parsing and dispatch only, same style as feature 01 subcommands; `--find` comes in T037) — executor: haiku
- [X] T017 [US1] Implement text loading in `src/docreader/textview.py`: document text with per-page flags, one page's lines with flags and `has_table`; not-read document and page-out-of-range errors as `UserError` with the contract messages — executor: sonnet
- [X] T018 [P] [US1] Add rendering of `read`, `text` and `text --page` (text and `--json`) to `src/docreader/render.py` exactly as contracts/cli.md (state words «готово», «требует просмотра», «ошибка»; «Итого: …»), with unit tests in `tests/unit/test_render_reading.py` — executor: haiku
- [X] T019 [US1] Write and pass `tests/integration/test_read_reset.py` part «удаление и пересортировка»: `remove D-0001` leaves no rows in `page_text`, `page_flag`, `document_text`, `text_span`; `reclassify` that changes page kinds resets `reading` to `pending`, and the next `read` without arguments re-reads the document — executor: opus
- [X] T020 [US1] Make `tests/integration/test_read.py` (T011) pass end to end; fix code, never weaken assertions without the main session's review — executor: sonnet

**Checkpoint (шаг 1 можно влить)**: полный набор тестов зелёный; ручной прогон quickstart А
(`add`, `read`, `read` повторно, `text --page`) в одноразовой папке данных и базе
`docreader_demo` работает. Для фичи 04 шаги 2–5 не требуются.

---

## Phase 4: Шаг 2 — все флаги качества, приведение знаков, сброс следующих этапов (US2, US1-8, FR-017)

**Goal**: флаги `ocr_text`, `unreadable`, `maybe_not_russian` с причинами (`reading_order_unknown` —
шаг 4); знаки приведены по R-5; повторное чтение с изменённым текстом сбрасывает
следующие этапы.

**Independent Test**: прочитать синтетические страницы с известными дефектами и сверить
флаги и причины; изменить отпечаток текста и перечитать — `structure`…`indexing` в `pending`
с причиной «текст изменён».

### Tests for Шаг 2 ⚠️

- [X] T021 [P] [US2] Add generators to `tests/synthetic/make_pdfs.py` (R-12): `make_unreadable_ru` (text layer of private-use-area chars and `U+FFFD`, or consonant-only garbage, at least `text_min_chars` chars), `make_kazakh_ru(path, letters=3)` (page with 3+ letters from Ә, Ғ, Қ, Ң, Ө, Ұ, Ү, Һ, І) and its variant with one letter in a surname, `make_latin_ru` (`b55183f5-…` identifier, «CKAВ» with Latin C, K, A, Latin abbreviations), `make_typography_ru` (NBSP, `U+2011`, `U+2212`, `„“`, `‘’`, soft hyphen, double spaces, plus `—`, `«»`, «ё» that must stay); each exposes its expected lines — executor: haiku
- [X] T022 [P] [US2] Write failing unit tests in `tests/unit/test_textnorm.py` for every row of the research R-5 table (spaces `U+00A0`, `U+2000–U+200A`, `U+202F`, `U+205F`, `U+3000` → space; `U+2010`, `U+2011`, `U+2012`, `U+2212` → `-`; `„ “ ” ‟ ″` → `"`; `‘ ’ ‚ ‛` → `'`; `U+00AD` removed; runs of spaces → one) and for what must not change: `–`, `—`, `« »`, `ё`, Latin look-alikes in «CKAВ», `«___» __________ 2024 г.` — executor: sonnet
- [X] T023 [P] [US2] Extend `tests/unit/test_quality_flags.py` (research R-7): `ocr_text` for `kind = scan_with_text` (text kept); `unreadable` — page text shorter than `text_min_chars` never flagged; flagged when the letter+digit share among non-space chars `< 0.6`, or the bad-char share (map errors, `U+FFFD`, private use area) `> 0.05`, or the share of 3+-letter Cyrillic «words» without vowels `> 0.4`; ordinary Russian text, numbered clauses and `«___» __________ 2024 г.` not flagged; `maybe_not_russian` — count of Cyrillic letters in `U+0400–U+052F` except `А–я`, `Ё`, `ё` `>= non_russian_min_letters`: 3 letters → flag, 1 letter → none, Latin never counted; reason texts with numbers and letters, e.g. «4 буквы не русского алфавита: Қ, Ә, Ұ, І»; thresholds from `ReadingSettings` — executor: opus
- [X] T024 [P] [US1] Write failing integration tests in `tests/integration/test_read_reset.py` part «сброс следующих этапов» (US1-8, FR-012, R-9): set `structure`, `extraction` to `done` and `checks` to `needs_review` for a read document, overwrite `document_text.text_sha256` with a different value (simulates text read by older code), `read D-0001` → those stages `pending` with reason «текст изменён» and the reading `run_id`; stages already `pending` untouched; unchanged text → no stage changes; first read (no previous text) → no stage changes; `read` output lists the document under «Текст изменился, следующие этапы сброшены», JSON `text_changed = true`; results of later stages are not deleted — executor: opus
- [X] T025 [US2] Add integration tests to `tests/integration/test_read.py`: US2-2 (`make_image_with_invisible_text` → `ocr_text`, text stored), US2-3 (`make_unreadable_ru` → `unreadable`), US2-4/5 (3 letters → `maybe_not_russian`, 1 letter → none), US2-6 (`make_latin_ru` → no flag), US2-8 (state `needs_review` with the reason list), FR-017 (`make_typography_ru` → stored line text normalized per R-5; `—`, `«»`, «ё», «CKAВ» unchanged) — executor: sonnet

### Implementation for Шаг 2

- [X] T026 [US2] Implement `src/docreader/textnorm.py` (`normalize_chars(text) -> str`, R-5) to make `tests/unit/test_textnorm.py` pass; the module docstring notes that feature 02 comparison rules (ё → е, Latin → Cyrillic) will be a separate function here — executor: sonnet
- [X] T027 [US2] Implement the remaining flag rules (`ocr_text`, `unreadable`, `maybe_not_russian`) in `src/docreader/quality.py` to make the extended `tests/unit/test_quality_flags.py` pass; rules use the char records from `pagetext.py` (map-error flag) and `ReadingSettings` — executor: opus
- [X] T028 [US2] Apply `normalize_chars` to every line text in `src/docreader/pagetext.py` (`page_text.lines` store normalized text, data-model) and pass map-error counts to `quality.py`; wire the new flags into `src/docreader/reading.py` — executor: sonnet
- [X] T029 [US1] Implement step (4) of the write order in `src/docreader/reading.py`: when the previous `text_sha256` exists and differs, `UPDATE stage_status SET state = 'pending', reason = 'текст изменён', run_id = <reading run>` for `structure`, `extraction`, `checks`, `indexing` of that document where `state <> 'pending'`, inside the same transaction; return `text_changed`; render the «Текст изменился…» line in `src/docreader/render.py`; make `tests/integration/test_read_reset.py` and the new `tests/integration/test_read.py` cases pass — executor: opus

**Checkpoint**: полный набор тестов зелёный; шаг 2 можно влить

---

## Phase 5: Шаг 3 — очистка текста (US3)

**Goal**: колонтитулы и номера страниц вынесены из основного текста и находятся
`text --find`; переносы склеены по словарю; дубли имитации жирного шрифта убраны.

**Independent Test**: синтетический договор с колонтитулом, номерами страниц и переносами:
колонтитулов нет в очищенном тексте, `text --find "№ 123/45-У"` находит их на всех
страницах с ролью `header`; «мон-»/«тажные» → «монтажные», «строительно-»/«монтажные» →
«строительно-монтажные», «123/45-У» не тронут.

### Tests for Шаг 3 ⚠️

- [X] T030 [P] [US3] Add generators to `tests/synthetic/make_pdfs.py`: `make_headers_ru(path, pages=5)` (header with the contract number «№ 123/45-У» and a footer page number on every page, body text) and its 2-page variant, `make_hyphens_ru` (real hyphenation «мон-»/«тажные», compound «строительно-»/«монтажные», «123/45-У» inside a line, hyphen before a capital letter and before a digit), `make_page_break_sentence_ru` (a sentence continues on the next page across footer and header), `make_fake_bold_ru` (same text drawn twice with a 0.3 pt shift); each exposes its expected clean text — executor: haiku
- [X] T031 [P] [US3] Write failing unit tests in `tests/unit/test_cleanup.py` for headers and page numbers (R-4, data-model settings): a line in the top/bottom `header_band` repeating (same normalized text, same position within tolerance) on more than `header_min_share` of pages → role `header`/`footer`; page-number lines in the band («3», «- 3 -», «Стр. 3», «3 из 10») → `page_number`; fewer than `header_min_pages` pages → nothing removed; signature-sheet lines that appear only on the last page are never headers (FR-016); removed lines are absent from the document text and from `text_span` but kept in `lines` with their role; a sentence split by a page break joins without header text in between — executor: sonnet
- [X] T032 [P] [US3] Write failing unit tests in `tests/unit/test_hyphenation.py` (R-6) with a stub `is_known(word)`: candidate only when a `body` line ends with `-` or the PDFium hyphen marker (`U+FFFE` / generated `0x02`) after a Cyrillic letter and the next `body` line starts with a lowercase Cyrillic letter; known joined word → joined without hyphen; unknown → hyphen kept, line break removed; hyphen inside a line, before a capital letter or a digit → untouched; the two lines give two adjacent `text_span` ranges; plus one test with the real `pymorphy3` dictionary for «монтажные» and «строительно-монтажные» — executor: sonnet
- [X] T033 [P] [US3] Add failing unit tests to `tests/unit/test_pagetext_lines.py`: duplicate chars from fake bold (same code point, offset under 1 pt) removed; genuine double letters («сс» in «касса») kept — executor: sonnet
- [X] T034 [US3] Write failing integration tests in `tests/integration/test_read_cleanup.py`: US3-1…5 on the T030 generators; `text --find` returns `start`, `end`, `page`, `line`, `bbox`, `role` for matches in the clean text and in `header`/`footer`/`page_number` lines; the phrase is normalized with `normalize_chars` before search; «Не найдено» with exit 0; a 2-page document keeps headers in the text; `run.settings.reading` contains the dictionary version — executor: sonnet

### Implementation for Шаг 3

- [X] T035 [US3] Implement fake-bold de-duplication in `src/docreader/pagetext.py` to make T033 pass — executor: sonnet
- [X] T036 [US3] Implement header/footer/page-number detection and the hyphenation join in `src/docreader/cleanup.py` (R-4, R-6) to make `tests/unit/test_cleanup.py` and `tests/unit/test_hyphenation.py` pass; `pymorphy3.MorphAnalyzer` is created once per run in `src/docreader/reading.py` and passed in as `is_known`; the dictionary version goes to `run.settings` under `reading` — executor: sonnet
- [X] T037 [US3] Implement `text --find ФРАЗА` in `src/docreader/textview.py` (search in `document_text.text` → intersecting `text_span` → page, line, `bbox`; and in `page_text.lines` with roles `header`, `footer`, `page_number`), the `--find` argument in `src/docreader/cli.py`, and its text/JSON rendering in `src/docreader/render.py` per contracts/cli.md — executor: sonnet
- [X] T038 [US3] Make `tests/integration/test_read_cleanup.py` pass end to end — executor: sonnet

**Checkpoint**: полный набор тестов зелёный; шаг 3 можно влить

---

## Phase 6: Шаг 4 — раскладка: поворот, колонки, таблицы, лист подписи (US1-5…7, US4, FR-015, FR-016, FR-018)

**Goal**: страница с `/Rotate` читается обычным порядком; текст под углом внутри страницы
даёт `reading_order_unknown`; реквизиты в две колонки читаются колонками, с продолжением
на следующей странице; таблицы с линейками распознаются и читаются построчно; лист
электронной подписи остаётся в основном тексте.

**Independent Test**: синтетический договор с разделом реквизитов в две колонки
(без линеек и таблицей) с продолжением на следующей странице, таблицей приложения,
повёрнутыми страницами и листом подписи.

### Tests for Шаг 4 ⚠️

- [X] T039 [P] [US4] Add generators to `tests/synthetic/make_pdfs.py`: `make_requisites_columns_ru` (section «Адреса и платежные реквизиты Сторон» in two columns without rules — Заказчик left, Подрядчик right, with ИНН/КПП lines — continuing on the next page), `make_requisites_table_ru` (the same as a ruled 2-cell table), `make_price_table_ru` (ruled table at least 3 × 3, «Ведомость договорной цены»), `make_rotated_page_ru` (page with `/Rotate 90` and content drawn so it reads normally), `make_rotated_text_ru` (text drawn at 90° inside a normal page), `make_spaced_table_ru` (columns aligned by spaces, no rules, 3+ two-segment lines not matching the column rule), `make_signature_sheet_ru` (last page «Номер договора: …», «Дата подписания: …», «ФИО: …»); each exposes its expected reading order — executor: haiku
- [X] T040 [P] [US1] Write failing unit tests in `tests/unit/test_columns_tables.py` (R-3, R-8) on hand-made lines/segments and path segments: the rotation transform for 0/90/180/270 gives top-to-bottom order in display space while `bbox` stays in unrotated PDF space; chars with display angle `> rotated_min_angle` → lines with role `rotated` moved to the end of the page, page marked for `reading_order_unknown`; two-column area (at least `column_min_lines` consecutive lines with exactly two segments, gap `>= column_min_gap`, gap position within `column_gap_tolerance`) → whole left column then whole right, `column` 1/2; continuation: a page starting with a two-column area after a page ending with one keeps column numbers; a grid of horizontal/vertical path segments at least 2 × 2 → table; lines assigned to cells and ordered row by row, cell by cell, `table = {t, row, cell}`, `has_table = true`; 3+ multi-segment lines outside columns and tables → `reading_order_unknown` — executor: sonnet
- [X] T041 [P] [US1] Add failing tests to `tests/unit/test_quality_flags.py`: the `reading_order_unknown` flag and its reason come from the layout result (rotated text inside the page, or unresolved multi-segment lines), never from rotation set in page properties — executor: opus
- [X] T042 [US1] Write failing integration tests in `tests/integration/test_read_layout.py`: US1-5 (columns: Заказчик text contiguous before Подрядчик, no flag; the same for the 2-cell table), US1-6 (continuation stays in its column, no flag), US1-7, FR-016 (signature sheet in the clean text with line positions, not a header, no flag), US4-1, FR-007 (price table → `has_table`, cells of one row adjacent; `text --page` shows column/cell), FR-018 (`/Rotate 90` page → normal order, no flag; rotated text → `reading_order_unknown`, state `needs_review`), spaced table → `reading_order_unknown` — executor: sonnet

### Implementation for Шаг 4

- [X] T043 [US1] Implement page rotation and rotated-text handling in `src/docreader/pagetext.py` (R-3 p. 1–2) — executor: sonnet
- [X] T044 [US1] Implement two-column detection, column ordering and continuation across pages in `src/docreader/pagetext.py` (R-3 p. 4–5; continuation state passed page to page by `reading.py`) — executor: sonnet
- [X] T045 [US4] Implement ruled-table detection from `FPDF_PAGEOBJ_PATH` objects and cell ordering in `src/docreader/pagetext.py` (R-8); set `has_table` — executor: sonnet
- [X] T046 [US1] Implement the `reading_order_unknown` rule and reason in `src/docreader/quality.py` (R-3 p. 6) to make T041 pass — executor: opus
- [X] T047 [P] [US4] Show column, table cell and the table mark in `text --page` (text and JSON) in `src/docreader/render.py`, with cases in `tests/unit/test_render_reading.py` — executor: haiku
- [X] T048 [US1] Make `tests/integration/test_read_layout.py` pass end to end and re-run the whole suite (column and table changes must not alter step 1–3 results) — executor: sonnet

**Checkpoint**: полный набор тестов зелёный; шаг 4 можно влить

---

## Phase 7: Шаг 5 — отчёт о чтении (US5)

**Goal**: `docreader read-report` показывает по документам и итогом число страниц,
прочитанных страниц, страниц с каждым флагом и с таблицами; `--csv` выгружает файл
для табличного редактора.

**Independent Test**: прочитать несколько синтетических договоров с разными флагами
и сверить числа отчёта с `page_flag`; открыть CSV как UTF-8 с BOM и `;`.

### Tests for Шаг 5 ⚠️

- [X] T049 [US5] Write failing integration tests in `tests/integration/test_read_report.py` (FR-011, R-11, contracts/cli.md): columns and totals exactly as the contract table; only documents whose `reading` is not `pending`; «Прочит.» = pages with at least one line; a page with several flags counted in each column; «Таблицы» = pages with `has_table`; `--json` shape; `--csv` without a path writes `$DOCREADER_DATA_DIR/reports/reading-<дата-время>.csv` and prints the path; `--csv ПУТЬ` writes there; the file starts with the UTF-8 BOM, separator `;`, Russian headers; no contract text in the file (only IDs, original names and numbers) — executor: sonnet

### Implementation for Шаг 5

- [X] T050 [US5] Implement the report query in `src/docreader/textview.py` (one `GROUP BY` over `page_flag`, counts from `page_text` and `document_text`) — executor: sonnet
- [X] T051 [US5] Add `read-report [--csv [ПУТЬ]] [--json]` to `src/docreader/cli.py`, the table rendering in `src/docreader/render.py` and the CSV writer (stdlib `csv`, `utf-8-sig`, `;`) — executor: haiku
- [X] T052 [US5] Make `tests/integration/test_read_report.py` pass end to end — executor: sonnet

**Checkpoint**: шаги 1–5 готовы, полный набор тестов зелёный

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T053 Validate quickstart.md part A on the development server with a throwaway setup: `DOCREADER_DATA_DIR=<session scratchpad>/demo-data` and a separate database `docreader_demo` (`createdb docreader_demo`, `dropdb docreader_demo` afterwards); never use `~/docreader-data` or the `docreader` database. Run «Ручной прогон на синтетике»; correct `specs/002-pdf-text-reading/quickstart.md` and `contracts/cli.md` where the actual output differs — executor: sonnet
- [X] T054 Update `docs/tech-context.md`: remove the **[проверить]** marks resolved by this feature (pymorphy3 on Linux and Docker from T001; macOS after T056 is reported); keep «текст с координатами на реальных договорах» marked until T057; check that the reading data model and the «Договорённости между этапами» entries (reset on text change, availability rule) match the code — executor: sonnet
- [X] T055 Run the full suite: `DOCREADER_TEST_DATABASE_URL=postgresql:///postgres uv run pytest`, then `docker compose build tests` and `docker compose run --rm tests`; both green; report failures with output — executor: opus

---

## Phase 8b: После ревью архитектуры (2026-11-18)

**Purpose**: привести код к разделу «Правила кода» в `docs/tech-context.md` и подготовить
текст к проверке цитат (принцип III) до фич 04 и 05. Поведение команд не меняется, кроме
`text --find`, где добавляется поле `lines` и находится фраза через перенос строки.
`source_text_sha256` здесь не делается: таблиц со смещениями в тексте ещё нет, правило
применяет миграция фичи 04.

- [X] T063 Transactions: `db.connect` opens the connection with `autocommit=True`; remove the manual `conn.commit()`/`conn.rollback()` that close implicit transactions in `db.py`, `runs.py`, `reading.py`, `registry.py`, `textview.py`, `cli.py`, and `conn.autocommit = True` in `intake.py`; every multi-statement write stays inside `with conn.transaction()`; an integration test that `db.connect` gives an autocommit connection and that `read` interrupted mid-document leaves the previous result intact — executor: opus (critical: transaction ordering)
- [X] T064 Stages and states in one place: new `src/docreader/stages.py` with `Stage`, `State` (`StrEnum`, values equal to the CHECKs in `0001_intake.sql`), `RunStage` for `run.stage`, `later_stages(stage)`, and functions `create_pending`, `lock`, `set_state`, `reset_later`, `reset_all` (document selection stays in the stage, with stage and states passed as parameters); `db.STAGES`, `reading.READING_STAGE`/`LATER_STAGES`/`_STATES`, `intake.INTAKE_STAGE`, `quality.STATE_NEEDS_REVIEW` and literal `'pending'`/`'failed'`/`'reading'` in SQL go through it; a unit test that the enums match the migration CHECKs — executor: opus (critical: decision rules, after T063)
- [X] T065 [P] NFC (R-5): `normalize_chars` applies `unicodedata.normalize("NFC")` first; a combining mark (category `Mn`) never starts a new segment in `_build_segments` and never counts as a jump back; unit tests (`и` + U+0306 whose box starts left of the base letter → one segment «й»; precomposed text unchanged) and a synthetic generator with decomposed «й»/«ё» read end to end — executor: sonnet
- [X] T066 One quote-locating function (tech-context «Договорённости между этапами»): `textnorm.compare_form(text) -> (folded, offsets)` (NFC, any whitespace run incl. `\n` → one space, `ё→е`, `Ё→Е`, `–`/`—` → `-`, `«»` → `"`, Latin look-alikes → Cyrillic inside Cyrillic words) and `textnorm.locate(text, phrase) -> list[(start, end)]` in offsets of the original text; `textview.find_phrase` uses it for the clean text and the removed lines, loads `text_span` once, and every match gets `lines: [{page, line, bbox}]` for all lines it covers (existing fields stay = first line); update `contracts/cli.md`; unit tests (phrase across a line break, across a page break, ё/е, dash and quote variants, offsets map back exactly) and an integration test of `text --find` across a line break — executor: opus (critical: principle III)
- [X] T067 Run `uv run ruff check .`, `uv run mypy` and the full suite; all green — executor: opus

---

## Phase 9: Для аналитика на Mac (реальные договоры, без агента)

**Purpose**: quickstart Б. Команды выполняет аналитик в своём терминале; агент их не
запускает и не видит их вывода. Главной сессии сообщаются только «прошло/не прошло»
по каждому пункту и числа, без имён файлов и текста договоров. Цифры хранятся в папке
данных, пока фича 02 не создаст таблицу результатов.

- [X] T056 Analyst: on the Mac after pulling the branch — `uv sync`, `uv run docreader migrate`, `DOCREADER_TEST_DATABASE_URL=postgresql:///postgres uv run pytest`; check `pymorphy3` on macOS arm64 the same way as T001 (load time, four `word_is_known` answers); report pass/fail and the numbers — executor: analyst
- [X] T057 Analyst: quickstart Б1 (R-1 **[проверить]**): `docreader read D-0001 D-0002 D-0003`, `docreader text D-XXXX --page …` for the first page, the requisites page and the signature sheet; compare with the PDF side by side (line order, clause numbers, headings, Заказчик/Подрядчик not mixed, signature sheet read, header removed); report pass/fail; on failure the plan switches to pdfplumber (R-1) — executor: analyst
  - Done 2026-11-18 on D-0054, D-0055, D-0056 instead of D-0001…D-0003 (most of the set is scans; these three are the documents with a text layer): pass, read pages match the PDF; `pypdfium2` stays (R-1)
- [ ] T058 Analyst: quickstart Б2 — `docreader read`, `docreader read-report --csv`; review flagged pages, tune `[reading]` thresholds in `settings.toml` on false flags or misses, `docreader read --all`, repeat; report the final thresholds (numbers only) for tech-context — executor: analyst
- [ ] T059 Analyst: quickstart Б3, SC-004 — `time docreader read --all` on 50 contracts, limit 10 minutes; report the time — executor: analyst
- [ ] T060 Analyst: quickstart Б4, SC-006 — 10 pages from different contracts with `docreader text D-XXXX --page N`: no headers/page numbers among `body` lines, no body line lost; report the number of passing pages; also SC-002, SC-003 from the report and SC-005 from a second `read --all` (same `text_sha256`, no stage reset) — executor: analyst
- [ ] T061 Analyst: quickstart Б6 and FR-010 — `docreader text D-XXXX --find "-"` on several contracts (compound words keep the hyphen, real hyphenation joined; describe errors in words, without contract text); `docreader read --all` with Wi-Fi off works the same; report pass/fail — executor: analyst
- [ ] T062 Analyst: quickstart Б5, SC-001 — **зависит от фичи 02 (эталон с контрольными строками)**; until then only a spot check with `docreader text D-XXXX --find "…"` for the contract number, party INNs, sums and the signature-sheet date; after feature 02 measure SC-001 (≥ 99% control lines found verbatim) and record SC-001…SC-006 in the results table; only then is the feature formally closed (plan, Complexity Tracking) — executor: analyst

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 first (its result may change the hyphenation plan); T002 ∥ T001; T003 after T002.
- **Foundational (Phase 2)**: after Setup; blocks all steps. T004 → T005; T006 → T007.
- **Шаг 1 (Phase 3)**: after Phase 2. Deliverable on its own — MVP for the end-to-end prototype.
- **Шаг 2 (Phase 4)**: after Шаг 1 (extends `quality.py`, `pagetext.py`, `reading.py`).
- **Шаг 3 (Phase 5)**: after Шаг 1; its tests (T030–T034) may run in parallel with Шаг 2, but T035/T036 come after T028/T029 (same files).
- **Шаг 4 (Phase 6)**: after Шаг 3 (column continuation works after header removal; the signature sheet must not become a header).
- **Шаг 5 (Phase 7)**: after Шаг 2 (needs all flags); the «Таблицы» column is complete after Шаг 4.
- **Polish (Phase 8)**: after the steps being delivered.
- **Analyst (Phase 9)**: after Phase 8; T062 also after feature 02.

### Within each step

- Generators and tests first, failing; then implementation; then the end-to-end task.
- Pure modules (`textnorm`, `pagetext`, `cleanup`, `quality`) before `reading.py`; `reading.py` before CLI and rendering integration.

### Same-file sequencing (no [P] between these)

- `src/docreader/pagetext.py`: T012 → T028 → T035 → T043 → T044 → T045
- `src/docreader/quality.py`: T013 → T027 → T046
- `src/docreader/cleanup.py`: T014 → T036
- `src/docreader/reading.py`: T015 → T028 → T029 → T036
- `src/docreader/render.py`: T018 → T029 → T037 → T047 → T051
- `src/docreader/cli.py`: T016 → T037 → T051
- `tests/synthetic/make_pdfs.py`: T003 → T021 → T030 → T039
- `tests/unit/test_quality_flags.py`: T009 → T023 → T041

## Parallel Examples

```text
# Phase 1
T001 (pymorphy3 check, haiku)  ∥  T002 (font, haiku)

# Phase 2
T004 → T005 (config, haiku)  ∥  T006 → T007 (migration, opus)

# Шаг 1 — tests
T008 (pagetext tests, sonnet)  ∥  T009 (flag tests, opus)  ∥  T010 (cleanup tests, sonnet)

# Шаг 1 — implementation
T012 (pagetext, sonnet)  ∥  T013 (quality, opus)  ∥  T014 (cleanup, sonnet)  ∥  T016 (CLI, haiku)  ∥  T018 (render, haiku)

# Шаг 2 — tests
T021 (generators, haiku)  ∥  T022 (textnorm tests, sonnet)  ∥  T023 (flag tests, opus)  ∥  T024 (reset tests, opus)

# Шаг 3 — tests
T030 (generators)  ∥  T031 (cleanup tests)  ∥  T032 (hyphenation tests)  ∥  T033 (bold tests)

# Шаг 4 — tests
T039 (generators)  ∥  T040 (layout tests)  ∥  T041 (flag tests)
```

## Implementation Strategy

### MVP first (Шаг 1)

1. Phase 1 Setup → Phase 2 Foundational.
2. Phase 3 (Шаг 1) → checkpoint: full suite green, manual run of `add`/`read`/`text`.
3. **STOP and VALIDATE**; merge into `develop` — feature 04 can start on this text.

### Incremental delivery

1. Шаг 2 — flags and normalization; merge.
2. Шаг 3 — cleanup; merge.
3. Шаг 4 — layout; merge.
4. Шаг 5 — report; merge.
5. Phase 8, then the analyst's Phase 9 on the Mac; SC-001 after feature 02.

## Notes

- Commit after each task or logical group; the main session reviews every delegated
  result, runs the tests and marks the task `[X]`.
- A task whose first delegated attempt fails review is redone by the main session
  on Opus (CLAUDE.md).
- No test may depend on real contracts, the data folder or a model.
