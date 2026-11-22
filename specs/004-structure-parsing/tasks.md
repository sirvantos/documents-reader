---
description: "Task list for feature 04 (branch 004): structure parsing, minimal version"
---

# Tasks: Разбор структуры: разделы и пункты (минимальная версия)

**Input**: Design documents from `specs/004-structure-parsing/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md), [quickstart.md](quickstart.md)

**Tests**: требуются — plan.md, раздел «Тесты», и quickstart А. Тесты пишутся до кода
и должны падать до реализации по ожидаемой причине.

**Organization**: фазы по историям spec.md — US1 (разделить на пункты), US2 (преамбула
и хвост), US3 (оглавление и пункт). Все три — P1; US1 + US2 дают разбор, US3 — просмотр.

## Format: `[ID] [P?] [Story?] [model] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история spec.md (US1…US3)
- **[model]** (CLAUDE.md, «Model routing»; аналитик может поменять до начала implement):
  - `[opus]` — главная сессия сама, тесты и код (критичное фичи 04: миграция `clause`
    и её запись, правило начала пункта, идентификаторы, правила `needs_review`);
  - `[sonnet]` — `implementer` на своей модели; тесты к задаче пишет главная сессия
    заранее отдельной задачей `[opus]`, исполнитель их не меняет;
  - `[haiku]` — `implementer` с `model: "haiku"`, тесты и код сам (механическое:
    раздел настроек, аргументы CLI, вывод, генератор синтетики);
  - `[analyst]` — аналитик на Mac, без агента.
- Задача, не прошедшая ревью, получает новую метку прямо здесь (CLAUDE.md).

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-13), data-model.md, contracts/cli.md обязательны.
- Только синтетические PDF из генераторов `tests/synthetic/make_pdfs.py`, создаваемые
  в фикстурах; никакого обращения к реальной папке данных и реальным договорам
  (CLAUDE.md, принцип I). Сами PDF в репозиторий не кладутся.
- Моделей нет нигде (FR-009); `DOCREADER_FORBID_MODELS=1` остаётся в фикстурах:
  страница-картинка в синтетике на сервере остаётся непрочитанной — это и нужно.
- `structure.py` — чистые функции без базы и без `psycopg`; модульные тесты
  в `tests/unit/` не требуют PostgreSQL.
- Одинаковый вход и настройки — одинаковый результат: никакой зависимости от времени,
  порядка словарей или случайности.
- Сообщения пользователю — на русском, как в contracts/cli.md; код, идентификаторы,
  комментарии — на английском.
- Перед `[X]`: `scripts/check.sh` проходит (тесты, ruff, mypy).

---

## Phase 1: Setup

**Purpose**: синтетический договор для всех интеграционных тестов.

- [X] T001 [haiku] Add `make_structured_contract(path)` to `tests/synthetic/make_pdfs.py` (research R-12), drawn with the existing Cyrillic helpers (`_register_cyrillic_font`, `_ru_page`); do not change existing generators. Expose the lines per page as a module constant `STRUCTURED_CONTRACT_PAGES` like `CONTRACT_RU_PAGES` (page 3 is `None`). **Page 1** — preamble «Договор подряда № 7/2026», «г. Энск», «ООО «Альфа», именуемое Заказчиком, и ООО «Бета», именуемое Подрядчиком, заключили договор:»; «1. Предмет договора»; «1.1. Подрядчик выполняет работы.»; «1.2. Работы выполняются в два этапа.»; «1.2.1. Первый этап.»; «1.2.1.1. Подготовка участка.»; «1.2.2. Второй этап включает:»; «а) разметку участка;»; «1) завоз материалов.» (lists inside 1.2.2). **Page 2** — «Работы второго этапа сдаются по акту.» (clause 1.2.2 continues across the page boundary); «2. Цена договора»; «2.1. Цена складывается из частей:»; «2.1.1. Часть 1.» … «2.1.12. Часть 12.» (twelve lines; «2.1.10»–«2.1.12» look like dates); «01.03.2025 Заказчик вносит аванс.»; «2.5 млн рублей оплачиваются по акту.»; «согласно п. 1.2 настоящего договора»; «1.5 тонны материалов поставляет Подрядчик.»; «2.2Оплата производится по счёту.» (glued number); a ruled table of 3 rows × 2 cells whose first cells are «2.3», «2.4», «2.5» — numbers that would continue the numbering if the rows were not table lines (draw it like `make_price_table_ru`); «3. Форс-мажор»; «Стороны освобождаются от ответственности при форс-мажоре.» (section without subclauses). **Page 3** — a full-page image with no text (`_full_page_image`): stays a scan, not read on the dev server. **Page 4** — «4. Сроки»; «4.1. Начало работ — дата подписания.»; «4.2. Окончание — по графику.»; «5.1. Порядок приёмки определяется актом.» (heading «5.» missing); «5.2. Акт подписывается в 5 дней.»; «5.4. Споры решаются в суде.» (gap); «6. Ответственность сторон»; «6.1. Стороны несут ответственность по закону.»; «6. Ответственность сторон» (repeat); «6.2» alone on a line, then «Неустойка начисляется за просрочку.»; «7. Адреса и реквизиты сторон»; «Заказчик: ООО «Альфа», ИНН 0000000000»; «Подрядчик: ООО «Бета», ИНН 0000000001». **Page 5** — «Приложение № 1»; «1. Перечень работ»; «1.1. Земляные работы.». All names and numbers are fictional. Add it to `make_demo_set`

---

## Phase 2: Foundational (blocking)

**Purpose**: схема, настройки, идентификаторы, очистка тестовой базы.

- [X] T002 [opus] Write `src/docreader/migrations/0004_structure.sql` exactly per data-model.md «Новая таблица `clause`»: `document_id text NOT NULL REFERENCES document (id) ON DELETE CASCADE`; `key text NOT NULL CHECK (btrim(key) <> '')`; `PRIMARY KEY (document_id, key)`; `ordinal integer NOT NULL CHECK (ordinal >= 0)`, `UNIQUE (document_id, ordinal)`; `kind text NOT NULL CHECK (kind IN ('preamble', 'section', 'clause', 'tail'))`; `number_printed text NULL`, `number integer[] NULL` with `CHECK ((kind IN ('section', 'clause')) = (number IS NOT NULL AND number_printed IS NOT NULL))`; `depth smallint NOT NULL CHECK (depth = coalesce(array_length(number, 1), 0))`; `parent_key text NULL` with `FOREIGN KEY (document_id, parent_key) REFERENCES clause (document_id, key)`; `title text NULL`, `section_number integer NULL`, `section_title text NULL`; `start integer NOT NULL CHECK (start >= 0)`, `end_ integer NOT NULL CHECK (end_ > start)`; `first_page integer NOT NULL`, `last_page integer NOT NULL`, `CHECK (first_page <= last_page)`; `source_text_sha256 char(64) NOT NULL CHECK (source_text_sha256 ~ '^[0-9a-f]{64}$')`; `run_id bigint NOT NULL REFERENCES run (id) ON DELETE RESTRICT`; index `(document_id, start)`. Add `RunStage.STRUCTURE = "structure"` to `src/docreader/stages.py`. Extend `tests/integration/test_migrate.py` (applied; re-run is a no-op; constraints reject an empty key, an unknown kind, a section without number, a wrong depth, `end_ <= start`, a bad hash; deleting a document removes its rows; deleting a referenced run is refused) and `tests/unit/test_stages.py` (`RunStage.STRUCTURE`)
- [X] T003 [opus] Add `"clause"` to `REGISTRY_TABLES` in `tests/conftest.py` (with a feature 04 comment); full suite stays green
- [X] T004 [P] [haiku] `StructureSettings` and section `[structure]` in `src/docreader/config.py` (research R-10, data-model.md «Настройки»): `max_gap: int = 5` (valid 0–20); `requisites_pattern: str = r"реквизит|подписи\s+сторон|адреса\s+сторон|юридические\s+адреса"` (non-empty and compiles with `re.compile`; otherwise `EnvironmentProblem` naming the key); `Settings.structure`; resolved values under key `structure` in `settings_for_run()`. Tests first in `tests/unit/test_config_structure.py`: defaults, overrides, unknown key, out-of-range and non-integer `max_gap`, empty pattern, pattern that does not compile, JSON-serialisable run settings. Follow the style of the `[reading]` section
- [X] T005 [P] [opus] Clause identifiers in `src/docreader/ids.py` (research R-5): `clause_key(number: tuple[int, ...]) -> str` (`(5, 2)` → `5.2`); `format_clause_id(doc_id: str, key: str) -> str` (`D-0001/5.2`); `parse_clause_id(text) -> tuple[int, str]` returning the document seq and the key; accepted keys are `преамбула`, `реквизиты` and numbers `N(.N)*` of 1–3 digits without a leading zero; surrounding spaces stripped; anything else → `UserError` «Неверный идентификатор пункта «…» — ожидается вид D-0001/5.2». Tests in `tests/unit/test_clause_ids.py`

**Checkpoint**: миграция применяется, настройки читаются, идентификаторы разбираются.

---

## Phase 3: User Story 1 — Разделить договор на пункты (P1) 🎯 MVP

**Goal**: `docreader parse` сохраняет разделы, пункты и подпункты любой глубины с номером,
вышестоящей записью, заголовком раздела, страницами и диапазоном текста; пропуск, повтор
и непрочитанная страница дают `needs_review`.

**Independent Test**: разобрать синтетический договор T001 и сравнить записи `clause`
с ожидаемым списком (spec.md, US1, сценарии 1–6).

### Tests for User Story 1 ⚠️

- [ ] T006 [US1] [opus] Failing unit tests in `tests/unit/test_structure.py` for the pure rule (research R-2, R-3, R-5, R-7); input `Line(start, end, page, text, table)`. Candidates: `5.`, `5.2`, `5.2.`, `5.2.1.1.`, glued `5.2Оплата`. Not candidates: `5`, `5)`, list lines «а) …» and «1) …», `01.03.2025` (leading zero), `5.3 млн` / `5.3 руб` / `5.3 %` (unit right after the number), table lines, a line that is not a line start (glued to the previous span). Continuation: four levels with parents (`5` ← `5.1` ← `5.1.1` ← `5.1.1.1`); a section without subclauses; missing heading `6.3 → 7.1` (accepted, no record `7`, `section_number` None, parent None); descent with a missing middle `5. → 5.1.1` (parent `5`); gaps `5.1 → 5.3` and `6. → 8.` accepted with a finding; a step larger than `max_gap` is not a gap (it is a number out of order, see below); a repeated `6.` rejected with a finding and its line left in the previous record; `2.1.10` after `2.1.9` accepted while `01.03.2025` in the same clause is not; `1.5` inside `5.2` (a number backwards) rejected silently; a number out of order — `5.9` after `5.1` with `max_gap = 5`, `8.1` after `5.3` — rejected with the finding `номер вне порядка: 5.9 после 5.1 (стр. 4)`; a section heading after its clause — `7.` when `7.1` was accepted without a heading — rejected with the finding `заголовок раздела 7 после пункта 7.1 (стр. 12)`, its line left in the current record; a number alone on its line starts the record. Records: keys from numbers (`5.2.` → `5.2`), `number_printed` as found, `depth`, the `title` of a section (rest of the heading line, may be empty) copied into `section_title` of its clauses, own-text ranges contiguous and in order, `ordinal` ascending. Findings text exactly as R-7 (`пропуск: после 5.1 идёт 5.3 (стр. 4)`, `повтор: 6 (стр. 9)`; several of one kind joined with `, `, kinds with `; `). Unread pages are an input (`unread_pages`): a page between the first and the last page of the main text gives `не прочитана страница внутри основного текста: стр. 3`, a page before or after it gives nothing; the whole reason string comes from one function in the order of R-7. The same input twice gives an equal result

### Implementation for User Story 1

- [ ] T007 [US1] [opus] Implement `src/docreader/structure.py` to make the tests of T006 pass: dataclasses `Line`, `ClauseRecord` (key, kind, number, number_printed, depth, parent_key, title, section_number, section_title, start, end), `Finding`, `ParseResult`; `parse_lines(lines, text_length, settings: StructureSettings, unread_pages: Sequence[int] = ()) -> ParseResult` with the state reason built in one place; the candidate pattern and unit list of R-2; one current number and the two accepted forms of R-3; no `psycopg`, no I/O
- [ ] T008 [US1] [opus] Failing integration tests in `tests/integration/test_parse.py` through the CLI on `make_structured_contract` (added and read in a fixture). `parse` → records `1`, `1.1`, `1.2`, `1.2.1`, `1.2.1.1`, `1.2.2`, `2`, `2.1`, `2.1.1`…`2.1.12`, `2.2`, `3`, `4`, `4.1`, `4.2`, `5.1`, `5.2`, `5.4`, `6`, `6.1`, `6.2` of `D-0001` with parents and pages (`1.2.2` has pages 1–2 and holds the list lines; `2.2` starts on page 2 and holds the table, there are no records `2.3`, `2.4`, `2.5`; `3` ends before page 4; page 3 unread). State `needs_review`, reason containing the gap `после 5.2 идёт 5.4`, the repeat `6` and `не прочитана страница внутри основного текста: стр. 3`. A `run` row with `stage = 'structure'` and `settings.structure`. `parse` again without arguments → the nothing-to-do message of contracts/cli.md, exit 0. `parse D-0001` and `parse --all` replace the rows (same keys, new `run_id`; SC-004). `--all` with ids → user error. A not read document given by id → «пропущен» with a reason, its `stage_status` unchanged. An exception while parsing one document (monkeypatch `structure.parse_lines` to raise for it) → `failed` with a reason, the next document still parsed. `--json` shape exactly as contracts/cli.md
- [ ] T009 [US1] [opus] Implement `src/docreader/parsing.py` (research R-1, R-6, R-7, R-9; data-model.md «Состояние этапа»): select available documents (`reading` in `done`/`needs_review` and `read_pages > 0`; by default `structure` in `pending`/`failed`; `--all`; explicit ids with «пропущен» reasons); load `document_text`, `text_span` with the line-start rule of R-1, the `table` mark from `page_text.lines[line_index]`, `page_text.source` and the unread flags; call `structure.parse_lines` with the unread page numbers (the reason comes from `ParseResult`, not from this module); the first and last page of every record from spans; one transaction per document — `stages.lock`, `DELETE FROM clause`, `executemany` insert in `ordinal` order, `stages.set_state`; `run` via `runs.start_run(conn, RunStage.STRUCTURE, {"structure": …})` and `finish_run`; `except Exception` only at the one-document boundary with the reason kept; results as dataclasses for render. Make T008 pass except the CLI wiring of T010
- [ ] T010 [US1] [haiku] Subcommand `parse [ID…] [--all] [--label МЕТКА] [--json]` in `src/docreader/cli.py` and its text and JSON output in `src/docreader/render.py` exactly as contracts/cli.md «docreader parse» (a line per document, «Итого: …», the nothing-to-do line, interrupted → 130 like `read`); unit tests of the text output in `tests/unit/test_render_structure.py`. T008 must pass

**Checkpoint**: US1 работает отдельно — разбор договора T001 даёт верные пункты и причину.

---

## Phase 4: User Story 2 — Преамбула и хвост (P1)

**Goal**: текст до первого раздела — `D-0001/преамбула`; всё с нумерованного раздела
реквизитов — `D-0001/реквизиты`; 100% текста в записях; без реквизитов и без нумерации —
`needs_review`.

**Independent Test**: разобрать T001, `make_contract_ru` и договор без нумерации; проверить
преамбулу, хвост, покрытие текста и причины.

### Tests for User Story 2 ⚠️

- [ ] T011 [US2] [opus] Failing unit tests in `tests/unit/test_structure.py` (research R-4, R-7): a preamble record `преамбула` (kind `preamble`, depth 0) for the text before the first accepted candidate; no preamble record when the text starts with a number; the tail `реквизиты` (kind `tail`) from a depth-1 candidate whose number is greater than the current section and whose rest matches `requisites_pattern` (case-insensitive: «АДРЕСА И РЕКВИЗИТЫ СТОРОН», «Подписи сторон») to the end of the text; numbered lines after it (appendix `1.`, `1.1`) are not records; a requisites line inside clause text («1.5. … реквизитов …», depth 2) does not start the tail; a heading with a skipped number (`7.` expected, `9. Реквизиты` found) starts the tail and gives a gap finding; no tail → finding `раздел реквизитов не найден`, the last record runs to the end; no accepted candidate → one `преамбула` record over the whole text and finding `нумерация не найдена`; the first depth-1 candidate after the tail start that continues the numbering from the requisites heading (`9. Порядок изменения реквизитов` … `10. Ответственность`) gives the finding `после начала хвоста идёт раздел 10 (стр. 20)` and leaves the tail as it is, while an appendix starting with `1.` gives none; an unread page inside the tail gives no finding; reason kinds in the order of R-7; coverage — records contiguous from 0 to `text_length` in every case

### Implementation for User Story 2

- [ ] T012 [US2] [opus] Extend `src/docreader/structure.py` to make T011 pass (preamble, tail boundary, the two findings, coverage); the US1 tests stay green
- [ ] T013 [US2] [opus] Integration tests in `tests/integration/test_parse.py`: T001 → `D-0001/преамбула` on page 1 and `D-0001/реквизиты` from «7. Адреса и реквизиты сторон» to the end with the appendix «1.1» inside; the sum of `end_ - start` over the document's rows equals `length(document_text.text)` and the ranges are contiguous (SC-003); `make_contract_ru` → `needs_review` with `раздел реквизитов не найден`; `make_digital` (no numbering) → one preamble record and `нумерация не найдена`; fix `parsing.py` if needed

**Checkpoint**: US1 + US2 — разбор целиком; можно передавать на Mac (Б1).

---

## Phase 5: User Story 3 — Посмотреть оглавление и пункт (P1)

**Goal**: `outline` и `clause` по contracts/cli.md, с проверкой устаревания.

**Independent Test**: вывести оглавление и пункты T001 и сравнить с ожидаемым.

### Tests for User Story 3 ⚠️

- [ ] T014 [US3] [opus] Failing integration tests in `tests/integration/test_outline_clause.py` on T001 after `parse`. `outline D-0001`: a first line with the state and reason; every record with its id, the printed number indented by depth, pages and the head of its own text (≤ 60 chars); the line «страница 3 не прочитана» between `3` and `4`; the `[распознано]` mark on records whose pages have `page_text.source = 'recognized'` (set `source` directly in the fixture for one page); `--json` shape as contracts/cli.md with `unread_pages: [3]`. `clause D-0001/1.2`: `1.2`, `1.2.1`, `1.2.1.1`, `1.2.2` in order, each from a new line with its number; `--own` — only the text of `1.2` up to `1.2.1`. `clause D-0001/6`: the heading and `6.1`, `6.2` (the repeated heading line inside `6.1`). `clause D-0001/преамбула` and `D-0001/реквизиты`. Errors with exit 1 and the messages of contracts/cli.md: bad id form, unknown record, document not parsed, unknown document. Stale: after the text changes (`UPDATE document_text SET text_sha256 = …` in the fixture) both commands report «Разбор устарел…». The same file also tests the loaders directly through the `db` fixture (`clauseview.load_outline`, `clauseview.load_clause` with and without `own`, the stale and not-found errors), so T015 can be checked before T016

### Implementation for User Story 3

- [ ] T015 [US3] [sonnet] Implement `src/docreader/clauseview.py` to make the loader tests of T014 pass: `load_outline(conn, seq) -> Outline` and `load_clause(conn, seq, key, own: bool) -> ClauseView` (dataclasses); the stale check against `document_text.text_sha256`; descendants by key prefix in `ordinal` order; text by slicing `document_text.text`; recognised marks from `page_text.source`; unread pages from `page_flag` codes `scan_unread`, `scan_no_text`, `unreadable`; errors as `UserError` with the contract messages. Do not edit the tests of T014
- [ ] T016 [US3] [haiku] Subcommands `outline ID [--json]` and `clause ИДЕНТИФИКАТОР [--own] [--json]` in `src/docreader/cli.py` and their output in `src/docreader/render.py` exactly as contracts/cli.md; extend `tests/unit/test_render_structure.py`. T014 must pass

**Checkpoint**: все три истории работают; quickstart А2 проходит.

---

## Phase 6: Polish & Cross-Cutting

- [ ] T017 [opus] Run quickstart А2 on the dev server (throwaway data dir, `docreader_demo`), compare with the expected results there, fix differences test-first; then `docker compose run --rm tests` and `docker compose run --rm lint`
- [ ] T018 [P] [haiku] Document the new commands in `CLAUDE.md` «Commands» (`docreader parse`, `outline`, `clause`; output of `parse` may be sent to the agent, output of `outline` and `clause` may not) and in `.env.example` if a variable is added (none expected)
- [ ] T019 [opus] Record the Fable trial for feature 04 in `CLAUDE.md` «Model routing» (clarify: questions settled from documents or survey numbers, questions asked, answers redone; analyze: findings fixed automatically vs brought to the analyst) and keep or revert the trial with the analyst
- [ ] T020 [analyst] Quickstart Б1–Б3 on the Mac: `parse --all` time and summary, manual boundary check on 5 contracts incl. D-0056, identical ids after a rerun; send the numbers only
- [ ] T021 [opus] Write the Б results into `docs/tech-context.md` (structure: time for the set, share of correct records, tail found in N of M) and the feature report; a systematic error from Б2 → a synthetic case and a failing test first (CLAUDE.md «Delivery»)

---

## Dependencies & Execution Order

### Phase dependencies

- Phase 1 (T001) — no dependencies; needed by T008, T013, T014.
- Phase 2 (T002–T005) — T003 after T002; blocks all stories.
- US1 (T006–T010) — after Phase 2, in order T006 → T007 → T008 → T009 → T010.
- US2 (T011–T013) — T011 after T007 (same files); T013 after T009.
- US3 (T014–T016) — after T009 (needs parsed data); T015 → T016.
- Polish — after the stories; T020 after T017; T021 after T020.

### Same-file sequencing (no [P] between these)

- `tests/unit/test_structure.py`: T006 → T011.
- `src/docreader/structure.py`: T007 → T012.
- `tests/integration/test_parse.py`: T008 → T013.
- `src/docreader/cli.py`, `src/docreader/render.py`, `tests/unit/test_render_structure.py`: T010 → T016.

## Parallel Examples

```text
Phase 1 ‖ Phase 2: T001 (generator, haiku) while the main session does T002–T005.
Phase 2: T004 (config, haiku) ‖ T005 (ids, opus) after T002/T003.
US3: T015 (clauseview, sonnet) while the main session writes T013.
Polish: T018 (docs, haiku) ‖ T017.
```

## Implementation Strategy

### MVP first

US1 + US2 (T001–T013) — разбор целиком: этого достаточно для Б1 на Mac и для того, чтобы
фичи 05 и 07 опирались на записи `clause`. US3 — просмотр для ручной проверки Б2.

### Incremental delivery

1. Phase 1–2 → схема, настройки, идентификаторы.
2. US1 → пункты и находки; проверка на T001.
3. US2 → преамбула, хвост, покрытие; Б1 на Mac можно запускать.
4. US3 → `outline`/`clause`; Б2 и Б3.
5. Polish → документы, итог испытания Fable, результаты Б.
