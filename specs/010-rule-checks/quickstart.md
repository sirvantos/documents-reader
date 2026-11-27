# Quickstart: проверки правилами и статусы полей (фича 06)

Проверка, что фича работает. Подробности команд — [contracts/cli.md](contracts/cli.md),
файлов — [contracts/files.md](contracts/files.md), таблиц — [data-model.md](data-model.md).

## А. Сервер разработки

### А1. Проверки

```bash
scripts/check.sh   # тесты, ruff, mypy; нужен DOCREADER_TEST_DATABASE_URL
```

Ожидается: всё проходит; среди тестов — каждое правило на синтетическом договоре
с внесённой ошибкой ловит её и молчит на договоре без дефектов (SC-002), повторный
`check` даёт те же статусы (SC-005), решения переживают повторное извлечение (SC-006),
вывод команд без значений и текста.

### А2. Ручной прогон на синтетике

Временная папка данных и база `docreader_demo` (CLAUDE.md, «Machines»); модель заменена
фиксированными ответами (`ScriptedModel`) в тестах, поэтому на сервере ручной прогон — только через
интеграционные тесты: `uv run pytest tests/integration/test_check_cli.py -v`.

## Б. Ноутбук аналитика

### Б0. Ветка и база

```bash
git pull && uv sync --group ocr
uv run --env-file .env docreader migrate
```

Ожидается: миграция `0008_checks` применена.

### Б1. Проверки на рабочем наборе (SC-001, SC-004, SC-005)

```bash
time uv run --env-file .env docreader check --all
uv run --env-file .env docreader check summary
uv run --env-file .env docreader check --all --again && uv run --env-file .env docreader check summary
```

Ожидается: у каждого из 336 полей один статус; меньше минуты; вторая сводка совпадает
с первой. **Прислать:** вывод всех команд и время.

### Б2. Польза правил по эталону (SC-003)

```bash
uv run --env-file .env docreader check report --label "правила 06.1"
```

**Прислать:** вывод (числа). Ориентир: верных значений в очереди не больше 20%.

### Б3. Очередь и решения (SC-006, SC-007)

```bash
uv run --env-file .env docreader check queue
# открыть страницу, решить карточки, скачать ответы в папку данных
uv run --env-file .env docreader check load ~/…/check-review-….json
uv run --env-file .env docreader check summary
```

**Прислать:** вывод `queue`, `load`, `summary` и время прохода очереди. Страницу и файл
ответов не присылать.

### Б4. Запись итогов (агент)

Агент записывает в `docs/tech-context.md` пункт «Проверки правилами (фича 06), замер …»:
статусы рабочего набора, время, польза правил по эталону, время очереди; невыполненный
ориентир записывается, не подгоняется.
