---
description: "Task list for feature 02 (branch 009): gold set by review of prefilled values, results table, search measurement"
---

# Tasks: Эталонный набор и таблица результатов

**Input**: Design documents from `specs/009-evaluation-set/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/files.md](contracts/files.md), [quickstart.md](quickstart.md)

**Tests**: требуются — plan.md, раздел «Тесты», SC-002…SC-005. Тесты пишутся до кода
и должны падать до реализации по ожидаемой причине.

**Organization**: фазы по историям spec.md — US1 (эталон проверкой, P1), US2 (шаблон
и слепой контроль, P1), US3 (сравнение полей, P1), US4 (таблица результатов, P1),
US5 (вопросы и замер поиска, P2). Схема, каталог, виды значений, исходы, файлы
эталона и правило замены — в Phase 2: они нужны всем историям. MVP — US1 + US3 + US4:
эталон проверкой, сравнение полей, таблица результатов.

## Format: `[ID] [P?] [Story?] [model] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история spec.md (US1…US5)
- **[model]** (CLAUDE.md, «Model routing»; аналитик может поменять до начала implement):
  - `[opus]` — главная сессия сама, тесты и код (plan.md «Критические части»: миграция;
    исход пары и итоги; сопоставление записей; правило замены и версия эталона;
    извлечение правилами; пометки и порядок карточек, перенос ответов, скрытие слепых;
    итог слепого контроля; защиты вывода и страницы);
  - `[sonnet]` — `implementer` на своей модели; тесты к задаче пишет главная сессия
    заранее отдельной задачей `[opus]`, исполнитель их не меняет;
  - `[haiku]` — `implementer` с `model: "haiku"`, тесты и код сам (механическое:
    синтетические файлы и генераторы, вывод, аргументы CLI);
  - `[analyst]` — аналитик на Mac, без агента.
- Задача, не прошедшая ревью, получает новую метку прямо здесь (CLAUDE.md).

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-15), data-model.md, contracts/ обязательны.
- Только синтетические PDF из `tests/synthetic/make_pdfs.py`, создаваемые в фикстурах,
  и синтетические файлы `tests/synthetic/gold/`; никакого обращения к реальной папке
  данных и реальным договорам (CLAUDE.md, принцип I). Значения в синтетике вымышлены.
- Моделей нет: извлечение в тестах — `ScriptedModel` (`use_model`), поиск —
  `TopicEmbedder`, `TableReranker` (`use_embedder`, `use_reranker`);
  `DOCREADER_FORBID_MODELS=1` остаётся в фикстурах. Подделки не меняются.
- Модульные тесты `catalog.py`, `outcomes.py`, `rules.py` и разбора файлов в `gold.py`
  не требуют PostgreSQL (сверка 2026-11-27: `gold.py` импортирует `psycopg` ради
  загрузки, поэтому запрет импорта ослаблен до «без базы в модульных тестах»).
- Ни одна команда `eval` не печатает (обычно и в `--json`) значение эталона, системы
  или правил, текст вопроса или цитату (FR-026); проверка — общий помощник T013,
  каждая задача команды добавляет свой случай.
- Страница проверки: один HTML без внешних ссылок, шрифтов и скриптов (FR-006).
- Существующие генераторы, их `GENERATOR_VERSION` и записи `tests/recordings/` не
  меняются (иначе записи фич 05 и 09 устаревают): новые синтетические договоры — новым
  генератором со своей версией.
- Сообщения пользователю — на русском, как в contracts/; код, идентификаторы,
  комментарии — на английском.
- Перед `[X]`: `scripts/check.sh` проходит (тесты, ruff, mypy).

---

## Phase 1: Setup

**Purpose**: схема и синтетические договоры для правил.

- [X] T001 [opus] Failing integration test `tests/integration/test_migration_0007.py` (data-model.md): `migrate` applies `0007_evaluation` after `0006`; the seven tables exist with their columns; CHECK of `gold_field.state`, `gold_field.path`, `gold_load.kind`, `gold_question.kind`, `gold_question.origin`, `eval_result.stage` equal the `StrEnum` values of `gold.py` / `outcomes.py` / `questions.py` (imported; the test fails until they exist); `gold_field` array checks (`absent` ⇔ empty arrays, equal lengths); removing a document deletes its `gold_field`, `gold_blind`, `blind_pick`, `gold_question` rows and keeps `eval_result`/`eval_case`; a `gold_load` referenced by `gold_field` cannot be deleted
- [X] T002 [opus] `src/docreader/migrations/0007_evaluation.sql` per data-model.md and the enums (`GoldState`, `GoldPath`, `LoadKind` in `gold.py`; `Outcome`, `BlindOutcome`, `EvalStage` in `outcomes.py`; `QuestionKind`, `QuestionOrigin` in `questions.py` — modules created with the enums only). Make T001 pass
- [X] T003 [P] [haiku] Generator `make_rules_contracts(directory) -> list[Path]` and `RULES_GENERATOR_VERSION = 1` in `tests/synthetic/make_pdfs.py`, built on `_extraction_pdf` and the preamble helpers (existing generators untouched). Four fictional contracts `rules-a.pdf` … `rules-d.pdf`: (a) plain — title «ДОГОВОР № …», preamble with both parties «(далее — «Заказчик»)» / «именуемое в дальнейшем «Подрядчик»», section «Цена Договора» with «без учёта НДС» and «с учётом НДС» amounts, clause «Срок действия» with «действует до «DD» месяца YYYY г.»; (b) traps from the catalog «Ловушки для эталона» in abstract form — numbers of other documents («протокол № …», «доверенность № …») before the title number, penalty and guarantee amounts outside the price section, dates of other documents near the term clause; (c) two different amounts «без учёта НДС» in the price section (→ «разошлось»); (d) no term clause and no VAT-free amount (→ nothing found). Unit test `tests/unit/test_make_rules.py`: four files, each text holds its lines, all values fictional

---

## Phase 2: Foundational (blocking)

**Purpose**: каталог, виды значений, исходы, файлы эталона, правило замены, защита вывода.

- [X] T004 [P] [opus] Failing tests `tests/unit/test_catalog.py` (research R-3): `CATALOG` has 68 fields, 35 of queue 1, 11 manual (`free_text` + `list`); `auto_compared` is false for these 11 and for `records` (`price_by_year`, plan deviation 7) and true for the other 56; every field name, kind and queue equals the tables of `docs/field-catalog.md` (the test parses the markdown tables: `*_` rows expand to `customer_`/`contractor_`; kind words map to kinds); choice variants of `contract_type`, `currency`, `payment_day_kind`, `*_authority_kind` equal the catalog; `PROTOTYPE` equals `fields.PROTOTYPE_FIELDS` (names, labels, kinds); `QUEUE1` starts with the six prototype fields; `field("x")` unknown → `KeyError`
- [X] T005 [sonnet] `src/docreader/catalog.py`: `CatalogKind` (`StrEnum` per R-3), `CatalogField(name, label, kind, queue, group, choices, requisite_length)`, `CATALOG`, `PROTOTYPE`, `QUEUE1`, `ALL`, `field(name)`, `auto_compared(field)`. Make T004 pass without editing it
- [X] T006 [P] [opus] Failing tests `tests/unit/test_values_kinds.py` (research R-4): `normalize_field(field, value)` for every catalog kind — requisite (ИНН «7708 503 727» → digits; 9 digits for ИНН → error «значение не приводится к ИНН (10 цифр)»; КПП 9, ОГРН 13, БИК 9, счёт 20); percent «0,1%», «20 %», «20» → `0.1`, `20`, `20`; «две» → error; number «60 (шестьдесят) месяцев» → `60`, «7,5» → error; choice — case and «ё» ignored, unknown → error listing the variants; free text / list / records — as is; the four existing kinds give exactly `values.normalize(kind, value)` (extraction unchanged); `same_value(field, a, b)` — names compare without case, others by equality
- [X] T007 [sonnet] `normalize_field`, `same_value` and the new kind functions in `src/docreader/values.py`; `normalize` and `find_in_quote` unchanged (feature 05 tests still pass). Make T006 pass
- [X] T008 [P] [opus] Failing tests of the pair outcome and totals in `tests/unit/test_outcomes.py` (research R-7): `field_outcome(field, gold, system) -> CaseOutcome(outcome, flags)` — every row of the R-7 table as its own case (manual kind; unlabeled with any system; no row / `failed` / stale / field not extracted → `no_result` with the reason flag; value + found equal → `correct`, one of several variants → `correct`, different → `wrong`; value + `not_found` → `missed`; value + `rejected` → `missed` with `rejected`; absent + found → `invented`; absent + `not_found` → `correct`; absent + `rejected` → `correct` with `rejected`); name compared without case; `totals(cases)` — per field and overall counts of the seven outcomes, the sum equals the number of pairs, shares over `correct + wrong + missed + invented`, fields sorted by the share of `correct` ascending then `invented` descending, fields not extracted by the stage in a separate block; a zero denominator gives no share, not a division error
- [X] T009 [opus] `field_outcome`, `totals` and their data classes in `src/docreader/outcomes.py`. Make T008 pass
- [X] T010 [P] [opus] Failing tests of the gold files in `tests/unit/test_gold_files.py` (research R-2, contracts/files.md): CSV with `;` and with `,`, with BOM and without; rows whose first cell starts with `#` skipped; ` || ` variants; «Отсутствует», « отсутствует » → absent; empty cell → unlabeled; a value of the wrong kind → error with row and column, never the value, the cell unlabeled; an unknown column or no `document_id` → the whole file rejected; a document not in the given registry ids → the row skipped with a reason. Review answers JSON: each `answer` kind (`agree`, `chosen` with `model` / `rules` / `rules:N`, `typed` with `value` and optional `clause`, `absent`, `skip`); `agree` and `chosen` take the value and clause from the build's `cards.json`, not from the answer; an unknown card key → error with the key; wrong `format` → error. `write_template(fields, document_ids)` round-trips through the parser with all cells unlabeled
- [X] T011 [sonnet] File parsing and `write_template` in `src/docreader/gold.py` (pure, no database in its unit tests; see «Общие правила»): `ParsedGold(coverage, values, errors, skipped_rows)`. Make T010 pass
- [X] T012 [opus] Replacement rule, version and load with tests first in `tests/unit/test_gold_replace.py` and `tests/integration/test_eval_gold.py` (research R-5, R-6): `diff(current, parsed)` inside the coverage — added / changed / removed / same, pairs outside unchanged; a type error that clears an existing value counts as removed; pairs last loaded from the other file kind counted; `gold_sha256(rows)` stable to row order and equal for the same content from two files; `load(conn, parsed, kind, file, yes)` — removal without `yes` changes nothing and returns the counts with `needs_confirmation`; with `yes` replaces the coverage rows and writes `gold_load` in one transaction; the same file twice — the version does not change
- [X] T013 [P] [opus] Output guard helper `tests/eval_guard.py`: `assert_no_values(text, secrets)` — fails when any synthetic value, question text or quote (and its comparison form) appears in a command's stdout/stderr; `synthetic_secrets(conn)` collects them from the test database (gold, `field_value`, rules output, questions; the rules and questions parts are added in T018 and T033, when `rules.py` and `questions.py` exist). Its own unit test `tests/unit/test_eval_guard.py`
- [X] T014 [haiku] Group `eval` in `src/docreader/cli.py` with the subcommand `load ФАЙЛ [--yes] [--json]` (contracts/cli.md) calling `gold.load` (CSV → template kind, JSON → review kind) and its output in `src/docreader/render.py`; exit 1 when confirmation is needed. Integration cases in `tests/integration/test_eval_gold.py` (written with T012): the printed counts, the `--yes` line, and `assert_no_values` on the output

**Checkpoint**: эталон загружается из файла; исходы считаются; страница и сравнения ещё не построены.

---

## Phase 3: User Story 1 — Эталон полей проверкой (Priority: P1) 🎯 MVP

**Goal**: `eval review` строит страницу с карточками шести полей (значение фичи 05,
значения правил, цитаты, страницы, пометки), ответы загружаются в эталон.

**Independent Test**: синтетика T003 и `make_extraction_contracts` прочитаны, разобраны,
извлечены с `ScriptedModel`; страница даёт карточки каждого вида; файл ответов,
собранный тестом, загружается.

- [X] T015 [P] [US1] [opus] Rules extraction with tests first in `tests/integration/test_rules.py` (needs read and parse of the generator contracts) (research R-8): `RULES_VERSION = "02.1"` (02.4 after convergence); `extract_rules(index: verify.TextIndex, clauses) -> dict[str, list[FieldResult]]` for the six prototype fields; every candidate goes through `verify.check_field`; on T003 contracts: (a) all six found with the right clause; (b) the trap numbers, penalty amounts and other dates are not taken; (c) two different `amount_without_vat` values, both returned; (d) `contract_end_date` and `amount_without_vat` empty; a candidate whose quote is not in the text is not returned; no database needed. Code in `src/docreader/rules.py`
- [X] T016 [P] [US1] [sonnet] Move page rendering and quote line boxes from `scripts/review_extraction.py` to `src/docreader/pageimage.py` (`render_page`, `pixel_box`, `quote_line_boxes`) without changing behaviour; the script imports them; existing tests of the script pass unchanged
- [X] T017 [US1] [opus] Cards: marks, order, carry-over and blind hiding with tests first in `tests/unit/test_review.py` (pure part) (research R-9): `build_cards(system, rules, gold, blind_waiting) -> list[Card]` — marks `agree` (normalized equal via `same_value`), `disagree` (also whenever the rules give several different values, whatever the model value — spec «Edge Cases»), `model_only`, `rules_only`, `none`, `changed` (a gold row with a review path whose `system_normalized` differs from the current normalized feature 05 value — a typed, absent or rules-chosen answer is not `changed` while the system shows what the analyst saw); order `changed`, `disagree`, `rules_only`, `none`, `model_only`, `agree`, then document and catalog order; a card with gold carries its answer (except `changed`); documents waiting for blind marking give no cards; a rejected system value shows with its reason and counts as `none` / `rules_only`. Code in `src/docreader/review.py`
- [X] T018 [US1] [opus] Failing integration tests `tests/integration/test_eval_review.py`: `eval review` on the synthetic set — cards of each mark (set up with `ScriptedModel` answers that agree, disagree, miss and are rejected), `cards.json` and `index.html` in `eval/review-…/`; places for `none`/`rejected` cards from word search only; a document without current passages (`index` not run) → its cards have no places and the output names the number of such documents; the page has no `http:`, `https:`, `//` or `@import` references and no external `src`/`href`; keys 1/2/3/4/0 and the download button present; a second build after loading the answers carries them; blind-waiting documents are absent and named; stdout passes `assert_no_values`
- [X] T019 [US1] [sonnet] `review.py` page: loading system values, rules, gold and blind state from the database, word-search places (`ranking.py` over the document's passages with the field's question template), page images via `pageimage.py`, `cards.json`, `index.html` (embedded JSON, `localStorage` under the build id, keys, remaining count, download `gold-review-<build>.json`, a light check of typed values). Make T018 pass without editing it
- [X] T020 [US1] [haiku] Subcommand `eval review [ID…] [--out ПАПКА] [--json]` in `cli.py` and its output in `render.py` (contracts/cli.md: path, counts by mark, carried answers, blind-waiting ids, the word-search line)
- [X] T021 [US1] [opus] End-to-end test in `tests/integration/test_eval_gold.py`: extract with `ScriptedModel` → `eval review` → an answers file built by the test (each answer kind) → `eval load` → `gold_field` rows with the right paths (`agree` only for `agree` cards, `confirmed` for «верно» on `model_only`/`rules_only`), values and `system_normalized` from the build (not from the answer file), clause keys; a rebuild after the load marks no card `changed`, and a changed `field_value` makes exactly that card `changed`; a typed value of the wrong kind → «не размечено» with the card key; the second load of the same file — the same version

**Checkpoint**: эталон шести полей собирается проверкой (MVP, часть 1).

---

## Phase 4: User Story 2 — Шаблон и слепой контроль (Priority: P1)

**Goal**: пустой шаблон любого набора полей; слепая разметка 5 договоров до проверки
их карточек и итог контроля в таблице результатов.

**Independent Test**: шаблон синтетического реестра → заполненный файл
`tests/synthetic/gold/` → загрузка; слепая разметка двух договоров с одним расхождением.

- [X] T022 [P] [US2] [haiku] Synthetic gold files in `tests/synthetic/gold/` for the generator contracts: `template-filled.csv` (six prototype fields of two documents, one wrong-kind value, one «отсутствует», one ` || `), `blind-filled.csv`, `field-results.json` (contracts/files.md; `search-results.json` is written in T035: its keys are the question keys of `questions.py`); a unit test that the CSV files parse with the parsers of T011 and that `field-results.json` has the shape of contracts/files.md (its reader comes in T027 and is checked in T026)
- [X] T023 [US2] [opus] Failing tests of the template and blind control: `tests/integration/test_eval_blind.py` and cases in `tests/integration/test_eval_gold.py` — `eval template` with `--fields prototype|queue1|all` (6 / 35 / 68 columns, prototype first, hint rows, all cells empty, `--documents`, never over an existing file); `eval blind pick` — 1 text-layer document if any plus scans at an even step, 5 in all (fewer documents → all, the count named), stored, the same on a second `pick`, new with `--again`; its template has the six prototype fields; `eval blind load` — kind checks as the template, rows in `gold_blind`, not in `gold_field`; `eval review` hides those documents until `blind load`
- [X] T024 [US2] [sonnet] `eval template` (`gold.write_template` + CLI + output) and `blind.py`: `pick(docs, scans, layers)` generalising `scripts/quickstart_extraction.pick_review` (the script kept its own copy and its tests pass unchanged — convergence 2026-11-27), `blind pick`, `blind load` and their CLI and output. Make T023 pass without editing it
- [X] T025 [US2] [opus] Blind control report with tests first in `tests/unit/test_blind.py` and `tests/integration/test_eval_blind.py` (research R-10): only pairs reviewed after the blind load count; outcomes `same`, `differs`, `blind_only`, `reviewed_only`; differences overall and among pairs whose path is `agree`, `confirmed` or `chosen`; `eval blind report [--label]` writes an `eval_result` of stage `gold_blind` with its cases (the record writer of T027) and the CSV review file; a second `blind report` after a corrected answer is loaded → a new record, the previous one kept (US2 scenario 10); output passes `assert_no_values`. Depends on T027

**Checkpoint**: шаблон и слепой контроль работают.

---

## Phase 5: User Story 3 — Сравнение полей с эталоном (Priority: P1)

**Goal**: `eval fields` — исход каждой пары, итоги, запись таблицы результатов
со случаями, файл разбора; источник — фича 05, правила или файл.

**Independent Test**: синтетический эталон + результаты с заранее известными исходами;
`eval fields` даёт по одному случаю каждого исхода и те же случаи при повторе.

- [X] T026 [US3] [opus] Failing integration tests `tests/integration/test_eval_fields.py` (research R-7, R-13, contracts/cli.md): the pairs are all registry documents × the fields of the set (default — every field with at least one gold row); system values read from `field_value` — current, stale (document re-read with a changed text), `failed`, field not extracted (a queue-1 field in the gold) → `no_result` with the reason; one case of every outcome; `--source rules` → stage `rules`, provenance `RULES_VERSION`; `--from tests/synthetic/gold/field-results.json` → `from_file` set; `eval_result` with provenance (runs of the `field_value` rows: model, prompt version), gold version, reviewed share, blind summary; `eval_case` rows equal the pairs; the stored metrics equal a recount from `eval_case`; the review CSV holds gold and system values, clause and quote; the same comparison twice → two records with identical cases (SC-003); an empty gold → code 1 and no record; output passes `assert_no_values`
- [X] T027 [US3] [sonnet] `src/docreader/evaluation.py`: collecting system values (extraction, rules, file), `compare_fields`, the record writer (`eval_result` + `eval_case` in one transaction, sum check before writing), provenance, the review CSV. Make T026 pass without editing it
- [X] T028 [US3] [haiku] Subcommand `eval fields [--label] [--source] [--from] [--fields] [--json]` in `cli.py` and the table output in `render.py` per contracts/cli.md

**Checkpoint**: сравнение полей пишет записи (MVP, часть 2).

---

## Phase 6: User Story 4 — Таблица результатов и сопоставление (Priority: P1)

**Goal**: `eval results`, `show`, `compare`, `export`.

**Independent Test**: две записи с разными результатами системы и одна по прежней
версии эталона; сопоставление даёт все изменившиеся случаи и ни одного лишнего.

- [X] T029 [P] [US4] [opus] Comparison of records with tests first in `tests/unit/test_outcomes.py` (research R-13): `compare(a, b)` — only the same stage (else error); metric differences; cases by key: ranks `correct` 0, `missed` 1, `wrong` 2, `invented` 3 → «стало лучше» / «стало хуже»; to and from `no_result`, `unlabeled`, `manual` → «вне сравнения»; a case whose `gold_sha` differs → «из-за эталона» (and not in better/worse); search cases: smaller place better, «не найден» worse than any place; a case only in one record → «вне сравнения»; every changed case appears exactly once, unchanged ones never (SC-005). Code in `src/docreader/outcomes.py`
- [X] T030 [US4] [opus] Failing integration tests `tests/integration/test_eval_results.py`: `eval results` (with `--stage`, the «прежняя» mark after a new gold load), `eval show N --field F --outcome O` lists exactly the cases of that number (SC-004), `eval compare A B` groups and the gold warning, different stages → code 1, `eval export` CSV with BOM and `;` that round-trips Cyrillic; outputs pass `assert_no_values`
- [X] T031 [US4] [sonnet] `results`, `show`, `compare` (loading the two records and calling `outcomes.compare`), `export` in `evaluation.py`. Make T030 pass without editing it
- [X] T032 [US4] [haiku] Subcommands `eval results|show|compare|export` in `cli.py` and their output in `render.py`

**Checkpoint**: MVP готов: эталон проверкой, сравнение, таблица результатов.

---

## Phase 7: User Story 5 — Вопросы и замер поиска (Priority: P2)

**Goal**: вопросы из наборов фич 08 и 09, генерация из эталона, пункты из ответов
замера фичи 09; `eval search` — места без реранкера и с ним, две записи.

**Independent Test**: синтетические наборы вопросов загружаются; генерация даёт каждый
вид; замер поиска с подделками и из файла даёт ожидаемые места.

- [X] T033 [P] [US5] [opus] Failing tests of questions in `tests/unit/test_questions.py` and `tests/integration/test_eval_questions.py` (research R-11, contracts/files.md): the question key stable to spaces, «ё» and case; `tests/synthetic/search_questions.toml` and `answer_questions.toml` load as they are (`answer` → text kind with the clause; `expected = "none"` → no answer; `document` + `expected = "answer"` → «пункт не указан», stored with `has_answer` and no clauses, counted separately in the composition with the `clauses` hint; `contains` → expected); new keys `answers`, `kind`, `false_premise`; exactly one of `answer`/`answers`/`expected`; `origin` from the file's top-level key, else `--origin`, else `own`; `generate` writes `origin = "generated"`; errors with the question number (bad clause id, unknown document, clause not in the current parse); a file loaded twice replaces its own questions; the same question in two files → one row, the latest flags, the differing numbers named; the composition and the warnings (< 10 without answer, < 5 false premise); `generate` — a question with answer per gold value with a clause, without answer per «отсутствует», false premise for amounts and dates with another document's value, the shortfall counted, never over an existing file, the six prototype templates equal `scripts/make_search_questions.TEMPLATES`; `clauses` — proposals from a synthetic `answers-b4-….json` with the comment mark, matched to the questions file by document and text (the question key), not by number: the answers file may come from a run on a part of the questions; the output holds the whole source set (with its `origin`), proposals filled in only for «пункт не указан» questions; `scripts/quickstart_answers.py` writes `answers-b4-<time>.json` next to the text files (format of contracts/files.md); outputs pass `assert_no_values`
- [X] T034 [US5] [sonnet] `src/docreader/questions.py`: key, TOML parsing, load (replace per file, merge across files), composition; `TEMPLATES` moved from `scripts/make_search_questions.py` (the script imports them, its tests pass unchanged); `generate`; `clauses`; the JSON output of `scripts/quickstart_answers.py`. Make T033 pass without editing it
- [X] T035 [US5] [opus] Failing tests of the search measurement in `tests/unit/test_outcomes.py` and `tests/integration/test_eval_search.py` (research R-12): `search_place(results, correct)` — the first of several correct clauses, «не найден», exact match only; `search_metrics` — shares at first place and in the first five over participating questions («не найден» in the denominator), median over found, counts of not found and excluded; `eval search` with `TopicEmbedder`/`TableReranker` on `make_search_contracts` and `tests/synthetic/search_questions.toml` — two records `search_plain` and `search_rerank` with one label and the places equal to what `scripts/quickstart_search.py` gives on the same set (SC-007); `--from tests/synthetic/gold/search-results.json` (written in this task with the question keys of T034, contracts/files.md) works under `DOCREADER_FORBID_MODELS`; without `--from` under FORBID → code 2 before the first question and no record; questions without answer, of kind `table` and «пункт не указан» excluded and counted; `eval show N --outcome first|top5|found|not_found|excluded` on a search record lists exactly the questions of that number (SC-004, FR-015); the review CSV; outputs pass `assert_no_values`
- [X] T036 [US5] [sonnet] `search_place`, `search_metrics` in `outcomes.py` and the measurement in `evaluation.py` (the same `search.search` calls as `scripts/quickstart_search.py`); the search filter of `eval show`. Make T035 pass without editing it
- [X] T037 [US5] [haiku] Subcommands `eval questions load|generate|clauses` and `eval search` in `cli.py` and their output in `render.py`

**Checkpoint**: все пять историй работают на синтетике.

---

## Phase 8: Polish & Cross-Cutting

- [X] T038 [opus] Guard sweep: `tests/unit/test_render_eval.py` runs every `eval` command of contracts/cli.md (plain and `--json`) on one synthetic database and checks each with `assert_no_values`; the review page check of T018 extended to every page asset; `--out` outside the data folder → code 1 and nothing written, for `template`, `review`, `export`, `questions generate`, `questions clauses` (FR-006, FR-025; tests and code here)
- [X] T039 [P] [sonnet] Documentation: `CLAUDE.md` «Commands» — the `eval` group, what may be sent to the agent (terminal output only, never the files); `docs/tech-context.md` — the data model rows (`gold_load`, `gold_field`, `blind_pick`, `gold_blind`, `gold_question`, `eval_result`, `eval_case`; `control_string` later), the file formats (R-2), `catalog.py` as the catalog in code, the rules helper (R-8); plan deviations 1–9 written back where tech-context names the decision
- [X] T040 [opus] `scripts/check.sh` and quickstart part А on `docreader_demo` in a throwaway data dir (no `~/docreader-data`, no `docreader` database); fix what fails
- [X] T041 [analyst] Quickstart Б0–Б6 on the Mac: Б1 editor check first (stop if Cyrillic breaks); Б2 blind marking before the review (note whether the template and its hints were enough without the documentation — SC-006); Б3 review and load with the time noted; Б4 blind report; Б5 questions (the eight questions without a clause re-run with `scripts/answers_b4.sh --questions …`); Б6 first records. Send only the terminal output of the `docreader eval …` commands and the times — never the files
- [X] T042 [opus] Quickstart Б7: the item «Эталонный набор (фича 02), …» in `docs/tech-context.md` (gold composition and paths, manual time vs SC-008, «совпало» share — SC-009, blind control — SC-010, questions — SC-011, first figures of fields, rules and search, SC-001 time, SC-007, SC-006 and the CSV check of Б1–Б2); a missed target is written down, not tuned; a systematic rules failure → an abstract case in `make_rules_contracts` (bump `RULES_GENERATOR_VERSION`) and a failing test first (CLAUDE.md «Delivery»)

---

## Dependencies & Execution Order

- Phase 1: T001 → T002; T003 independent.
- Phase 2 (after T002): T004 → T005; T006 → T007; T008 → T009; T010 → T011 (needs T005,
  T007) → T012 → T014; T013 independent of T012.
- US1 (after Phase 2 and T003): T015, T016 in parallel; T017 (needs T015) → T018 →
  T019 → T020 → T021.
- US2 (after Phase 2): T022 any time after T011; T023 → T024; T025 after T027.
- US3 (after Phase 2; the tests build the gold directly, so US1 is not needed): T026 →
  T027 → T028.
- US4 (after T027): T029 in parallel with T026–T028; T030 → T031 → T032.
- US5 (after Phase 2 and T027): T033 → T034 → T035 (its results file needs the question keys;
  `eval search` needs loaded questions) → T036; T037 after T036.
- Polish: T038 after all commands; T039 any time after T032; T040 after T038; T041 after
  T040 and the branch is pushed; T042 after T041.

## Parallel Opportunities

- T003 ∥ T001–T002.
- In Phase 2: T004, T006, T008, T010, T013 (tests by the main session) in parallel;
  T005 ∥ T007 (implementer, different files).
- In US1: T015 ∥ T016.
- T022 ∥ US1; T029 ∥ US3.

## Implementation Strategy

1. Phase 1–2 → эталон загружается, исходы считаются.
2. US1 → страница проверки; аналитик может начать Б1–Б3 (T041) после T021 и T024.
3. US3 + US4 → сравнение и таблица результатов: MVP.
4. US2 report, US5 → итог слепого контроля, вопросы, замер поиска.
5. Polish → защиты, документация, quickstart А, затем Б на Mac и запись итогов.

## Phase 9: Convergence

- [X] T043 [opus] Store the system value on a review answer «отсутствует» (`gold.parse_review_answers`), so a rebuilt page does not mark the card `changed`; end-to-end test review → load absent → rebuild per FR-001, FR-004, US1/AC5, T017 (contradicts)
- [ ] T044 [sonnet] `eval load`: counts per field (accepted, absent, skipped, by path) in text, `--json` and `gold_load.counts` per FR-005, US1/AC6, US2/AC2 (partial)
- [ ] T045 [sonnet] `eval compare` and `eval export`: per-field metrics diffed and exported (metrics keyed by field, not a list) per FR-016, US4/AC2 (partial)
- [ ] T046 [sonnet] Provenance of a record shown in `eval results` / `eval show` (text and `--json`) and in `eval export`; results text with reviewed share and blind summary per US4/AC1, FR-014 (partial)
- [ ] T047 [sonnet] Blind cases carry a «confirmed system value» flag; `eval show` filters by it so the figure «разошлось N из M при подтверждённом значении системы» opens to its cases per FR-015, SC-004 (partial)
- [X] T048 [opus] «верно» on a card where the model and the rules agree is stored with the path «совпало» whatever its mark per FR-005 (contradicts)
- [ ] T049 [sonnet] Template: the «отсутствует» / « || » note in every column's hint per FR-007, US2/AC1 (partial)
- [X] T050 [opus] Rules: «действует до … включительно» for `contract_end_date`, synthetic case first per plan: R-8 (partial)
- [ ] T051 [sonnet] `eval fields --from`: the review CSV shows the file's value as the system value per FR-027, US3/AC8 (partial)
- [ ] T052 [sonnet] `eval search` text shows the excluded «пункт не указан» count; `questions generate` names the no-answer shortfall per US5/AC7, SC-011 (partial)
- [ ] T053 [sonnet] Provenance: `run.settings` of the extraction runs in `fields` records and the `[reranker]` settings in `search` records per plan: R-13 (partial)
- [ ] T054 [sonnet] Review page: keys for a third and further choices that do not clash with «другое значение» (partial)
- [ ] T055 [haiku] Tests for the `--out` refusal of `eval export`, `eval questions generate` and `eval questions clauses` per T038 (partial)
- [ ] T056 [opus] Documents follow the code: contracts/files.md hint row, contracts/cli.md (`eval review` note, `questions load` lines), research R-4 (short-name matching), R-10 and data-model (blind values normalized again), R-6 and the spec edge cases on question conflicts and other-kind pairs, the spec edge case on a re-parse (R-7), T015 rules version, plan file names, plan deviation 8 and T024 (`quickstart_extraction.py` keeps its own pick), T011/T015 «no psycopg» relaxed to «no database in unit tests» per plan, spec (contradicts)
- [ ] T057 [opus] Record `scripts/survey_gold_diversity.py` (gold diversity survey, used in Б7) as an added task; fix its docstring feature number per CLAUDE.md «Survey before clarify» (unrequested)
