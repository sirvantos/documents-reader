# Quickstart: гибридный поиск с реранкером (фича 08)

Проверка фичи по шагам. Команды — [contracts/cli.md](contracts/cli.md), решения —
[research.md](research.md).

## А. Сервер разработки

### А1. Автотесты

```bash
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres scripts/check.sh
```

Ожидается: все тесты, ruff и mypy проходят. Поиск проверяется на синтетических
договорах с `TopicEmbedder`/`HashEmbedder` и `TableReranker`; к реальным моделям
никто не обращается (`DOCREADER_FORBID_MODELS`).

### А2. Ручной прогон без моделей

Только временная папка данных и база `docreader_demo` (CLAUDE.md, «Machines»), как А2
фичи 07:

```bash
uv run --env-file "$DEMO/.env" docreader search ""; echo "код $?"
uv run --env-file "$DEMO/.env" docreader search "срок оплаты" --document D-0001; echo "код $?"
```

Ожидается: пустой запрос — «Пустой запрос — введите слова для поиска», код 1; без
отрывков — «Отрывков нет: выполните docreader index D-0001», код 1 (проверка области
идёт до моделей, R-10). Модели на сервере разработки не нужны и не запускаются.

## Б. Ноутбук аналитика

### Б0. Реранкер и настройки

```bash
git switch 007-hybrid-search && git pull
llama-server -m ~/models/bge-m3-Q8_0.gguf --embedding --pooling cls -c 8192 -b 8192 -ub 8192 -np 1 \
  --host 127.0.0.1 --port 8081
llama-server -m ~/models/bge-reranker-v2-m3-Q8_0.gguf --reranking -c 8192 -b 8192 -ub 8192 -np 1 \
  --host 127.0.0.1 --port 8082
```

В `settings.toml` — только если значения отличаются от умолчаний (R-9):

```toml
[reranker]
base_url = "http://127.0.0.1:8082/v1"
model = "bge-reranker-v2-m3"
```

### Б1. Реранкер на синтетике (уровень 3) — **[проверить]** (R-7)

```bash
uv run --env-file .env pytest -m real_model tests/real_model/test_reranker_server.py
```

Ожидается: проходит; путь `/v1/rerank` и форма ответа подтверждены. **Можно
прислать**: вывод pytest.

### Б2. Один поиск

```bash
uv run --env-file .env docreader search "срок оплаты" --document D-0015
uv run --env-file .env docreader search "срок оплаты" --document D-0015 --no-rerank
```

Ожидается: 8 результатов, все из D-0015; с реранкером видна оценка. Вывод содержит
текст договора — **не присылать** (принцип I). Можно прислать только первую строку
(число кандидатов и время).

### Б3. Замер реранкера (история 4, SC-003, SC-005)

Составить 15–20 вопросов, каждый про один договор, с правильным пунктом
(уточнение 2026-11-24). Файл — в папке данных, не в репозитории:

```bash
mkdir -p "$DOCREADER_DATA_DIR/questions"
$EDITOR "$DOCREADER_DATA_DIR/questions/rerank-08.toml"
```

```toml
[[question]]
text = "Какой срок оплаты?"
answer = "D-0015/2.2.1"
```

Правильный пункт проверяется до замера: `docreader passage D-0015/2.2.1` должен
показать пункт, который отвечает на вопрос.

```bash
uv run --env-file .env python scripts/quickstart_search.py \
  --questions "$DOCREADER_DATA_DIR/questions/rerank-08.toml"
```

Ожидается: таблица мест и времени, итог и строка «Решение (FR-014)». SC-003 — медиана
≤ 3 с без реранкера и ≤ 10 с с ним. Запустить замер второй раз: места в обоих прогонах
совпадают (SC-004). **Можно прислать**: вывод скрипта или сохранённую
сводку (в них нет текста вопросов и договоров).

### Б4. Запись итогов

Итог Б1 и Б3 и решение по реранкеру — в `docs/tech-context.md` (строка «Реранкер»,
раздел «Гибридный поиск (фича 08), замер …»). Если решение — выключить, в коде
`[reranker] enabled` по умолчанию становится `false` (R-9). На 15–20 вопросах
разница в один вопрос — 5–7 процентных пунктов: вывод ориентировочный
и перепроверяется на эталоне фичи 02 (спецификация, Assumptions).
