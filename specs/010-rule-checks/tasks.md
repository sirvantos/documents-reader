---
description: "Task list for feature 06 (branch 010): rule checks and field statuses on the six prototype fields"
---

# Tasks: Проверки правилами и статусы полей

**Input**: Design documents from `specs/010-rule-checks/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/files.md](contracts/files.md), [quickstart.md](quickstart.md)

**Tests**: требуются — plan.md «Testing», SC-001, SC-002, SC-005, SC-006; CLAUDE.md
(test-first). Тесты пишутся до кода и должны падать до реализации по ожидаемой причине.

**Organization**: фазы по историям spec.md — US1 (статусы, P1), US2 (очередь и сводка, P1),
US3 (решения аналитика, P2), US4 (польза правил, P2). Схема, настройки, числительные,
синтетические договоры с ошибками и защита вывода — в Phase 1–2: они нужны всем
историям. MVP — US1 + US2: статусы, сводка, страница очереди.

## Format: `[ID] [P?] [Story?] [model] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история spec.md (US1…US4)
- **[model]** (CLAUDE.md, «Model routing»; аналитик может поменять до начала implement):
  - `[opus]` — главная сессия сама, тесты и код (plan.md «Модели для задач»: миграция;
    таблица статусов и устаревание; решения и «значение системы изменилось»; правила
    прописи и НДС; защита вывода);
  - `[sonnet]` — `implementer` на своей модели; тесты к задаче пишет главная сессия
    заранее отдельной задачей `[opus]`, исполнитель их не меняет;
  - `[haiku]` — `implementer` с `model: "haiku"`, тесты и код сам (механическое:
    настройки, генератор синтетики; аргументы CLI и вывод идут одной задачей с командой,
    `[sonnet]`);
  - `[analyst]` — аналитик на Mac, без агента.
- Задача, не прошедшая ревью, получает новую метку прямо здесь (CLAUDE.md). T006 (Haiku)
  не прошёл ревью: вспомогательная функция генератора перекрыла существующую
  `_check_pages` и сломала тесты чтения; исправлено в главной сессии, задачи генераторов
  с этой фичи — Sonnet.

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-12), data-model.md, contracts/ обязательны.
- Только синтетические PDF из `tests/synthetic/make_pdfs.py`, создаваемые в фикстурах;
  никакого обращения к реальной папке данных и реальным договорам (CLAUDE.md, принцип I).
  Значения в синтетике вымышлены.
- Моделей нет: извлечение в тестах — `ScriptedModel` (`use_model`);
  `DOCREADER_FORBID_MODELS=1` остаётся в фикстурах.
- Существующие генераторы, их версии и записи `tests/recordings/` не меняются: новые
  синтетические договоры — новым генератором `make_check_contracts` со своей версией.
- Ни одна команда `check` не печатает (и в `--json`) значение системы, решения или
  эталона, цитату или текст (FR-013); проверка — помощник вывода T007, каждая задача
  команды добавляет свой случай.
- `field_value` и `gold_field` команды `check` не пишут (FR-008, уточнение 2026-11-27).
- Сообщения пользователю — на русском, как в contracts/; код, идентификаторы,
  комментарии — на английском.
- Перед `[X]`: `scripts/check.sh` проходит (тесты, ruff, mypy; код возврата самой
  проверки, не конвейера).

---

## Phase 1: Setup

- [X] T001 [opus] Failing integration test `tests/integration/test_migration_0008.py` (data-model.md): `migrate` applies `0008_checks` after `0007`; tables `field_check` (PK `document_id`, `field`, `rule`), `field_status` (PK `document_id`, `field`; column `settings_sha256 char(64)`), `field_decision` (PK `document_id`, `field`) with their columns; CHECK of `field_check.outcome` = `RuleOutcome` («`passed`, `violated`, `not_applied`»), `field_status.status` = `FieldStatus` («`accepted`, `needs_review`, `rejected`, `not_found`»), `field_decision.kind` = `DecisionKind` («`confirm`, `correct`, `absent`») imported from `src/docreader/checks.py`; field CHECK «одно из шести полей прототипа»; `field_decision` CHECK «`correct` ⇔ `value_text` и `value_normalized` не NULL»; `eval_result.stage` accepts `checks`; CHECK of `eval_case.outcome` = the feature 02 outcomes plus `CheckOutcome` («`queued_wrong`, `queued_right`, `accepted_wrong`, `accepted_right`», from `src/docreader/outcomes.py`; research R-10), `test_migration_0007.py` still passes; deleting a document deletes its rows in all three tables
- [X] T002 [opus] Migration `src/docreader/migrations/0008_checks.sql` and the enums `RuleOutcome`, `FieldStatus`, `DecisionKind`, `CHECKS_VERSION = "06.1"` in `src/docreader/checks.py`, `RunStage.CHECKS` in `src/docreader/stages.py`, `EvalStage.CHECKS` and `CheckOutcome` in `src/docreader/outcomes.py`. Make T001 pass
- [X] T003 [P] [haiku] `CheckSettings` (`[checks]`: `vat_rate = 20`, `end_date_min = "2015-01-01"`, `end_date_max = "2040-12-31"`) in `src/docreader/config.py` with validation (rate 0–100, dates ISO, min ≤ max) and tests in `tests/unit/test_config.py`; `[checks]` added to the list of sections in `README.md` («Настройки»)

## Phase 2: Foundational (blocking)

- [X] T004 [P] [opus] Failing tests `tests/unit/test_numwords.py` (research R-3): the cases of `tests/unit/test_survey_rule_checks.py::test_words_to_int` plus «одна тысяча», «две тысячи», «двадцать один миллион», «девятьсот девяносто девять тысяч девятьсот девяносто девять», «ноль»; stops at «руб*»/«коп*»; an unknown word → `None`; empty → `None`
- [X] T005 [sonnet] `src/docreader/numwords.py` (`words_to_int`, `words_of_amount(value_text, after)`) moved from `scripts/survey_rule_checks.py`; the survey imports them from `docreader.numwords` and its tests pass unchanged. Make T004 pass without editing it
- [X] T006 [P] [sonnet] Generator `make_check_contracts(directory)` in `tests/synthetic/make_pdfs.py` (research R-11, own `CHECK_GENERATOR_VERSION = 1`), text-layer PDFs with fictional parties and amounts: `check-clean` (no defect), `check-words` (amount in words ≠ digits), `check-vat` (with VAT ≠ without × 1,2), `check-rate10` («НДС (10%)» written and kept), `check-exempt` («НДС не облагается», one amount), `check-zero` (price without VAT 0 roubles), `check-date` (end date 2045), `check-same` (both parties the same short name), `check-noamount` (no price with VAT); matching `ScriptedModel` answers in `tests/integration/check_fixtures.py`; tests in `tests/unit/test_make_checks.py` (key lines in the text layer, version)
- [X] T007 [opus] Output guard for `check` commands in `tests/integration/test_check_output_guard.py` on top of `tests/eval_guard.py`: a helper that runs a command and fails if any synthetic value, quote or party name of `make_check_contracts` appears in stdout/stderr (text and `--json`); first case — `check --help`

---

## Phase 3: User Story 1 — Проверить значения и присвоить статусы (Priority: P1) 🎯 MVP

**Goal**: каждое из шести полей получает один статус и перечень правил с исходами.

**Independent Test**: синтетические договоры T006 → `extract` (`ScriptedModel`) → `check`;
статусы и нарушенные правила совпадают с ожидаемыми; повторный `check` — то же (SC-005).

- [X] T008 [P] [US1] [opus] Failing tests `tests/unit/test_checks_rules.py` (research R-2 table): `amount_positive`, `parties_differ`, `required`, `kind_valid`, `end_date_range` — each on a value with the defect, without it, and the «не применялось» case with its reason code; values built in the test as `DocFields`, no database
- [X] T009 [US1] [sonnet] Rules `amount_positive`, `parties_differ` (`values.same_value`), `required` (number, both short names, both amounts), `kind_valid` (`values.normalize_field`), `end_date_range` (`[checks]`) and the registry `Rule(code, fields, fn)`, `RULES` in `src/docreader/checks.py`. Make T008 pass without editing it
- [X] T010 [US1] [opus] Rules `amount_words` (`numwords`; brackets in `value_text` or right after the value; roubles only; `words_differ`, `words_unreadable`, `no_words`) and `vat_consistent` (rate from the quotes «НДС … N%», else `[checks] vat_rate`; `Decimal`, `quantize(0.01, ROUND_HALF_UP)`, no tolerance; `one_amount`, `exempt` — `exempt` wins when both hold) with tests first in `tests/unit/test_checks_rules.py` (research R-3, R-4), among them: words of another amount in the same quote (the VAT sum) are not taken for the field's words; words with kopecks or «руб.»/«коп.» compare by roubles. After T009 (same files, uses its registry)
- [X] T011 [US1] [opus] Field status and staleness with tests first in `tests/unit/test_checks_status.py` (research R-6 rows 3–7, R-7): `rejected` → «отклонено», rules not applied; `failed` → «требует просмотра» with the extraction reason; for both every rule of the field is stored `not_applied` with reason `rejected`/`failed` (FR-002); any `violated` → «требует просмотра» with all violated rules; `not_found` of the end date → «не найдено», of a required field → «требует просмотра» `required_missing`; else «принято»; flag `document_needs_review` from `stage_status` of reading or structure; stale when `extraction_run_id`, `checks_version` or `settings_sha256` (fingerprint of `[checks]`, analyze U2) differ. Code `field_status`, `is_stale` in `src/docreader/checks.py`
- [X] T012 [US1] [opus] Failing integration tests `tests/integration/test_check_cli.py` (contracts/cli.md «check»): T006 contracts → `extract` → `check` — every field one status (SC-001), expected rules violated per contract; `check` again → nothing to do; `check --again` → same statuses (SC-005); a document without extraction → skipped with its reason; re-`extract` → `check` rechecks only that document; `stage_status` `checks` = `done`/`needs_review`; `field_value` unchanged; output guard T007 case
- [X] T013 [US1] [sonnet] Command `check [ID…] [--all] [--again] [--json]`: run `RunStage.CHECKS`, per document one transaction replacing its `field_check` and `field_status` rows, `stage_status`, totals; in `src/docreader/checks.py`, output in `src/docreader/render.py`, group `check` in `src/docreader/cli.py`. Make T012 pass without editing it
- [X] T014 [US1] [opus] SC-002 test `tests/integration/test_check_catch.py`: on the T006 contracts each rule catches every error made for it (`amount_words`, `vat_consistent`, `amount_positive` on `check-zero`, `end_date_range`, `parties_differ`, `required`) and no rule fires on `check-clean`; `check-rate10` gives no `vat_consistent` violation; `check-exempt` gives `not_applied` `exempt`

**Checkpoint**: статусы ставятся и повторяются.

---

## Phase 4: User Story 2 — Очередь просмотра и сводка (Priority: P1)

**Goal**: сводка по статусам и страница очереди, самые важные первыми.

**Independent Test**: после T013 — `check summary` и `check queue` на синтетике: числа,
состав и порядок карточек, страница без внешних ссылок.

- [X] T015 [P] [US2] [opus] Failing tests: `tests/unit/test_check_queue.py` (order: the cards of the five required fields, then the end date; within each of the two groups by document, then catalog order; `system_changed` first in its group — research R-9; card content per contracts/files.md; parse of `docreader-check-review/1` answers: `agree` (only on a `found` card; refused with a reason on `rejected`/`failed`/`not_found` cards — analyze U1), `typed` with kind check by field, `absent`, `skip`, unknown key or format rejected; a `rejected` card shows the model's proposal marked «цитата не подтверждена») and integration cases in `tests/integration/test_check_cli.py` for `check summary` (counts per field and total, stale documents counted, contracts/cli.md) and `check queue` (folder `checks/queue-<сборка>/` with `cards.json`, `index.html`, `img/`; `--out` outside the data dir refused; stale documents named; page has no external references; output guard)
- [X] T016 [US2] [sonnet] `check summary [--json]` in `src/docreader/checks.py` and `src/docreader/render.py`. Make its T015 cases pass without editing them
- [X] T017 [US2] [sonnet] `check queue [ID…] [--out ПАПКА] [--json]`: cards and order in `src/docreader/check_queue.py`, page via `review_page.render_html` with the answers format as a parameter (`docreader-gold-review/1` stays the default for feature 02), images via `pageimage`; CLI and output. Make the T015 queue cases pass without editing them

**Checkpoint**: MVP — статусы, сводка, страница очереди.

---

## Phase 5: User Story 3 — Решения аналитика (Priority: P2)

**Goal**: решения со страницы очереди хранятся отдельно и переживают повторное извлечение.

**Independent Test**: ответы трёх видов → `check load` → статусы по решениям; повторный
`extract` с другим значением → `check` → «значение системы изменилось»; эталон не изменился.

- [X] T018 [US3] [opus] Decisions with tests first (unit `tests/unit/test_checks_status.py` rows 1–2 of research R-6; integration `tests/integration/test_check_decisions.py`): `check load ФАЙЛ` finds the build by `build`, writes `field_decision` with the system value of the build's card in `cards.json` (`system_result`, `system_normalized`; if the extraction differs by now the field gets `system_changed` at once), an answer for a removed document or a pair without a `field_value` row is not applied and counted (contracts/cli.md), replaces an earlier decision of the pair, a `typed` value that does not normalize is not accepted (card named, no value), statuses recomputed; `confirm`/`correct` → «принято» `human_confirmed`/`human_corrected`, `absent` → «не найдено» `human_absent`; re-`extract` with another value + `check` → «требует просмотра» `system_changed`, decision kept and shown on the next queue card; `gold_field` and `field_value` unchanged (SC-006); `checks.effective_value` (research R-8); output guard case. Code in `src/docreader/checks.py`, `src/docreader/check_queue.py`, `src/docreader/render.py`, `src/docreader/cli.py`

---

## Phase 6: User Story 4 — Польза правил по эталону (Priority: P2)

**Goal**: отчёт о пользе правил по эталону фичи 02 — запись таблицы результатов.

**Independent Test**: синтетический эталон фичи 02 на договорах T006, часть значений
системы неверна (`ScriptedModel`), → `check report`; числа совпадают с подсчитанными вручную.

- [X] T019 [P] [US4] [opus] Failing tests: unit `tests/unit/test_check_report.py` (research R-10: per rule `fired`, `fired_on_wrong`; per field and total `wrong_in_queue / wrong`, `right_in_queue / right`; decisions ignored; `unlabeled`, `no_result`, `manual` out and counted) and integration `tests/integration/test_check_report.py` (gold loaded from a feature 02 template in the test; `check report --label` writes `eval_result` stage `checks` with provenance — `CHECKS_VERSION`, extraction and check runs, `[checks]` — gold version and `eval_case` per pair with outcome `queued_wrong`/`queued_right`/`accepted_wrong`/`accepted_right` and the fired rules in flags; `eval show` (with `--outcome` of the four outcomes), `eval compare` (order `accepted_right`, `queued_wrong`, `queued_right`, `accepted_wrong`), `eval export` work on it; review CSV `eval/checks-<запись>-<время>.csv` per contracts/files.md; no gold → code 1; stale and unlabeled documents counted; output guard)
- [X] T020 [US4] [sonnet] `check report [--label] [--json]`: metrics in `src/docreader/outcomes.py`, record and cases in `src/docreader/evaluation.py`, command in `src/docreader/checks.py`, output in `src/docreader/render.py`. Make T019 pass without editing it

---

## Phase 7: Polish & Cross-Cutting

- [ ] T021 [P] [sonnet] Documentation: `README.md` and `CLAUDE.md` «Commands» — the `check` group and what may be sent to the agent (terminal output only; never the queue page, answers or report files); `docs/tech-context.md` — data model rows `field_check`, `field_status`, `field_decision` and the `field_value` row (plan deviation 1), `[checks]` settings
- [ ] T022 [opus] Output guard across all `check` commands (`check`, `summary`, `queue`, `load`, `report`, text and `--json`) in `tests/integration/test_check_output_guard.py`; performance case: `check --all` on 56 synthetic documents (generated in the test) under 60 s (SC-004); `scripts/check.sh` passes
- [ ] T023 [analyst] Quickstart Б0–Б3 on the Mac: migration; `check --all` with time, `summary` twice (SC-001, SC-004, SC-005); `check report` (SC-003); `check queue`, decisions, `check load`, `summary` with the queue time (SC-006, SC-007). Send only the terminal output and times — never the page, answers or report files
- [ ] T024 [opus] Quickstart Б4: the item «Проверки правилами (фича 06), замер …» in `docs/tech-context.md` (statuses of the working set, time, rule usefulness by the gold set, queue time); a missed target is written down, not tuned; a systematic false alarm → an abstract case in `make_check_contracts` (bump its version) and a failing test first (CLAUDE.md «Delivery»)

---

## Dependencies & Execution Order

- Phase 1: T001 → T002; T003 parallel.
- Phase 2: T004 → T005; T006 parallel; T007 after T006 (needs its values).
- US1: T008 → T009 → T010 → T011 (one after another: all write `src/docreader/checks.py`; T008 and T010 share `tests/unit/test_checks_rules.py`); T012 after T006, T007 (may be written while T009–T011 go) → T013 (needs T009–T011) → T014.
- US2: T015 after T013 → T016, T017.
- US3: T018 after T017.
- US4: T019 after T013 (needs T006 and feature 02 gold) → T020.
- Polish: T021 any time after T013; T022 after T018 and T020; T023 after T022; T024 after T023.

## Parallel Example: User Story 1

```text
T008 rule tests (unit)           ─┐ different files, both after T005–T007
T012 integration tests of check  ─┘
T009 → T010 → T011 one after another (same module), then T013 (command) → T014 (SC-002)
```

## Implementation Strategy

1. MVP: Phase 1 → Phase 2 → US1 → US2 — статусы, сводка, страница очереди; quickstart Б1.
2. US3 — решения аналитика; US4 — отчёт по эталону (независимы друг от друга).
3. Polish, затем замер на Mac (T023) и запись итогов (T024).
