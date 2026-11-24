---
description: "Task list for feature 07 (branch 006): passages, labels and indexes, minimal version"
---

# Tasks: Нарезка, метки и индексы (минимальная версия)

**Input**: Design documents from `specs/006-passages-and-indexes/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/embedding.md](contracts/embedding.md), [quickstart.md](quickstart.md)

**Tests**: требуются — plan.md, раздел «Тесты», quickstart А, SC-005. Тесты пишутся до
кода и должны падать до реализации по ожидаемой причине.

**Organization**: фазы по историям spec.md — US1 (нарезка и метки, P1), US2 (индексы, P1),
US3 (просмотр отрывка, P2). US1 — чистые правила без базы и модели (spec.md, US1,
Independent Test — сравнить отрывки с записями разбора); US2 строит на них этап `index`
с записью в базу; US3 читает записанное.

## Format: `[ID] [P?] [Story?] [model] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история spec.md (US1…US3)
- **[model]** (CLAUDE.md, «Model routing»; аналитик может поменять до начала implement):
  - `[opus]` — главная сессия сама, тесты и код (критичное фичи 07 по plan.md «Критические
    части»: миграция `0006_passages.sql` и запись отрывков и векторов, образ базы
    в `compose.yaml`, нарезка и покрытие, метка, обрезка и состояние с причиной, выбор
    договоров и устаревание, интерфейс модели поиска с подделками и защиты — в том числе
    проверка петлевого адреса в разделе `[embedding]`);
  - `[sonnet]` — `implementer` на своей модели; тесты к задаче пишет главная сессия
    заранее отдельной задачей `[opus]`, исполнитель их не меняет;
  - `[haiku]` — `implementer` с `model: "haiku"`, тесты и код сам (механическое: аргументы
    CLI, вывод, вариант генератора синтетики, константа этапа, документация команд);
  - `[analyst]` — аналитик (на сервере разработки с `sudo` или на Mac), без агента.
- Задача, не прошедшая ревью, получает новую метку прямо здесь (CLAUDE.md).

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-12), data-model.md, contracts/ обязательны.
- Только синтетические PDF из `tests/synthetic/make_pdfs.py`, создаваемые в фикстурах;
  никакого обращения к реальной папке данных и реальным договорам (CLAUDE.md, принцип I).
  Сами PDF в репозиторий не кладутся.
- Реальной модели поиска нет нигде, кроме `tests/real_model/`. `DOCREADER_FORBID_MODELS=1`
  остаётся в фикстурах; модель подменяется только транспортом (`HashEmbedder`,
  `FailingEmbedder`, `DownEmbedder` из `tests/fakes/embedding.py`). Ни один тест не открывает
  сокет к модели.
- `openai` для модели поиска импортируется только в `src/docreader/embedding.py`
  (для языковой модели — по-прежнему только `llm.py`).
- `passages.py`, `wordforms.py` и правила `indexing.py` (обрезка, состояние) — чистые
  функции без базы, `psycopg` и модели; их модульные тесты не требуют PostgreSQL.
- Текст отрывка в базу не копируется: только `start`, `end_` (data-model.md).
- В причинах состояния, в выводе `index` и в `--json` `index` нет меток, текста договора
  и текста исключений (FR-008, FR-011).
- Сообщения пользователю — на русском, как в contracts/cli.md; код, идентификаторы,
  комментарии — на английском.
- Перед `[X]`: `scripts/check.sh` проходит (тесты, ruff, mypy).

---

## Phase 1: Setup

**Purpose**: pgvector на сервере разработки и в Docker, синтетический договор с нужными
случаями.

- [X] T001 [analyst] Quickstart А0 on the dev server: `sudo apt install postgresql-17-pgvector`; `psql postgresql:///postgres -Atc "SELECT version, trusted FROM pg_available_extension_versions WHERE name = 'vector' ORDER BY 1 DESC LIMIT 1"`; if `trusted = f`, `sudo -u postgres psql -d template1 -c 'CREATE EXTENSION IF NOT EXISTS vector'` (and in `docreader_demo` if it exists); send the version and `trusted` (research R-10). **Done 2026-11-24 on the dev server:** `postgresql-17-pgvector` 0.8.7 installed, `trusted = f`, `CREATE EXTENSION vector` in `template1` by `postgres` (no `docreader_demo` yet); a new database created by the `developer` role gets `vector` 0.8.7
- [X] T002 [opus] In `compose.yaml` replace the `db` image `postgres:17` with `pgvector/pgvector:pg17` (research R-10, plan «Отступления» #6); keep tmpfs, network and healthcheck as they are; `docker compose pull db && docker compose run --rm tests -k migrate` passes on the current schema (0001–0005)
- [X] T003 [P] [haiku] Add `make_passage_contract(path) -> Path` to `tests/synthetic/make_pdfs.py`, built on the helpers of `make_extraction_contract` (do not change existing generators, their pages or `GENERATOR_VERSION`). Pages (logical lines, wrapped by `_wrap_page`): page 1 — «ДОГОВОР ПОДРЯДА», «№ ДП-17/2026», «г. Энск», the preamble of `_PREAMBLE_BASE`; «1. Предмет договора»; «1.1. Подрядчик выполняет работы по ремонту здания.»; «1.1.1. Работы выполняются в два этапа.»; «1.1.2. Не применяется.»; «2. Цена договора»; «Цена определяется сметой и не меняется.» (a section with text after its heading); «2.1. Цена договора составляет 1 200 000 рублей без НДС.»; page 2 — «3. Ответственность»; «3.1. За просрочку Подрядчик уплачивает неустойку 0,1% за каждый день.»; «3.2. Размер неустойки не превышает 10% цены.»; «4. Адреса и реквизиты сторон»; «Заказчик: ООО «Альфа», ИНН 0000000000»; «Подрядчик: ООО «Бета», ИНН 0000000001»; page 3 — «Приложение № 1»; «Смета работ»; «Итого: 999 999 рублей»; «Приложение № 2»; «График работ». Unit test in `tests/unit/test_make_passages.py` (pdfium text of each page holds these lines; 3 pages; all names and numbers fictional). The expected passages of this contract (`PASSAGE_TRUTH`) are not part of this task: they are the expected result of the cutting rule and are written by the main session in T009

---

## Phase 2: Foundational (blocking)

**Purpose**: схема, настройки, константа этапа, интерфейс модели поиска с подделками.

- [X] T004 [opus] Write `src/docreader/migrations/0006_passages.sql` exactly per data-model.md and its tests in `tests/integration/test_migrate.py` (after T001, T002). First line `CREATE EXTENSION IF NOT EXISTS vector`. Table `passage`: `document_id text NOT NULL REFERENCES document (id) ON DELETE CASCADE`; `clause_key text NOT NULL` «не пустой»; `PRIMARY KEY (document_id, clause_key)`; `ordinal integer NOT NULL CHECK (ordinal >= 0)`, `UNIQUE (document_id, ordinal)`; `part text NOT NULL CHECK (part IN ('preamble', 'main', 'tail'))`; `start integer NOT NULL CHECK (start >= 0)`; `end_ integer NOT NULL` with `CHECK (end_ > start)`; `first_page`, `last_page integer NOT NULL` with `1 <= first_page <= last_page`; `label text NOT NULL` «не пустой»; `lemmas text NOT NULL` «не пустой»; `tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', lemmas)) STORED` with a GIN index; `source_text_sha256 char(64) NOT NULL CHECK (source_text_sha256 ~ '^[0-9a-f]{64}$')`; `structure_run_id bigint NOT NULL REFERENCES run (id) ON DELETE RESTRICT`; `run_id bigint NOT NULL REFERENCES run (id) ON DELETE RESTRICT`. Table `passage_vector`: `document_id`, `clause_key text NOT NULL`, `FOREIGN KEY (document_id, clause_key) REFERENCES passage ON DELETE CASCADE`; `model text NOT NULL` «не пустой»; `PRIMARY KEY (document_id, clause_key, model)`; `embedding vector NOT NULL`; `dims integer NOT NULL CHECK (dims > 0 AND dims = vector_dims(embedding))`; `input_chars integer NOT NULL CHECK (input_chars > 0)`; `truncated boolean NOT NULL`; `run_id bigint NOT NULL REFERENCES run (id) ON DELETE RESTRICT`. No foreign key to `clause`, no ANN index. Tests: the migration applies after 0005; each CHECK rejects a bad row; `tsv` of `'неустойка'` matches `to_tsquery('simple', 'неустойка')`; `tsv` of `lemmas = 'дп-17/2026 договор'` matches `plainto_tsquery('simple', 'ДП-17/2026')` and does not match `plainto_tsquery('simple', '17/2026')` (the recorded limitation of U1, research R-5); deleting a document deletes its passages and vectors; deleting a passage deletes its vectors; a vector whose length ≠ `dims` is rejected. If `CREATE EXTENSION` fails for lack of rights, `docreader migrate` raises `EnvironmentProblem` naming `CREATE EXTENSION vector` in `template1` (R-10) — test with a monkeypatched execute
- [X] T005 [P] [opus] `EmbeddingSettings` and section `[embedding]` in `src/docreader/config.py` (research R-9, as `ExtractionSettings`): `base_url = "http://127.0.0.1:8081/v1"` (only loopback, `is_local_model_url`), `model = "bge-m3"`, `timeout_s = 120`, `batch_size = 16`, `max_chars = 16000`; positive integers; unknown key → settings error; `Settings.embedding`. Tests first in `tests/unit/test_config_embedding.py`: defaults; each override; non-loopback address rejected; zero or negative numbers rejected; unknown key rejected
- [X] T006 [P] [haiku] `RunStage.INDEXING = "indexing"` in `src/docreader/stages.py` (the `Stage.INDEXING` row of `stage_status` already exists); unit test that `RunStage.INDEXING.value == Stage.INDEXING.value`
- [X] T007 [opus] Failing unit tests in `tests/unit/test_embedding_guard.py` and the fakes `tests/fakes/embedding.py` (contracts/embedding.md, research R-1, R-2) and fixture `use_embedder(fake)` in `tests/conftest.py` (as `use_model`; patches `embedding.load_embedder` to pass the fake's transport). Fakes: `HashEmbedder(dims=8, served_model="fake-embedder")` — vector of each input from the first `dims` bytes of its SHA-256 mapped to [-1, 1], answers `/v1/embeddings` in OpenAI form, keeps `.inputs` (all texts in order) and `.requests`; `FailingEmbedder(fail_on, kind)` with `kind` in `"http_500"`, `"wrong_count"`, `"connect"`; `DownEmbedder()` — every request `httpx2.ConnectError`. Tests: `DOCREADER_FORBID_MODELS` without a transport → `EnvironmentProblem` «На этой машине модель поиска не запускается (DOCREADER_FORBID_MODELS)» and no client created; non-loopback `base_url` → error; `check()` → `EmbedderInfo(served_model, dims)`; `embed` splits into batches of `batch_size` (`.requests`), keeps input order (fake answers with shuffled `index`), returns vectors of length 1; wrong count or mixed lengths → `EmbeddingRequestError`; HTTP 500 → `EmbeddingRequestError`; connect error and timeout → `ModelUnavailable`; a text longer than `max_chars` → `ValueError` before any request; no exception message contains an input text (marker string); `OPENAI_API_KEY`/`OPENAI_BASE_URL` in the environment change nothing
- [X] T008 [opus] Implement `src/docreader/embedding.py` to make T007 pass (contracts/embedding.md): `EmbedderInfo`, `Embedder.check()`, `Embedder.embed(texts)`, `load_embedder(settings, transport=None)`, `EmbeddingRequestError`; `openai.OpenAI(base_url=…, api_key="local", max_retries=0, timeout=timeout_s, http_client=httpx2.Client(transport=…))`; L2-normalize in code. Move `ModelUnavailable` to `src/docreader/errors.py` and import it in `llm.py` and `embedding.py` (no behaviour change; the tests of feature 05 keep passing unchanged)

**Checkpoint**: схема с pgvector, настройки и модель поиска только через `embedding.py`.

---

## Phase 3: User Story 1 — Нарезать договор на отрывки с метками (P1)

**Goal**: правило нарезки и метки как чистые функции (R-3, R-4).

**Independent Test**: на записях разбора синтетического договора — число отрывков, их тексты
по месту, метки, покрытие SC-001.

- [X] T009 [US1] [opus] Failing unit tests in `tests/unit/test_passages.py` (research R-3, R-4) on hand-built text and record lists (`kind`, `key`, `depth`, `start`, `end`, `section_number`, `section_title`) and `tail_end`: `cut(text, records, tail_end) -> list[PassageSpan(key, part, start, end)]`: one passage per preamble, clause, subclause; a section with only its heading line — none; a section with text after the heading — the text after the first line only; the tail — up to `tail_end` (the first «Приложение» line), the whole tail when `tail_end` is its end; boundaries without leading and trailing whitespace; an empty record after trimming — none; `part` is `preamble`/`main`/`tail`; order by `start`. `label(document_id, record) -> str` — every row of the R-4 table, an empty section title («раздел 5»), a clause without section. `coverage(text, records, tail_end, spans) -> (uncovered, doubled)` — counts of non-whitespace characters outside every passage and inside two, both 0 for `cut`'s result, and > 0 for a hand-broken list. Plus `PASSAGE_TRUTH: dict[str, str]` in `tests/synthetic/make_pdfs.py` next to `make_passage_contract` (T003) — clause key → expected passage text, written by hand by the main session from the lines of T003 (keys `преамбула`, `1.1`, `1.1.1`, `1.1.2`, `2`, `2.1`, `3.1`, `3.2`, `реквизиты`; no `1`, `3`, `4`; `2` — only the line after the heading; `реквизиты` — from the heading line «4. Адреса и реквизиты сторон» to the last line before «Приложение № 1»), and one integration test in `tests/integration/test_passages_contract.py` on `make_passage_contract`: after `add`, `read`, `parse` in a temporary database, `cut` over its records gives exactly `PASSAGE_TRUTH` (key → `text[start:end]`) and coverage 0/0
- [X] T010 [US1] [opus] Implement `src/docreader/passages.py` to make T009 pass: `PassageSpan`, `cut`, `label`, `coverage`; the tail boundary comes from the caller (`extraction_text.shown_end`), not recomputed here

**Checkpoint**: отрывки и метки на строках, без базы и модели.

---

## Phase 4: User Story 2 — Построить индексы по словам и по смыслу (P1) 🎯 MVP

**Goal**: этап `index` — отрывки, словарные формы, векторы, запись, состояния (R-5–R-8).

**Independent Test**: два синтетических договора с `HashEmbedder`: в каждом индексе
столько записей, сколько отрывков; повторный запуск ничего не добавляет.

- [X] T011 [P] [US2] [opus] Failing unit tests in `tests/unit/test_wordforms.py` (research R-5): `lemmatize("неустойки неустойку")` → `"неустойка неустойка"`; «ДП-17/2026», «5.2.1» — words with a digit kept as written; «0,1%» → `"0 1"` (a comma and «%» are separators, R-5); «Ёлка» → «елка»; upper case → lower; punctuation and quotes dropped; empty text → `""`; one analyzer per process (`wordforms.analyzer()` is cached and `values.py` uses it)
- [X] T012 [US2] [sonnet] Implement `src/docreader/wordforms.py` to make T011 pass (`analyzer()` cached, `lemmatize`); `src/docreader/values.py` takes its analyzer from `wordforms.analyzer()` without changing behaviour (feature 05 tests unchanged)
- [X] T013 [P] [US2] [opus] Failing unit tests in `tests/unit/test_indexing_rules.py` (research R-6, R-8): `embedding_input(label, text, max_chars) -> (input, truncated)` — `label + "\n" + text`; exactly `max_chars` → not truncated; one more character → first `max_chars` characters, truncated; `index_state(passage_keys, truncated_keys, document_id) -> (State, reason)`: none truncated → `done`, None; truncated → `needs_review` «отрывок длиннее предела модели: D-0001/5.2, D-0001/реквизиты» in passage order, more than 5 → first 5 and «и ещё N»; no passages → `needs_review` «нет отрывков»; the reason never holds a label or a text (marker)
- [X] T014 [US2] [opus] Implement the rules of T013 in `src/docreader/indexing.py` (pure functions `embedding_input`, `index_state`; module docstring per research R-8)
- [X] T015 [US2] [opus] The write of passages and vectors — tests and code (plan.md «Критические части»). In `src/docreader/indexing.py`: `store_document(conn, doc_id, passages: Sequence[PassageRow], vectors: Sequence[VectorRow], state, reason, run_id) -> None` — one transaction: `stages.lock` → `DELETE FROM passage WHERE document_id = …` → inserts (vectors as `'[…]'::vector` text) → `stages.set_state(…, Stage.INDEXING, …)`. Integration tests in `tests/integration/test_index_store.py` on a document added, read and parsed in a fixture, with hand-built rows (no model): rows, state and reason written; a second call replaces (no duplicates); a vector row for an unknown passage or with `dims` ≠ its length → the whole call rolls back, the previous rows and state stay; rows of other documents untouched. Also here, tests and code (R-7 is a decision rule, plan.md «Критические части»): `select_documents(conn, ids, all_) -> tuple[list[str], list[SkippedDocument]]` — available documents (`structure` in `done`/`needs_review`, clause records exist, every `clause.source_text_sha256` equal to `document_text.text_sha256`); without ids and `--all` — those of them with `indexing` in `pending`/`failed` or `passage.structure_run_id` ≠ the `clause.run_id`; with ids or `--all` an unavailable document is skipped with the reason «не разобран — выполните docreader parse D-000N» or «разбор устарел — выполните docreader parse D-000N»; and `passages_current(conn, doc_id) -> bool` — every passage has `source_text_sha256` equal to the current `document_text.text_sha256` and `structure_run_id` equal to the `clause.run_id`. Tests in the same file on fixture documents: each state of `structure` and `indexing`, a text changed after `parse`, a second `parse`, no passages
- [X] T016 [US2] [opus] Failing integration tests in `tests/integration/test_index.py` through the CLI (`index`, `--json`) on `make_passage_contract` and `make_extraction_contract(variant="base")` (added, read and parsed in fixtures; `use_embedder(HashEmbedder())`). `index` → `passage` rows equal `PASSAGE_TRUTH` for the passage contract (`text[start:end]`), pages from `text_span`, labels per R-4, `lemmas` = `lemmatize(label + "\n" + text)`, one `passage_vector` per passage with `model = "bge-m3"`, `dims = 8`, length 1, `truncated = false`; `HashEmbedder.inputs` = `label + "\n" + text` of each passage in order; `tsv @@ to_tsquery('simple', 'неустойка')` finds `3.1` and `3.2`; the `lemmas` of `преамбула` hold `ДП-17/2026` as one word and `tsv @@ plainto_tsquery('simple', 'ДП-17/2026')` finds `преамбула` (FR-004, U1); one `run` with `stage = 'indexing'`, `model`, `settings` with `served_model` and `dims`; state `done`; `passages.coverage` is 0/0 for both contracts (R-3 invariant, SC-001). Selection: no arguments → `pending`/`failed` only; `--all`; explicit ids; `--all` with ids → code 1; not parsed → «пропущен» «не разобран — выполните docreader parse D-000N»; parse on an older text → «разбор устарел — …»; nothing to do → the line of contracts/cli.md, code 0; a second `parse` of the same document → `index` without arguments takes it again (R-7). A second `index --all` → the same counts (SC-003). `max_chars` set low in `settings.toml` → `needs_review` with the reason of R-8 and `truncated = true`. `FailingEmbedder("…", "http_500")` on one document → `failed` «ошибка построения векторов: EmbeddingRequestError», its old rows unchanged, the next document indexed. `DownEmbedder` → code 2 «Модель поиска недоступна по адресу …», no state changed; `FailingEmbedder(…, "connect")` on the second document → the first written, the second untouched, code 2, `stopped` in `--json`. `DOCREADER_FORBID_MODELS` without a fake → code 2 with the message of contracts/cli.md. `docreader remove` of an indexed document → no `passage` or `passage_vector` rows left (US2-5). Text and `--json` output hold no label and no line of the synthetic contract
- [X] T017 [US2] [sonnet] Implement the rest of `src/docreader/indexing.py` to make the stage part of T016 pass (research R-7, R-8), structured like `src/docreader/extraction.py`: the documents come from `select_documents` of T015 (called as is, not changed); `load_embedder` and `check()` before the first document; per document: load text, records, spans; `extraction_text.shown_end` for the tail; `passages.cut`, `passages.label`, `wordforms.lemmatize`, `embedding_input`; `embed` outside any transaction (measure `seconds`); `index_state`; then `store_document` of T015 (called as is, not changed); `EmbeddingRequestError` → `failed` «ошибка построения векторов: <type>», any other exception of one document → `failed` «ошибка индексации: <type>» (no message), old rows kept; `ModelUnavailable` → stop, return with `stopped`; `KeyboardInterrupt` → `interrupted`. Dataclasses `IndexedDocument`, `SkippedDocument`, `IndexRun` with `to_json()` per contracts/cli.md
- [X] T018 [US2] [haiku] Subcommand `index [ID…] [--all] [--label МЕТКА] [--json]` in `src/docreader/cli.py` and its text and JSON output in `src/docreader/render.py` exactly as contracts/cli.md; exit codes 0/1/2/130; unit tests in `tests/unit/test_render_indexing.py` (each line kind, the totals line, `--json` keys)

**Checkpoint**: `index` целиком на поддельной модели; Б0–Б4 на Mac можно запускать.

---

## Phase 5: User Story 3 — Посмотреть отрывок (P2)

**Goal**: `passage D-0001/5.2` (FR-012).

**Independent Test**: после `index` синтетического договора открыть `D-0001/3.1` и сверить
с записью разбора.

- [X] T019 [US3] [opus] Failing integration tests in `tests/integration/test_passage.py` after `index` on `make_passage_contract` (`HashEmbedder`): text output and `--json` exactly as contracts/cli.md for `D-0001/3.1` (pages, part, label, «В индексе по словам: да», model and dims, text = `PASSAGE_TRUTH["3.1"]`); a truncated passage shows «(вход обрезан до N знаков)»; `D-0001/1` (heading only) → «Нет отрывка D-0001/1: у записи нет текста, кроме заголовка», code 1; `D-0001/9.9` → «Нет записи D-0001/9.9», code 1; bad id form → message with an example, code 1; not indexed → «Отрывков нет: выполните docreader index D-0001», code 1; after a text change or a second `parse` → «Отрывки устарели: текст или разбор изменились — выполните docreader index D-0001», code 1
- [X] T020 [US3] [sonnet] Implement `src/docreader/passageview.py` to make the loader part of T019 pass: `load_passage(conn, clause_id) -> PassageView` or `UserError` (unknown document, not indexed, heading-only record, unknown record, stale — by `indexing.passages_current` of T015, called as is); text from `document_text.text[start:end_]`
- [X] T021 [US3] [haiku] Subcommand `passage ID [--json]` in `src/docreader/cli.py` and its output in `src/docreader/render.py` exactly as contracts/cli.md (after T018: same files); unit tests in `tests/unit/test_render_indexing.py`

**Checkpoint**: все три истории работают на поддельной модели.

---

## Phase 6: Polish & Cross-Cutting

- [X] T022 [P] [opus] `tests/real_model/test_embedding_server.py` (`@pytest.mark.real_model`, Mac only; contracts/embedding.md level 3): `check()` → dims 1024; the same text twice → the same vector; length 1; a batch of 16 synthetic strings → 16 vectors in input order; one synthetic string of exactly `max_chars` (16 000) characters made of digit groups and requisites-like words (the densest input in tokens) is embedded without an error — `max_chars` really fits the 8192 tokens of the model (R-6; if it fails, the default is lowered in T028); with `base_url` pointing at a closed port → `ModelUnavailable`
- [X] T023 [P] [sonnet] `scripts/quickstart_passages.py` and `tests/unit/test_quickstart_passages.py` (quickstart Б4; prints counts and shares only — no text, labels, names or file names): documents by `indexing` state; passages by part; word-index and vector entries; SC-001 — `passages.coverage` over every indexed document (uncovered and doubled characters, documents with either); SC-002 — every passage's `first_page`/`last_page` re-derived from `text_span` and `end_ <= len(text)`, share passing; truncated passages; time total and per document (median, max) from the `--json` report if given; `--compare OTHER.json` — whether the passage and entry counts per document changed (SC-003). The main session writes the tests first; unit tests on a synthetic database fixture
- [X] T024 [opus] Run quickstart А2 on the dev server (throwaway data dir, `docreader_demo`): `index` stops with code 2 under `DOCREADER_FORBID_MODELS`, `passage` says not indexed; fix differences test-first; then `docker compose build tests lint`, `docker compose run --rm tests` and `docker compose run --rm lint`
- [X] T025 [P] [haiku] Document the new commands in `CLAUDE.md` «Commands» (`docreader index [ID…] [--all]`, `docreader passage D-0001/5.2`; output of `index` may be sent to the agent, output of `passage` on real contracts may not; `[embedding]` in `settings.toml`, the model server runs only on the Mac) and pgvector in the setup notes (`postgresql-17-pgvector` on the dev server, `brew install pgvector` on the Mac)
- [X] T026 [analyst] Quickstart Б0–Б1 on the Mac: pgvector, llama.cpp, BGE-M3 GGUF, `[embedding]` in `settings.toml`, `docreader migrate`, `uv run pytest -m real_model tests/real_model/test_embedding_server.py`; send the versions, `trusted`, the weights file and its quantization, and the pytest output
- [X] T027 [analyst] Quickstart Б2–Б3: one contract — `index D-… --json` with `/usr/bin/time -l`; the three models together (the reranker weights BGE Reranker v2-m3 in GGUF are downloaded beforehand, outside the repository) — memory per process, memory pressure, swap, `extract D-0001` time; send the numbers only
- [X] T028 [opus] Write А0 (T001: version, `trusted` or template) and Б0–Б3 into `docs/tech-context.md` («Запуск PostgreSQL» — pgvector, replacing «[проверить]»; «Поиск по смыслу» — server, weights, replacing «[проверить]»; «Что проверить в первый день», п. 3 — the memory result: together or one at a time) and research.md R-1, R-10, R-12; adjust `[embedding]` defaults only if a number requires it
- [X] T029 [analyst] Quickstart Б4: `index --all`, `scripts/quickstart_passages.py --report`, the rerun with `--compare`; send the `index` summary and the script output only (no `passage` output)
- [X] T030 [opus] Write the Б4 results into `docs/tech-context.md` («Нарезка и индексы (фича 07), замер …»: time for the set, passages by part, SC-001…SC-004); a systematic error from Б4 → a synthetic case in `tests/synthetic/` and a failing test first (CLAUDE.md «Delivery»)

---

## Dependencies & Execution Order

### Phase dependencies

- Phase 1 — T001 (analyst, sudo) before any integration test of this feature; T002 after T001; T003 independent, needed by T009, T016, T019.
- Phase 2 — T004 after T001, T002; T005 ‖ T006; T007 after T005; T008 after T007.
- US1 (T009–T010) — T009 after T003 (its contract test runs `parse` in a temporary database); T010 after T009.
- US2 (T011–T018) — T011 ‖ T013; T012 after T011; T014 after T013; T015 after T004, T006, T014; T016 after T008, T010, T012, T015; T017 after T016; T018 after T017.
- US3 (T019–T021) — after T017; T020 after T019; T021 after T018 and T020.
- Polish — T022 after T008; T023 after T017; T024 after T021; T025 after T021; T026 after T022 and T024 (branch pushed); T027 after T026; T028 after T027; T029 after T023 and T026; T030 after T029.

### Same-file sequencing (no [P] between these)

- `src/docreader/indexing.py`: T014 → T015 → T017.
- `src/docreader/cli.py`, `src/docreader/render.py`, `tests/unit/test_render_indexing.py`: T018 → T021.
- `tests/conftest.py`: T007 only.
- `src/docreader/llm.py`, `src/docreader/errors.py`: T008 only.
- `src/docreader/values.py`: T012 only.

## Parallel Examples

```text
Phase 1: T003 (generator, haiku) while the analyst does T001 and the main session T002.
Phase 2: T005 (settings, main session) ‖ T006 (stage constant, haiku).
US2: T011 ‖ T013 — the main session writes both test files; then T012 (wordforms, sonnet) while the main session does T014 and T015.
Polish: T022 (main session) ‖ T023 (quickstart script, sonnet) ‖ T025 (docs, haiku).
```

## Implementation Strategy

### MVP first

Phase 1–2 + US1 + US2 (T001–T018): `index` целиком на поддельной модели — отрывки по записям
разбора с метками, словарные формы, векторы, состояния, вывод без текста. Этого достаточно
для Б0–Б4 на Mac и для того, чтобы фича 08 искала по `passage` и `passage_vector`. US3 даёт
просмотр отрывка для проверки нарезки и отладки поиска.

### Incremental delivery

1. Phase 1–2 → pgvector, схема, настройки, модель поиска только через `embedding.py`.
2. US1 → нарезка и метки на строках (без модели и базы).
3. US2 → `index` на `HashEmbedder`; Б0–Б4 на Mac можно запускать.
4. US3 → `passage`.
5. Polish → документы, замеры Б, итоги в tech-context.
