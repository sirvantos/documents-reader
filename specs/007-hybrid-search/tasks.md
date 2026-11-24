---
description: "Task list for feature 08 (branch 007): hybrid search with the reranker, minimal version"
---

# Tasks: Гибридный поиск с реранкером (минимальная версия)

**Input**: Design documents from `specs/007-hybrid-search/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/cli.md](contracts/cli.md),
[contracts/reranker.md](contracts/reranker.md), [quickstart.md](quickstart.md)

**Tests**: требуются — plan.md, раздел «Тесты», SC-001. Тесты пишутся до кода и должны
падать до реализации по ожидаемой причине.

**Organization**: фазы по историям spec.md — US1 (найти отрывки, P1), US2 (искать в одном
договоре, P1), US3 (реранкер, P1), US4 (замер реранкера, P2). Правила решения
и интерфейс реранкера — в Phase 2: они нужны нескольким историям.

## Format: `[ID] [P?] [Story?] [model] Description`

- **[P]**: можно параллельно (разные файлы, нет зависимости от незавершённых задач)
- **[Story]**: история spec.md (US1…US4)
- **[model]** (CLAUDE.md, «Model routing»; аналитик может поменять до начала implement):
  - `[opus]` — главная сессия сама, тесты и код (критичное по plan.md «Критические
    части»: BM25, служебные слова, слияние, порядок равных, правило FR-014; выбор
    области поиска — актуальные отрывки, договор, устаревшие договоры, векторы
    выбранной модели; интерфейс реранкера с подделками и защиты, раздел `[reranker]`);
  - `[sonnet]` — `implementer` на своей модели; тесты к задаче пишет главная сессия
    заранее отдельной задачей `[opus]`, исполнитель их не меняет;
  - `[haiku]` — `implementer` с `model: "haiku"`, тесты и код сам (механическое: генератор
    синтетики, вывод, аргументы CLI, документация команд);
  - `[analyst]` — аналитик на Mac, без агента.
- Задача, не прошедшая ревью, получает новую метку прямо здесь (CLAUDE.md).

## Общие правила для всех задач

- Решения plan.md, research.md (R-1…R-12), data-model.md, contracts/ обязательны.
- Только синтетические PDF из `tests/synthetic/make_pdfs.py`, создаваемые в фикстурах;
  никакого обращения к реальной папке данных и реальным договорам (CLAUDE.md, принцип I).
- Реальных моделей нет нигде, кроме `tests/real_model/`. `DOCREADER_FORBID_MODELS=1`
  остаётся в фикстурах; модели подменяются только транспортом (`TopicEmbedder`,
  `HashEmbedder`, `TableReranker`, `FailingReranker`, `DownReranker`). Ни один тест
  не открывает сокет.
- HTTP к реранкеру — только в `src/docreader/reranker.py`; `openai` для модели поиска —
  только в `embedding.py`.
- `ranking.py` и `wordforms.query_terms` — чистые функции без базы, `psycopg` и моделей;
  их модульные тесты не требуют PostgreSQL.
- Поиск ничего не пишет в базу; миграции нет (data-model.md).
- В сообщениях об ошибках и предупреждениях поиска, в выводе скрипта замера нет текста
  договоров, запроса и вопросов (FR-012, FR-013).
- Сообщения пользователю — на русском, как в contracts/; код, идентификаторы,
  комментарии — на английском.
- Перед `[X]`: `scripts/check.sh` проходит (тесты, ruff, mypy).

---

## Phase 1: Setup

**Purpose**: синтетические договоры для поиска.

- [ ] T001 [P] [haiku] Add `make_search_contracts(directory) -> list[Path]` to `tests/synthetic/make_pdfs.py`, built on the helpers of `make_passage_contract` (`_PREAMBLE_BASE`, `_wrap_page`; do not change existing generators, their pages or `GENERATOR_VERSION`). Three one- or two-page contracts, files `search-a.pdf`, `search-b.pdf`, `search-c.pdf`, returned in this order (they become D-0001…D-0003 when added in this order). All three: «ДОГОВОР ПОСТАВКИ», the preamble, «2. Цена и порядок расчётов», «2.2. Срок оплаты товара составляет 30 дней с даты поставки.» (the same typical clause, word for word; it holds the words «срок» and «оплата» and the marker «оплат» of the `payment` topic of T008, so the query «срок оплаты» finds it by words and by meaning), «5. Адреса и реквизиты сторон» with fictional parties and ИНН 0000000000/0000000001. Only in A: «№ ДП-17/2026» on the title line; «1. Предмет договора»; «1.1. Поставщик передаёт товар по договору № ДП-17/2026.»; «2.1. Цена договора составляет 500 000 рублей.»; «3. Ответственность»; «3.1. За просрочку поставки Поставщик уплачивает неустойку 0,1% за каждый день.»; «4. Гарантия»; «4.1. Гарантийный срок составляет 12 месяцев.». Only in B: «1. Предмет договора»; «1.1. Поставщик поставляет оборудование.»; «2.3. Покупатель перечисляет денежные средства на счёт Поставщика.»; «3. Порядок приёмки»; «3.1. Приёмка проводится на складе Покупателя.». Only in C: «1. Предмет договора»; «1.1. Поставщик поставляет запасные части.»; «3. Форс-мажор»; «3.1. Стороны освобождаются от ответственности при обстоятельствах непреодолимой силы.». Unit test in `tests/unit/test_make_search.py`: three files, pdfium text of each holds its lines, clause 2.2 identical in all three, all names and numbers fictional

---

## Phase 2: Foundational (blocking)

**Purpose**: настройки, слова запроса, формулы ранжирования, клиент реранкера и подделки
обеих моделей.

- [ ] T002 [P] [opus] `SearchSettings` (`[search]`) and `RerankerSettings` (`[reranker]`) in `src/docreader/config.py`, fields `Settings.search`, `Settings.reranker`, parsed like `[embedding]` (unknown key — error naming it). Exactly data-model.md: `candidates` int 30 «1…500»; `rrf_k` int 60 «1…1000»; `rerank_candidates` int 30 «1…200»; `results` int 8 «1…200, не больше `rerank_candidates`»; `enabled` bool true; `base_url` «только эта машина (`is_local_model_url`, принцип I)», default `http://127.0.0.1:8082/v1`; `model` «не пустая», default `bge-reranker-v2-m3`; `timeout_s` int 60 «1…3600»; `max_chars` int 16000 «1…1 000 000». Tests first in `tests/unit/test_config_search.py`: defaults, each bound, `results > rerank_candidates`, non-local `base_url`, unknown key, `enabled = "yes"` (not bool) rejected
- [ ] T003 [P] [opus] `query_terms(query) -> list[str]` in `src/docreader/wordforms.py` (research R-1, R-2): the words of `lemmatize(query)` in lower case, in order, without repeats, without words whose first `pymorphy3` parse has POS `PREP`, `CONJ`, `PRCL` or `INTJ`; words with a digit are kept as written, lower-cased. Tests first in `tests/unit/test_query_terms.py`: «неустойки» → «неустойка»; «ДП-17/2026» → «дп-17/2026»; «и в на по» → `[]`; «срок оплаты по договору» → «срок», «оплата», «договор»; repeats removed; «ё» folded; empty and blank → `[]`
- [ ] T004 [P] [opus] `src/docreader/ranking.py` (research R-1, R-4), pure functions over plain values: `PassageKey = tuple[str, int]` (document id, ordinal) as the tie order; `bm25(terms, docs: Sequence[tuple[PassageKey, list[str]]], k1=1.2, b=0.75) -> list[tuple[PassageKey, float]]` — scores > 0 only, sorted by score desc then key; statistics over `docs` (count, mean length, document frequency per term); IDF `ln(1 + (N − df + 0.5)/(df + 0.5))`; `rrf(lists: Sequence[Sequence[PassageKey]], k) -> list[tuple[PassageKey, float, list[int | None]]]` — score `Σ 1/(k + place)`, places from 1, `None` where a list misses the key, sorted by score desc then key. Tests first in `tests/unit/test_ranking.py`: rare word outweighs common; same word in a longer passage scores lower; a digit word matches only whole («дп-17/2026» vs «дп»); ties by document then ordinal; no terms → `[]`; RRF: found by both above found by one at the same place; `k` changes the scores; places reported per list
- [ ] T005 [opus] `src/docreader/reranker.py` exactly per contracts/reranker.md: `RerankRequestError`, `RerankerInfo`, `Reranker.check`, `Reranker.score`, `rerank_input`, `load_reranker` (FORBID without transport → `EnvironmentProblem` before the client; non-local address → `EnvironmentProblem`; `httpx2.Client(base_url, timeout, transport, trust_env=False)`; no retries); every error of the contract table with its exception and a message without query or document text. Fakes `tests/fakes/reranker.py` (`TableReranker(scores, default=0.0)` with `.requests`, `FailingReranker(kind)` for `http_500`, `wrong_count`, `bad_index`, `not_json`, `timeout`, `connect`, `DownReranker()`) and the fixture `use_reranker` in `tests/conftest.py` (like `use_embedder`). Tests first in `tests/unit/test_reranker_guard.py`: each guard and each error row; scores returned in document order for an answer sorted by score; empty documents → `[]` without a request; `rerank_input` cuts the query to `max_chars // 4` and the document to `max_chars − len(query)`, flag set; no message contains the probe query text
- [ ] T006 [P] [opus] `TopicEmbedder(topics: dict[str, list[str]], dims=16)` in `tests/fakes/embedding.py` per contracts/reranker.md (axis per topic, a 1 on each axis whose marker substring occurs in the lower-cased text, plus `0.01 * hash_vector(text)`, normalised; same `/v1/embeddings` protocol and `.inputs` as `HashEmbedder`). Unit test in `tests/unit/test_fake_embedders.py`: two texts sharing a topic are closer than texts without it; the same text → the same vector; text without topics → a unit vector

**Checkpoint**: правила и клиенты готовы; поиск ещё не собран.

---

## Phase 3: User Story 1 — Найти отрывки по запросу (Priority: P1) 🎯 MVP

**Goal**: `docreader search "ЗАПРОС"` и `search.search(...)` по всем договорам: слова +
смысл + слияние, места по способам, предупреждения; реранкер в этой фазе выключен
(`--no-rerank` / `rerank=False`).

**Independent Test**: синтетика T001 проиндексирована с `TopicEmbedder`; поиск с
выключенным реранкером даёт ожидаемые состав и порядок.

- [ ] T007 [US1] [opus] Scope queries in `src/docreader/search.py` (research R-3, R-6): `current_passages_sql` — the condition «актуальный отрывок» of data-model.md (`p.source_text_sha256 = t.text_sha256` and `p.structure_run_id` = the run of the document's current clause records), written once and used by both candidate queries; `stale_documents(conn) -> int` — registry documents without current passages; `ensure_searchable(conn, settings, document_id)` — no current passages at all → `UserError` «Индексы пусты — выполните docreader index»; no vector of `[embedding] model` among current passages → `EnvironmentProblem` with the message of contracts/cli.md; `word_corpus(conn, document_id) -> list[(PassageKey, list[str])]` (lower-cased `lemmas` split on spaces); `vector_candidates(conn, model, vector, n, document_id)` — the SQL of R-3 with the tie order. With `document_id` (research R-5) `ensure_searchable` first checks the document, with the messages of contracts/cli.md: not in the registry → `UserError` «Нет документа D-…»; no passages → `UserError` «Отрывков нет: …»; passages not current → `UserError` «Отрывки устарели: …». Integration tests first in `tests/integration/test_search_scope.py`: a document re-parsed after `index` is excluded and counted; a document never indexed is counted; changing `[embedding] model` → the error; empty indexes → the error; the three document errors; `word_corpus` and `vector_candidates` with `document_id` return passages of that document only
- [ ] T008 [US1] [opus] Failing tests of US1 in `tests/integration/test_search.py` (CLI `docreader search … --no-rerank --json` and `search.search(..., rerank=False)`; T001 contracts added → read → parse → `index` with `use_embedder(TopicEmbedder({"payment": ["оплат", "плат", "перечисл", "денежн", "деньг"], "penalty": ["неустойк", "штраф", "пен"], "warranty": ["гарант"]}))`): «ДП-17/2026» → D-0001/1.1 with `word_place` 1 and among the first two hits (the preamble of D-0001 holds the number too; which of the two is first depends on the fake vectors); «куда переводить деньги» → D-0002/2.3 among results with `word_place` null and `vector_place` set; «неустойки» → D-0001/3.1 found by words; a passage found by both ranks above one found by one at the same place; `--json` keys and `place` order per contracts/cli.md; the same query twice → the same list (SC-004); edge cases: empty query → code 1 before any model request (`TopicEmbedder.inputs` empty); «и в на по» → `word_candidates` 0 and the warning; a query longer than `[embedding] max_chars` → cut and warned; («Ничего не найдено» has no case here: the search by meaning returns the nearest passages whenever the indexes are not empty, so the message is tested on a hand-built empty result in T010); stale documents warned and absent from hits; FORBID without the fake → code 2; no error text holds the query
- [ ] T009 [US1] [sonnet] `search.search(conn, settings, query, *, document_id=None, rerank=None, results=None, embedder=None, reranker=None) -> SearchResult` and the data classes `Candidate`, `Hit`, `SearchResult` of data-model.md in `src/docreader/search.py`, assembled from T003, T004, T007 (rerank path left for T015: `rerank=True` raises `NotImplementedError` until then). Order of research R-10: empty query → `ensure_searchable` → `embedder.check()` → words (`query_terms`, `bm25` over `word_corpus`, first `candidates`) → vector of the query (cut to `max_chars`, warning) → `vector_candidates` → `rrf` → first `results` → texts and labels from `passage` and `document_text`. `embedder` / `reranker` — clients already loaded by the caller (the measurement script, feature 09); `None` → loaded from the settings; `check()` runs in both cases. `seconds` (`time.perf_counter`) excludes model checks. Make T008 pass without editing it
- [ ] T010 [US1] [haiku] Output of `search` in `src/docreader/render.py`: text form and `--json` exactly per contracts/cli.md (header line, `!` warning lines, numbered hits with clause id, pages, places «слова N, смысл —, слияние N», label, indented text; «Ничего не найдено»); tests in `tests/unit/test_render_search.py` on hand-built `SearchResult` values (the data classes of T009)
- [ ] T011 [US1] [haiku] Subcommand `search` in `src/docreader/cli.py`: positional `query`, `--no-rerank`, `--results N` (1…`rerank_candidates`, else code 1 with «--results: целое от 1 до N»), `--json`; calls `search.search` and `render`; `--document` comes in T013. Extend the existing CLI argument tests for parsing only

**Checkpoint**: поиск по всем договорам без реранкера работает на синтетике.

---

## Phase 4: User Story 2 — Искать в одном договоре (Priority: P1)

**Goal**: `--document D-…` ограничивает оба способа и реранкер одним договором.

**Independent Test**: один запрос с ограничением и без на трёх договорах с одинаковым
пунктом 2.2.

- [ ] T012 [US2] [opus] Failing tests of US2 in `tests/integration/test_search.py` (all with `--no-rerank` / `rerank=False`, as in T008: the rerank path comes in T015): «срок оплаты» without `--document` → D-0001/2.2, D-0002/2.2, D-0003/2.2 all among the first three; with `--document D-0002` → every hit from D-0002 (SC-002) and BM25 statistics over D-0002 only; `--document D-0003 --results 30` → every passage of D-0003 once, fewer than 30 (fewer candidates than results — all are returned); `--document D-0099` → code 1 «Нет документа D-0099 (список: docreader list)»; a registered document without passages → code 1 «Отрывков нет: выполните docreader index D-…»; stale passages of that document → code 1 «Отрывки устарели: …»; in none of these cases is a model called
- [ ] T013 [US2] [sonnet] `document_id` in `search.search`: pass it to the scope functions of T007 (`ensure_searchable`, `word_corpus`, `vector_candidates` — the document checks and the condition in both candidate queries are already there; do not change them) so that the checks run before any model is called, and `--document` in `src/docreader/cli.py`; make T012 pass without editing it

**Checkpoint**: поиск в одном договоре.

---

## Phase 5: User Story 3 — Пересортировать кандидатов реранкером (Priority: P1)

**Goal**: реранкер включён по умолчанию, `--no-rerank` выключает; включённый
и недоступный — остановка.

**Independent Test**: один запрос с `TableReranker` и без него; порядок по таблице.

- [ ] T014 [US3] [opus] Failing tests of US3 in `tests/integration/test_search.py` with `use_reranker`: `TableReranker({"перечисл": 9.0, "30 дней": 5.0})` → in D-0002 «срок оплаты» puts 2.3 first, `rerank_score` and `fused_place` in `--json`, `place` = order by score, ties by `fused_place`; the reranker received exactly the first `rerank_candidates` fused passages as `label + "\n" + text`; `--no-rerank` → `TableReranker.requests` empty and order = fusion; default (`[reranker] enabled = true`) uses it; `enabled = false` in `settings.toml` → not used; a query longer than `[reranker] max_chars // 4` (and shorter than `[embedding] max_chars`) → the warning about the cut query; `DownReranker` → code 2 with the contract message and no hit line; each `FailingReranker` kind → code 2, no hit line (FR-005); FORBID with the reranker on and no fake → code 2 «На этой машине реранкер не запускается (DOCREADER_FORBID_MODELS)» and the search model was not asked to embed the query (checks before search, FR-009)
- [ ] T015 [US3] [sonnet] Rerank path of `search.search` (research R-7, R-10): `rerank` None → `settings.reranker.enabled`; `reranker.load_reranker` and `check()` after `embedder.check()` and before any search; first `rerank_candidates` fused candidates → `rerank_input` → `score` → order by score desc, ties by `fused_place`; first `results`; a query cut by `rerank_input` → warning; any `RerankRequestError` → `EnvironmentProblem` «Реранкер ответил не по форме: … — поиск остановлен» (code 2); `reranker_model` from `check()`. Score in the text output of `render.py` («оценка 7.312») and the header «реранкер bge-reranker-v2-m3». Make T014 pass without editing it
- [ ] T016 [P] [US3] [opus] Level 3 test `tests/real_model/test_reranker_server.py` (`pytest.mark.real_model`, Mac only) per contracts/reranker.md: `check()` answers with a non-empty `served_model`; n scores for n documents in document order; «срок оплаты»: «оплата в течение 30 дней» scores above «гарантийный срок 12 месяцев»; `base_url = http://127.0.0.1:1/v1` → `ModelUnavailable`. Excluded by default like the other `real_model` tests

**Checkpoint**: поиск целиком: слова + смысл + слияние + реранкер.

---

## Phase 6: User Story 4 — Замерить реранкер на вопросах аналитика (Priority: P2)

**Goal**: скрипт замера с правилом FR-014; вывод только числа.

**Independent Test**: тестовый набор на синтетике с подделками — три вопроса и один
с ошибкой в наборе.

- [ ] T017 [US4] [opus] `decide(off: VariantStats, on: VariantStats, limit_s=10.0) -> tuple[str, str]` and `VariantStats(questions, top1, top5, median_s, max_s)` in `src/docreader/ranking.py` — the rule of data-model.md / FR-014: `keep` if `top5(on) > top5(off)`, or `top5` equal and `top1(on) > top1(off)`, and in both cases `median_s(on) ≤ limit_s`; otherwise `disable`; the reason names the numbers («в первых пяти 16 против 14, медиана 1,60 с ≤ 10 с» / «медленно: медиана 10,01 с > 10 с» / «без улучшения»); `questions == 0` → `disable` «нет вопросов без ошибок». Tests first in `tests/unit/test_ranking.py`: each branch, median exactly 10.0 and 10.01, equal top5 with better and worse top1
- [ ] T018 [US4] [opus] Failing tests of the measurement script: `tests/synthetic/search_questions.toml` (four questions on T001 contracts: «Какой срок оплаты?» → `D-0002/2.2`; «Куда переводить деньги?» → `D-0002/2.3`; «Какая неустойка за просрочку?» → `D-0001/3.1`; one broken: `answer = "D-0001/99.1"`) and `tests/unit/test_quickstart_search.py` (pure parts: reading the TOML — a question with a missing or empty `text`, a missing `answer` or a bad id → that question is «ошибка в наборе» and the rest are read (research R-11); no file, not TOML, no question at all → code 1 per contracts/cli.md; places, shares, median; text and JSON summary) plus one integration case in `tests/integration/test_search.py` running `scripts/quickstart_search.py --questions …` on a copy of the questions file in `tmp_path` (the summary is written next to it, and the repository is read-only in the tests container) with `TopicEmbedder` and `TableReranker`: rows for questions 1–3 with places, question 4 «ошибка в наборе», summary over 3 questions, the models and settings line, the «Решение (FR-014)» line; neither the question texts nor any synthetic contract line appear in stdout or the saved summary; the summary file is written next to the questions file
- [ ] T019 [US4] [sonnet] `scripts/quickstart_search.py` per contracts/cli.md and research R-11: argparse `--questions`, `--json`; settings and connection like `scripts/quickstart_passages.py`; models loaded and checked once; per question `search.search(..., document_id=<from answer>, results=rerank_candidates)` with `rerank=False` and `rerank=True`; the time of a search is `SearchResult.seconds` (without model checks — the same number the `search` command prints); place of `answer` or «—»; `decide`; summary saved as `search-b3-summary-<YYYYMMDD-HHMMSS>.txt` next to the questions file; exit codes of the contract. Make T018 pass without editing it

**Checkpoint**: замер готов к запуску на Mac.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T020 [P] [haiku] `CLAUDE.md` «Commands»: `uv run docreader search "…" [--document ID] [--no-rerank] [--results N] [--json]` — hybrid search (feature 08); needs the search model server and, unless `--no-rerank`, the reranker (`llama-server --reranking` with BGE Reranker v2-m3, `[reranker]` in `settings.toml`, on the Mac only); stops with exit 2 here (`DOCREADER_FORBID_MODELS`); its output contains contract text, so on real contracts it is never sent to the agent; `scripts/quickstart_search.py --questions FILE` — the reranker measurement, its output (numbers and ids only) may be sent; test fakes `TopicEmbedder`, `TableReranker`
- [ ] T021 [P] [opus] `docs/tech-context.md` — decisions of the plan written back (plan «Отступления» #1, #2): the «Поиск по словам» row — BM25 by `lemmas` in code, `tsv` unused in the minimal version (research R-1), chosen by reasoning, not by a measurement: the comparison of the variants waits for the standard set of feature 02; «Модели в автотестах» — the reranker through `reranker.py` over `llama-server` `/v1/rerank`, fakes by transport (`TableReranker`); the «Реранкер» row — `[проверить]` until Б1
- [ ] T022 [opus] Full check: `DOCREADER_TEST_DATABASE_URL=postgresql:///postgres scripts/check.sh` and `docker compose run --rm tests`; review against spec.md FR-001…FR-014 and SC-001, SC-002, SC-004; quickstart А1–А2 on the dev server in a throwaway data dir with `docreader_demo`
- [ ] T023 [analyst] Quickstart Б0–Б2 on the Mac (after the branch is pushed): both `llama-server`s, `[reranker]` in `settings.toml` if it differs from the defaults, `uv run --env-file .env pytest -m real_model tests/real_model/test_reranker_server.py`, one `search` with and without `--no-rerank`; send the pytest output and the first line of each `search` (not the hits: contract text)
- [ ] T024 [analyst] Quickstart Б3: 15–20 questions, each about one contract, in `$DOCREADER_DATA_DIR/questions/rerank-08.toml`; check each answer with `docreader passage`; run `scripts/quickstart_search.py --questions …` twice — the places of both runs must be the same (SC-004); send the script output or the saved summary of both runs
- [ ] T025 [opus] Quickstart Б4: Б1 and Б3 into `docs/tech-context.md` (the «Реранкер» row without `[проверить]`: path, answer form, score scale; new «Гибридный поиск (фича 08), замер …» item: question count, top-1 and top-5 shares with and without the reranker, median and max time, SC-003, the decision by FR-014) and research.md R-7, R-12; if the decision is `disable`, the `RerankerSettings.enabled` default becomes `False` with its test changed in the same commit; a systematic failure from Б3 → a synthetic case in `tests/synthetic/` and a failing test first (CLAUDE.md «Delivery»)

---

## Dependencies & Execution Order

### Phase dependencies

- Phase 1 — T001 independent; needed by T007, T008, T012, T014, T018.
- Phase 2 — T002 ‖ T003 ‖ T004 ‖ T006; T005 after T002 (its settings).
- US1 — T007 after T001, T002, T006; T008 after T007; T009 after T003, T004, T008; T010 after T009 (its data classes); T011 after T009, T010.
- US2 — T012 after T011; T013 after T012.
- US3 — T014 after T005, T013; T015 after T014; T016 after T005 (independent of search).
- US4 — T017 after T004; T018 after T015, T017; T019 after T018.
- Polish — T020 after T019; T021 any time; T022 after T019, T020, T021; T023 after T022 (branch pushed); T024 after T023; T025 after T024.

### Same-file sequencing (no [P] between these)

- `src/docreader/search.py`: T007 → T009 → T013 → T015.
- `tests/integration/test_search.py`: T008 → T012 → T014 → T018.
- `src/docreader/ranking.py`, `tests/unit/test_ranking.py`: T004 → T017.
- `src/docreader/cli.py`: T011 → T013.
- `src/docreader/render.py`: T010 → T015.
- `src/docreader/config.py`: T002 only. `tests/conftest.py`: T005 only. `tests/fakes/embedding.py`: T006 only.

## Parallel Examples

```text
Phase 1–2: T001 (generator, haiku) ‖ T002, T003, T004, T006 (main session, one after another) — then T005.
US1: T009 (search, sonnet), then T010 (render, haiku), then T011 (CLI, haiku); T012 only after T011 (it adds tests to the file T009 must make pass).
US3: T016 (real-model test) ‖ T014.
Polish: T020 (docs, haiku) ‖ T021 (main session).
```

## Implementation Strategy

### MVP first

Phase 1–2 + US1 + US2 (T001–T013): поиск по словам и по смыслу со слиянием, в одном
договоре или во всех, без реранкера (`--no-rerank`). Этого достаточно, чтобы фича 09
получала отрывки. US3 добавляет реранкер (включён по умолчанию — решение аналитика),
US4 — замер для решения о нём.

### Incremental delivery

1. Phase 1–2 → синтетика, настройки, формулы, клиент реранкера и подделки.
2. US1 → `search --no-rerank` по всем договорам.
3. US2 → `--document`.
4. US3 → реранкер по умолчанию; уровень 3 на Mac.
5. US4 → скрипт замера.
6. Polish → документы, Б0–Б4 на Mac, решение о реранкере в tech-context.
