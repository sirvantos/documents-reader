# Quickstart: нарезка, метки и индексы (фича 07)

Проверка готовности фичи. Часть А — сервер разработки (модели нет), часть Б — ноутбук
аналитика (реальная модель поиска, реальные договоры только в Б4). Агенту присылается
только то, что помечено «можно прислать». Команды — [contracts/cli.md](contracts/cli.md),
интерфейс модели — [contracts/embedding.md](contracts/embedding.md), данные —
[data-model.md](data-model.md).

## А. Сервер разработки

### А0. pgvector — **[проверить]** (R-10)

```bash
sudo apt install postgresql-17-pgvector
psql postgresql:///postgres -Atc "SELECT version, trusted FROM pg_available_extension_versions WHERE name = 'vector' ORDER BY 1 DESC LIMIT 1"
# trusted = f → один раз от суперпользователя:
sudo -u postgres psql -d template1 -c 'CREATE EXTENSION IF NOT EXISTS vector'
sudo -u postgres psql -d docreader_demo -c 'CREATE EXTENSION IF NOT EXISTS vector'
docker compose build tests lint && docker compose pull db   # образ pgvector/pgvector:pg17
```

Ожидается: версия 0.8.x; после этого `docreader migrate` во временной базе проходит.
Итог (доверенное расширение или шаблон) — в `docs/tech-context.md`, строка «Запуск
PostgreSQL», вместо «установка pgvector [проверить]».

### А1. Автотесты

```bash
uv sync
scripts/check.sh
docker compose run --rm tests
```

Ожидается: все тесты, ruff и mypy проходят; модель поиска подменена `HashEmbedder`.

### А2. Ручной прогон без модели

Только временная папка данных и база `docreader_demo` (CLAUDE.md, «Machines»), как А2
фичи 05:

```bash
uv run --env-file "$DEMO/.env" docreader migrate
uv run --env-file "$DEMO/.env" docreader index; echo "код $?"
uv run --env-file "$DEMO/.env" docreader passage D-0001/2.1; echo "код $?"
```

Ожидается: `index` — «На этой машине модель поиска не запускается
(DOCREADER_FORBID_MODELS)», код 2, состояния не изменились; `passage` — «Отрывков нет:
выполните docreader index D-0001», код 1.

## Б. Ноутбук аналитика

### Б0. Установка — **[проверить]** (R-1, R-10)

```bash
brew install llama.cpp   # pgvector для postgresql@17 — сборка из исходников (tech-context, «Запуск PostgreSQL»)
psql postgresql:///postgres -Atc "SELECT version, trusted FROM pg_available_extension_versions WHERE name = 'vector' ORDER BY 1 DESC LIMIT 1"
# trusted = f → CREATE EXTENSION vector в template1 и в базе docreader от суперпользователя
# веса BGE-M3 в GGUF (F16 или Q8_0) — скачать заранее в папку моделей, вне репозитория
llama-server -m ~/models/bge-m3-Q8_0.gguf --embedding --pooling cls -c 8192 -b 8192 -ub 8192 -np 1 \
  --host 127.0.0.1 --port 8081
```

В `settings.toml`:

```toml
[embedding]
base_url = "http://127.0.0.1:8081/v1"
model = "bge-m3"
```

Затем `uv run --env-file .env docreader migrate`.

**Можно прислать**: версии pgvector и llama.cpp, `trusted`, имя файла весов и сжатие.

### Б1. Модель поиска на синтетике (уровень 3)

```bash
git fetch && git checkout 006-passages-and-indexes
uv run pytest -m real_model tests/real_model/test_embedding_server.py
```

Ожидается: проходит; размерность 1024. **Можно прислать**: вывод pytest.

### Б2. Один договор

```bash
/usr/bin/time -l uv run --env-file .env docreader index D-0001 --json > /tmp/b2.json
```

Ожидается: `done`, `passages = word_entries = vectors`. **Можно прислать**: вывод
`--json` (числа без текста) и строки времени и памяти.

### Б3. Память: три модели вместе (решение аналитика 2026-11-24)

tech-context, «Что проверить в первый день», п. 3. Веса реранкера (BGE Reranker v2-m3
в GGUF) скачать заранее в папку моделей, вне репозитория. Запустить одновременно:

```bash
mlx_lm.server --model <qwen3.6-27b-4bit> --host 127.0.0.1 --port 8080     # языковая модель (фича 05)
llama-server -m ~/models/bge-m3-Q8_0.gguf --embedding --pooling cls -c 8192 -b 8192 -ub 8192 -np 1 --host 127.0.0.1 --port 8081
llama-server -m ~/models/bge-reranker-v2-m3-Q8_0.gguf --reranking -c 8192 -b 8192 -ub 8192 -np 1 --host 127.0.0.1 --port 8082
```

В другом окне — один запрос к каждой: `docreader extract D-0001`, `docreader index D-0001`
и запрос к реранкеру:

```bash
curl -s http://127.0.0.1:8082/v1/rerank -H 'Content-Type: application/json' \
  -d '{"query": "срок оплаты", "documents": ["оплата в течение 30 дней", "гарантийный срок"]}'
```

Записать: память каждого процесса (Мониторинг системы, столбец «Память», или
`ps -o rss= -p <pid>`), давление памяти и своп (`memory_pressure`, `sysctl vm.swapusage`)
до и во время запросов; время `extract D-0001` по сравнению с Б3 фичи 05 (264 с на 35 страниц).

Ожидается одно из двух: помещаются вместе (давление в норме, своп не растёт, время
`extract` близко к прежнему) или нужна поочерёдная загрузка. **Можно прислать**:
числа памяти, давление, своп, время.

### Б4. Весь набор (SC-001–SC-004)

```bash
caffeinate -i uv run --env-file .env docreader index --all --label "07 полный прогон" --json \
  > ~/…/reports/index-07-full.json; echo "код $?"
uv run --env-file .env python scripts/quickstart_passages.py --report ~/…/reports/index-07-full.json
uv run --env-file .env docreader index --all --json > ~/…/reports/index-07-rerun.json
uv run --env-file .env python scripts/quickstart_passages.py --report ~/…/reports/index-07-rerun.json \
  --compare ~/…/reports/index-07-full.json
```

Скрипт печатает только числа: договоры по состояниям; отрывки по частям; записи обоих
индексов; покрытие SC-001 (непробельные символы вне отрывков и в двух отрывках сразу —
должно быть 0) и прослеживаемость SC-002 (страницы и границы каждого отрывка сверены
с `text_span`); время всего и на договор; при `--compare` — изменились ли числа
отрывков и записей (SC-003).

Ожидается: SC-001 и SC-002 — 100%; SC-003 — без изменений; SC-004 — набор ≤ 30 мин.
**Можно прислать**: вывод `index` (текстовый или `--json`) и вывод скрипта. Вывод
`passage` на реальных договорах не присылать (принцип I).

### Б5. Запись итогов

Цифры Б0–Б4 — в `docs/tech-context.md`: pgvector и llama.cpp («Запуск PostgreSQL»,
«Поиск по смыслу»), память трёх моделей («Что проверить в первый день», п. 3, и
«Языковая модель»), раздел «Нарезка и индексы (фича 07), замер …». До фичи 02 таблицы
результатов нет (plan.md, Complexity Tracking).
