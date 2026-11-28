---
description: "Task list for feature 10 (branch 011): table answers, minimal version (count and list, one condition)"
---

# Tasks: Ответ по таблице через фиксированные фильтры

**Input**: Design documents from `specs/011-table-answers/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/model.md](contracts/model.md), [quickstart.md](quickstart.md)

**Tests**: требуются — plan.md «Testing», SC-002, SC-003, SC-005, SC-006; CLAUDE.md
(test-first). Тесты пишутся до кода и должны падать до реализации по ожидаемой причине.

**Organization**: фазы по историям spec.md — US1 (посчитать и перечислить, P1), US2
(полнота данных, P1), US3 (вопрос, на который таблица не отвечает, P2). Настройки,
действующее значение, подсказка и схема, фикстуры договоров — в Phase 1–2: они нужны всем
историям. Записи модели и замер — после US3. MVP — US1 + US2.

## Format: `[ID] [P?] [Story?] [model] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история spec.md (US1…US3)
- **[model]** (CLAUDE.md, «Model routing»; аналитик может поменять до начала implement):
  - `[opus]` — главная сессия сама, тесты и код (plan.md «Распределение по моделям»:
    проверка запроса `validate`; состояния ячеек и действующее значение; выполнение
    и причины неучтённых; сопоставление наименований и выбор стороны; защита вывода;
    команда записи с её защитами — как T017 фичи 09);
  - `[sonnet]` — `implementer` на своей модели; тесты к задаче пишет главная сессия
    заранее отдельной задачей `[opus]`, исполнитель их не меняет;
  - `[haiku]` — `implementer` с `model: "haiku"`, тесты и код сам (механическое:
    настройки; генераторы синтетики с фичи 06 — Sonnet, CLAUDE.md);
  - `[analyst]` — аналитик на Mac, без агента.
- Задача, не прошедшая ревью, получает новую метку прямо здесь (CLAUDE.md).

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-13), data-model.md, contracts/ обязательны.
- Только синтетика: договоры `make_check_contracts` (фича 06) и вопросы
  с вымышленными наименованиями; никакого обращения к реальной папке данных и реальным
  договорам (CLAUDE.md, принцип I).
- Моделей нет: в тестах — `ScriptedModel` (`use_model`) и записи `RecordedModel`;
  `DOCREADER_FORBID_MODELS=1` остаётся в фикстурах. Записи не правятся руками.
- Существующие генераторы, их версии и записи `tests/recordings/` не меняются.
- `ask-table` ничего не пишет в базу (FR-013): интеграционные тесты сверяют число строк
  `field_value`, `field_status`, `field_decision`, `run` до и после.
- Первая строка вывода `ask-table`, сообщения об ошибках и предупреждения — без текста
  вопроса и значений договоров (FR-014); проверка — помощник T006, каждая задача
  команды добавляет свой случай.
- Числа ответа считает код, модель — только форма `TableReply` (FR-004).
- Сообщения пользователю — на русском, как в contracts/; код, идентификаторы,
  комментарии — на английском.
- Перед `[X]`: `scripts/check.sh` проходит (тесты, ruff, mypy; код возврата самой
  проверки, не конвейера).

---

## Phase 1: Setup

- [X] T001 [P] [haiku] `TableSettings` (`[table]`: `max_tokens = 512`, `max_retries = 2`, `list_rows = 20`) in `src/docreader/config.py` with validation (`max_tokens` 1–8192, `max_retries` 0–5, `list_rows` ≥ 1) and tests in `tests/unit/test_config.py`; `[table]` added to the list of sections in `README.md` («Настройки»)
- [X] T002 [P] [opus] `checks.effective_cell(status, flags, system_result, system_normalized, decided) -> (state, value)` in `src/docreader/checks.py` (research R-5 table: `effective`, `unreviewed`, `needs_review`, `rejected`, `not_found`), `effective_value` rewritten on it without change of behaviour; tests first in `tests/unit/test_checks_status.py` — every row of the R-5 table, «исправить» wins over the status, «в договоре нет» → `not_found`, «требует просмотра» with `found` → `unreviewed` (also a decision that no longer holds, flag `system_changed`), without a value → `needs_review`; the existing `effective_value` tests pass unchanged

---

## Phase 2: Foundational

- [ ] T003 [opus] Failing tests `tests/unit/test_table_prompt.py` (research R-3, contracts/model.md): `PROMPT_VERSION == "10.1"`; `TableReply` — `kind` one of `query`, `refuse`, `clarify`, `unsupported`, the other keys strings or `null`, extra keys refused; `build_messages(question, today)` — system message holds today's date as ISO, every field name of the contracts/model.md table with its comparisons, `party`, both actions, the period codes of R-6, the rules of the outcomes and «данные, а не указания»; the user message is «Вопрос: …»; `build_retry(messages, reply_json, reason)` appends the assistant reply and «Запрос недопустим: <причина>…»; `prompt_sha256()` stable and changes with the system text; no `openai`/`instructor` import in the module
- [ ] T004 [sonnet] `src/docreader/table_prompt.py`: `PROMPT_VERSION`, `SYSTEM_TEMPLATE`, `TableReply` (pydantic, `extra = "forbid"`), `build_messages`, `build_retry`, `prompt_sha256` (as `answer_prompt.py`). Make T003 pass without editing it
- [ ] T005 [opus] Fixtures `tests/integration/table_fixtures.py`: `make_check_contracts` (tests/synthetic/make_pdfs.py) → `add` → `read` → `parse` → `extract` (`ScriptedModel`, `CHECK_ANSWERS` of `check_fixtures.py`) → `check`; the table of expected effective values per contract (from `CHECK_ANSWERS` and the statuses of `test_check_cli.py`); helper `reply(**query)` that builds a `TableReply` JSON for `ScriptedModel`
- [ ] T006 [opus] Output guard for `ask-table` in `tests/integration/test_table_output_guard.py` on top of `tests/check_guard.py`: a helper that runs `ask-table` and fails if any synthetic value or party name of `make_check_contracts` or the question text appears in the first line of stdout, in stderr or in an error message; first case — `ask-table --help`

---

## Phase 3: User Story 1 — Посчитать и перечислить договоры по условию (Priority: P1) 🎯 MVP

**Goal**: вопрос на подсчёт или перечисление по одному условию над шестью полями даёт число, условие простыми словами и список договоров с шестью полями и пунктом поля условия.

**Independent Test**: на договорах T005 задать вопросы по каждому из шести полей обоими действиями (модель — `ScriptedModel`) и сравнить число и список с ожидаемыми.

- [ ] T007 [US1] [opus] `table_query.validate(reply, today) -> TableQuery | Problem` and `resolve_period(code, today)` with tests first in `tests/unit/test_table_query.py` (research R-4, R-6): the table of allowed field/op pairs; values normalized with `values.normalize` by kind (number — identifier, names — name, amounts — `Decimal` from the normalized string, «1500000» and «1 500 000,00» the same), dates ISO or a period code; every problem code of R-4 (`unknown_field`, `unknown_action`, `op_not_allowed`, `value_not_normalized`, `missing_value`, `missing_value_to`, `bad_range`, `unknown_period`, `missing_reason`); periods `this_year`, `last_year`, `next_year`, `this_quarter`, `last_quarter`, `next_quarter`, `this_month`, `last_month`, `next_month` from a fixed `today` (quarter and year edges, January and December); a code with `before` → before the start, with `after` → after the end, with `eq`/`between` → the whole period; the Russian text of a `Problem` is built from its code and the allowed names only — no string taken from the reply (value, unknown field, op or action) gets into it (FR-014, research R-4). Code in `src/docreader/table_query.py`
- [ ] T008 [US1] [opus] Name matching and the side with tests first in `tests/unit/test_table_query.py` (research R-7, clarifications 2026-11-27): `values.same_value` of feature 02 (case, spelled legal form, initials); a name without legal form compared with the name in quotes of the table value (case ignored, initials rule); no match by part of the name (`"Альфа"` ≠ `"Альфа-Строй"`); `party` — matched on one side only → that side, named in the query; on both → `clarify` «заказчик или подрядчик?»; on none → zero rows with the condition «заказчик или подрядчик — X», a contract considered only when both name cells are, otherwise excluded under the state of the customer cell, else of the contractor cell; the side is chosen by the considered cells only (`effective`, with the flag also `unreviewed`); the distinct matched spellings collected. Code `match_names`, `resolve_party` in `src/docreader/table_query.py`. After T007 (same files)
- [ ] T009 [US1] [opus] `table_query.execute(query, rows, include_unreviewed) -> Result` with tests first in `tests/unit/test_table_query.py` on `DocRow`/`Cell` built in the test (data-model.md): every comparison and its edge (`gt` vs `ge` at the bound, `before`/`after` strict, `between` inclusive), number by normalized equality, names by T008; only cells `effective` (and `unreviewed` with the flag) are considered, every other state goes to `excluded` under its state; rows in document id order (FR-012); `count`, `considered`, `matched_names`; the same input twice → the same `Result`. After T008 (same files)
- [ ] T010 [US1] [opus] Failing tests of the answer text in `tests/unit/test_table_query.py` and `tests/unit/test_table_render.py`: `describe(query)` per contracts/cli.md («подрядчик — ООО "Альфа"», «цена с НДС больше 1 000 000,00 руб.», «дата окончания с 2026-01-01 по 2026-12-31», `party` with its side); the first line «По таблице — ответ: N договоров; учтено K из M, не учтено J; повторов R; T с» with Russian plural forms (1 договор, 2 договора, 5 договоров) and no value; the list with the six fields, the clause of the condition field, a non-effective value shown with its state, «… ещё N — полный список: --json» after `[table] list_rows`; «Из каких договоров» for `count`; «Получено: …» line
- [ ] T011 [US1] [opus] `table_answer.load_rows(conn, settings) -> list[DocRow]` with integration tests first in `tests/integration/test_table_rows.py` on the T005 contracts (research R-5): every registry document, one pass over `field_value`, `field_status`, `field_decision`; cells by `checks.effective_cell`; `no_extraction` for a document without `field_value`, `checks_stale` by `checks.split_fresh` for all six cells; clause id `format_clause_id(document_id, clause_key)`; flags carried. Code in `src/docreader/table_answer.py`
- [ ] T012 [US1] [opus] Failing tests: unit `tests/unit/test_table_answer.py` on `ScriptedModel` (research R-1, R-9): a valid query → `answered`, one model call; an invalid query → one retry with the reason, valid second → `answered`, `retried`; invalid twice → `rejected` with the second reason; a form or HTTP error on the first call → `failed`, on the retry → `rejected` with the first reason; `today` parameter used in the messages; `table_answer.translate(client, question, today)` (model, `validate`, retry) works without a database (R-1); provenance (`PROMPT_VERSION`, prompt sha, `CHECKS_VERSION`, model); integration `tests/integration/test_ask_table_cli.py` (contracts/cli.md): `ask-table` count and list by each of the six fields on T005 contracts, matched spellings shown, zero rows «таких договоров нет» with the condition, the same question twice → the same list (FR-012), `--json` holds the full list and every key of data-model.md, the database row counts unchanged (FR-013), empty question → 1, no extracted fields → 1 without a model call, `DOCREADER_FORBID_MODELS` without a fake → 2 (also on a registry without extracted fields: the model checks come first, R-1), a dropped connection or a timeout of the model call → 2 (as `extract`), output guard T006 case
- [ ] T013 [US1] [sonnet] `translate`, `ask_table` and `TableAnswer` in `src/docreader/table_answer.py` (model client with `[extraction]` and `[table]`; checks in the order of R-1: empty question, model client with `client.check()`, extracted fields exist, then the model; retry R-9), `describe` in `src/docreader/table_query.py`, output in `src/docreader/render.py`, subcommand `ask-table` with `--include-unreviewed` and `--json` in `src/docreader/cli.py`. Make T010 and T012 pass without editing them

**Checkpoint**: US1 работает — quickstart А1 (часть US1).

---

## Phase 4: User Story 2 — Полнота данных (Priority: P1)

**Goal**: ответ называет неучтённые договоры по причинам и со списком; по просьбе учитывает значения «требует просмотра» с пометкой; «отклонено» не учитывается никогда.

**Independent Test**: на договорах T005, где у части поле условия в каждом из состояний R-5, задать вопрос и сравнить число неучтённых по причинам; повторить с `--include-unreviewed`.

- [ ] T014 [US2] [opus] Integration tests `tests/integration/test_ask_table_completeness.py` (SC-006, spec US2): for the condition field one contract in each state of R-5 — `unreviewed` (status «требует просмотра» with a found value: a rule violated, `check-vat` or `check-words`), `needs_review` (the same status without a value, `check-noamount`), `rejected` (an extraction answer with a quote that is not in the text), `not_found`, `no_extraction` (added and parsed, not extracted), `checks_stale` (two cases: `extract` with no `check` at all, and re-`extract` without `check`), `human_corrected` and `human_absent` (via `check load` with an answers file built in the test) — each counted under its reason with its ids, the corrected value used and flagged; `--include-unreviewed` takes the `unreviewed` cells, marks them and the first line, still excludes `rejected` and `needs_review` without a value; output guard case
- [ ] T015 [US2] [opus] Make T014 pass: reasons and marks in `src/docreader/table_query.py`, `src/docreader/table_answer.py`, the «Не учтено (N): …» block and the unreviewed marks in `src/docreader/render.py`. After T013

**Checkpoint**: US1 + US2 — MVP.

---

## Phase 5: User Story 3 — Вопрос, на который таблица не отвечает (Priority: P2)

**Goal**: отказ, уточнение и «не поддерживается» — с причиной; недопустимый запрос — один повтор, затем отказ с причиной; два запроса — первый выполнен, о втором сказано.

**Independent Test**: `ScriptedModel` с ответами `refuse`, `clarify`, `unsupported`, `query` с `other`, недопустимыми запросами; сравнить итоги и сообщения.

- [ ] T016 [US3] [opus] Failing tests in `tests/unit/test_table_answer.py` and `tests/integration/test_ask_table_cli.py`: `refuse` → `refused`: first line «По таблице — отказ; повторов 0; T с», then «Причина: …» and «Поиск по тексту не подставляется (docreader ask)», exit 0; `clarify` → «нужно уточнение», `unsupported` → «не поддерживается» in the same shape, exit 0; the model's `reason` and `other` never in the first line (FR-014, contracts/cli.md); `party` on both sides → `clarify` (contracts with a party name on both sides built in the test); `query` with `other` → answered plus «Выполнен первый запрос; не выполнено: …»; `rejected` → exit 1 with «Запрос модели недопустим: …»; none of these runs the query (no `load_rows` call needed for `refuse`/`clarify`/`unsupported`); output guard case
- [ ] T017 [US3] [sonnet] Outcomes and their output in `src/docreader/table_answer.py` and `src/docreader/render.py`, exit codes in `src/docreader/cli.py`. Make T016 pass without editing it

---

## Phase 6: Записи модели и замер

- [ ] T018 [P] [opus] `tests/synthetic/table_questions.toml` (fictional party names, per contracts/model.md: each of the six fields and `party`, both actions, a period, «до конца квартала» (a single date the model computes from today, R-6), `refuse`, `clarify`, `unsupported`, two requests) and `tests/synthetic/record_table_answers.py` (guards of `tests/synthetic/recording.py`: local model address, questions only from a file inside `tests/synthetic/`; each variant goes through `table_answer.translate` — no database, no contracts (R-11); fixed today `2026-11-28`; recordings `tests/recordings/10-table-answers/<variant>.json` in the format of feature 09) with guard tests in `tests/unit/test_record_table_answers_guard.py`
- [ ] T019 [P] [sonnet] Level 3 `tests/real_model/test_table_server.py` (`pytest -m real_model`, Mac): the server answers, three questions of `table_questions.toml` give `TableReply` by the schema and `validate` accepts the query questions
- [ ] T020 [P] [opus] Failing tests `tests/unit/test_make_table_questions.py` and `tests/unit/test_quickstart_table.py` (research R-12, contracts/cli.md): the generator makes, from effective values given in the test, both actions per field (names — per organisation, number — 5 seeded contracts, amounts — median and quartile thresholds, dates — a year and a period) with `expected`, writes TOML with commented examples for the analyst, refuses to overwrite without `--force`, prints counts only; the measurement compares the query (field, action, op, normalized value) or the outcome and the list (given `documents`, else the expected query executed by `table_query.execute`), counts right answers separately for `template` and `analyst`, retries, outcomes, median and max time; the summary holds numbers, question numbers and ids only (no question text, no value)
- [ ] T021 [sonnet] `scripts/make_table_questions.py` and `scripts/quickstart_table.py` (as `scripts/make_search_questions.py` and `scripts/quickstart_answers.py`): file `$DOCREADER_DATA_DIR/questions/table-10.toml`, summary `table-b4-summary-….txt`, full answers `table-b4-….txt` next to the questions file. Make T020 pass without editing it

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T022 [P] [sonnet] Documentation: `README.md` and `CLAUDE.md` «Commands» — `ask-table` and what may be sent to the agent (the first line and the measurement summary; never the full output on real contracts, the questions file or `table-b4-….txt`); `docs/tech-context.md` — `[table]` settings, the model row (features 05, 09, 10), «Модели в автотестах» — recordings `10-table-answers`
- [ ] T023 [opus] Output guard across `ask-table` (every outcome, text and `--json` error paths) in `tests/integration/test_table_output_guard.py`; a test that no `ask-table` call writes to the database; `scripts/check.sh` passes
- [ ] T024 [analyst] Quickstart Б1–Б2 on the Mac: `pytest -m real_model tests/real_model/test_table_server.py`; `record_table_answers`; commit and push `tests/recordings/10-table-answers/`
- [ ] T025 [opus] Level 2 `tests/integration/test_table_recorded.py` on the T024 recordings (as `tests/integration/test_ask_recorded.py`: `RecordedModel`, `StaleRecording`, no skip): each variant, through `table_answer.translate` (no database), gives the outcome and query of `table_questions.toml`; a variant the real model gets wrong is a finding — reported to the analyst, never edited. After T024
- [ ] T026 [analyst] Quickstart Б3–Б4 on the Mac: three `ask-table` questions (first lines only); `make_table_questions.py`, own questions, `quickstart_table.py`; send the generator output and `table-b4-summary-….txt` only
- [ ] T027 [opus] Quickstart Б5: the item «Ответ по таблице (фича 10), замер …» in `docs/tech-context.md` (right answers by template and by analyst, outcomes, retries, time); a missed target is written down, not tuned; a systematic translation error → an abstract synthetic question and a failing test first (CLAUDE.md «Delivery»)

---

## Dependencies & Execution Order

- Phase 1: T001, T002 parallel.
- Phase 2: T003 → T004; T005 after T002; T006 after T005.
- US1: T007 → T008 → T009 (same module and test file); T010 after T009; T011 after T002, T005; T012 after T004, T005, T006 → T013 (needs T007–T011).
- US2: T014 after T013 → T015.
- US3: T016 after T013 → T017 (after T015: same files).
- Phase 6: T018, T019 after T013 (`translate`, `validate`); T020 after T009 → T021 (needs T013).
- Polish: T022 any time after T013; T023 after T017 and T021; T024 after T018, T019; T025 after T024; T026 after T021 and T023; T027 after T026.

## Parallel Example: User Story 1

```text
T007 → T008 → T009 → T010   one after another (table_query.py, test_table_query.py)
T011 load_rows (integration) ─┐ different files, in parallel with T007–T010
T012 ask_table / CLI tests    ─┘
T013 ask_table, CLI and output (Sonnet), after all of them
```

## Implementation Strategy

1. MVP: Phase 1 → Phase 2 → US1 → US2 — число, условие, список и неучтённые; quickstart А1.
2. US3 — отказы, уточнения, повтор.
3. Phase 6 — записи и скрипты замера; Polish; затем Mac: Б1–Б2 (T024), уровень 2 (T025),
   замер (T026) и запись итогов (T027).
