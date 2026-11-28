# Quickstart: ответ по таблице (фича 10)

Проверка, что фича работает. Команды — [contracts/cli.md](contracts/cli.md), модель —
[contracts/model.md](contracts/model.md), данные — [data-model.md](data-model.md).

## А. Сервер разработки

### А1. Проверки

```bash
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres scripts/check.sh
```

Ожидается: всё проходит; среди тестов — проверка запроса (каждая причина R-4), периоды,
сопоставление наименований и выбор стороны, выполнение по каждому состоянию ячейки
(SC-006), повтор, вывод; интеграционные — `ask-table` на договорах `make_check_contracts`
после `extract` и `check` с `ScriptedModel`; уровень 2 — записи
`tests/recordings/10-table-answers/` (после Б2). Модель здесь не запускается:
`ask-table` вне тестов стоит с кодом 2.

## Б. Ноутбук аналитика

### Б0. Ветка

```bash
git pull && uv sync --group ocr
```

Миграции нет. Сервер языковой модели — как для фич 05 и 09.

### Б1. Уровень 3

```bash
uv run pytest -m real_model tests/real_model/test_table_server.py -v
```

**Прислать:** вывод (синтетика).

### Б2. Записи уровня 2

```bash
uv run python -m tests.synthetic.record_table_answers \
  --quantization "4 бита" --server "mlx_lm.server 0.32.2"
git add tests/recordings/10-table-answers && git commit -m "test(table): recordings" && git push
```

### Б3. Ручная проверка

```bash
uv run --env-file .env docreader check --all
uv run --env-file .env docreader ask-table "Сколько договоров дороже миллиона рублей с НДС?"
uv run --env-file .env docreader ask-table "Какие договоры заканчиваются в этом году?"
uv run --env-file .env docreader ask-table "На какую сумму все договоры?"
```

**Прислать:** только первую строку вывода каждой команды (итог, числа, время).

### Б4. Замер (SC-001, SC-004)

```bash
uv run --env-file .env python scripts/make_table_questions.py
# добавить свои вопросы в $DOCREADER_DATA_DIR/questions/table-10.toml (образцы — в файле)
uv run --env-file .env python scripts/quickstart_table.py
cat "$DOCREADER_DATA_DIR"/questions/table-b4-summary-*.txt | tail -40
```

**Прислать:** вывод `make_table_questions.py` и сводку `table-b4-summary-….txt`. Файлы
`table-10.toml` и `table-b4-….txt` (без `summary`) не присылать: в них значения договоров.

### Б5. Запись итогов (агент)

Агент записывает в `docs/tech-context.md` пункт «Ответ по таблице (фича 10), замер …»:
доля верных по шаблонам и по вопросам аналитика, исходы, повторы, время; невыполненный
ориентир записывается, не подгоняется; систематическая ошибка перевода — синтетический
вопрос и падающий тест сначала (CLAUDE.md «Delivery»).
