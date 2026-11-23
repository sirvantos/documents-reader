# Quickstart: Извлечение полей (фича 05)

Часть А — на сервере разработки, только синтетика и поддельная модель. Часть Б —
на Mac аналитика, реальная модель; реальные договоры — только в Б4–Б5. Агенту
присылается только то, что помечено «можно прислать». Команды —
[contracts/cli.md](contracts/cli.md), интерфейс модели и записи —
[contracts/model.md](contracts/model.md), данные — [data-model.md](data-model.md).

## А. Сервер разработки

### А1. Автотесты

```bash
uv sync
scripts/check.sh
docker compose build tests && docker compose run --rm tests
```

Ожидается: все тесты, ruff и mypy проходят. Тесты уровня 2 (`RecordedModel`) проходят
только после того, как аналитик записал ответы (Б2); до этого они падают с сообщением
«перезапишите ответы на ноутбуке» — это не ошибка кода.

### А2. Ручной прогон без модели

Только временная папка данных и база `docreader_demo` (CLAUDE.md, «Machines»).

```bash
export DEMO=$(mktemp -d)
createdb docreader_demo 2>/dev/null || true
cat > "$DEMO/.env" <<EOF
DOCREADER_DATA_DIR=$DEMO/data
DOCREADER_DATABASE_URL=postgresql:///docreader_demo
DOCREADER_FORBID_MODELS=1
EOF
mkdir -p "$DEMO/data" "$DEMO/in"
uv run python -c "from tests.synthetic.make_pdfs import make_extraction_contracts as m; m('$DEMO/in')"
uv run --env-file "$DEMO/.env" docreader migrate
uv run --env-file "$DEMO/.env" docreader add "$DEMO/in"
uv run --env-file "$DEMO/.env" docreader read
uv run --env-file "$DEMO/.env" docreader parse
uv run --env-file "$DEMO/.env" docreader extract; echo "код $?"
uv run --env-file "$DEMO/.env" docreader fields D-0001; echo "код $?"
```

Ожидается: `extract` — «На этой машине языковая модель не запускается
(DOCREADER_FORBID_MODELS)», код 2, состояния `extraction` не изменились (`docreader
show D-0001`); `fields` — «Поля D-0001 не извлекались — выполните docreader extract
D-0001», код 1. Полный путь с ответами модели проверяют интеграционные тесты с
`ScriptedModel` и `RecordedModel`.

## Б. Mac аналитика

Подготовка: `git pull` ветки `005-field-extraction`, `uv sync`.

### Б1. Сервер модели и проверка подключения

Запустить Qwen3.6-27B в 4 битах на локальном OpenAI-совместимом сервере (способ —
**[проверить]**: MLX или llama.cpp, tech-context). Окно — не меньше 48 тыс. токенов
(research R-13); только `127.0.0.1`. Пример для llama.cpp:

```bash
llama-server -m <путь к весам>.gguf --host 127.0.0.1 --port 8080 -c 49152 --jinja
```

Рассуждения Qwen отключены по умолчанию (`[extraction] extra_body`, research R-11).
Имя модели на сервере должно совпадать с `[extraction] model` (`qwen3.6-27b-4bit`):
`curl -s http://127.0.0.1:8080/v1/models`. Для MLX — запуск из папки с весами по
короткому имени, иначе имя — полный путь с именем пользователя:

```bash
cd ~/models && mlx_lm.server --model qwen3.6-27b-4bit --host 127.0.0.1 --port 8080
```

```bash
uv run pytest -m real_model tests/real_model/test_llm_server.py
```

Ожидается: тесты проходят (подключение, ответ по схеме на синтетическом договоре,
тайм-аут, сообщение при выключенном сервере — тест сам просит остановить сервер
или пропускает этот случай). **Можно прислать**: вывод pytest.

### Б2. Запись ответов для автотестов (уровень 2)

```bash
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres \
  uv run python -m tests.synthetic.record_extraction --quantization "4 бита" --server "llama.cpp <версия>"
git add tests/recordings/05-field-extraction && git commit -m "test(extraction): record model answers on synthetic contracts" && git push
```

Ожидается: по файлу на вариант R-14. Только синтетика; записи руками не правятся.
**Можно прислать**: вывод команды и `pytest` после записи.

### Б3. Скорость и память на одном договоре — **[проверить]** (SC-004, R-13)

На одном реальном договоре во временной копии базы или в рабочей базе:

```bash
/usr/bin/time -l uv run --env-file .env docreader extract D-0001 --json > /tmp/b3.json
```

Записать: `seconds` из вывода, пиковую память процесса сервера модели (Монитор
активности), включены ли рассуждения. Повторить с `enable_thinking = true`, если
пригодных ответов меньше. **Можно прислать**: секунды, память, состояние и числа
полей из `extract --json` (без `fields`). Итог переносится в tech-context
(«Языковая модель», «Способ запуска модели»).

### Б4. Прогон набора

```bash
uv run --env-file .env docreader extract --all --label "05 первый прогон" --json > ~/docreader-data/reports/extract-05.json
uv run --env-file .env python scripts/quickstart_extraction.py
```

`scripts/quickstart_extraction.py` печатает только числа: договоров по состояниям;
по каждому полю — найдено / не найдено / отклонено / ошибка; виды причин отклонения;
время всего прогона и на договор (медиана, наибольшее); повторную программную
проверку всех найденных значений по текущему тексту (SC-001: цитата есть в тексте
и содержит значение — должно быть 100%); список идентификаторов для ручной проверки
по правилу Б5.

Ожидается: SC-004 — весь набор ≤ 8 ч; SC-001 — 100%. **Можно прислать**: вывод
`extract` (текстовый или `--json`) и вывод скрипта.

### Б5. Ручная проверка 10 договоров (SC-002, SC-003)

Отбор (уточнение Q6) печатает скрипт Б4: все три договора с текстовым слоем и 7 сканов
по порядку идентификаторов через равный шаг, среди них хотя бы один «требует просмотра»
по извлечению, если такие есть.

По каждому договору: `docreader fields D-…` рядом с исходным PDF; для каждого из шести
полей отметить: верное значение, верное «не найдено», неверное значение, пропуск
(«не найдено» при значении в договоре), придуманное значение (значения нет в договоре),
верное отклонение, неверное отклонение.

Ожидается: SC-002 — верных результатов ≥ 54 из 60 (90%); SC-003 — придуманных
значений среди «найдено» 0. **Можно прислать**: только счётчики по видам и полям;
вывод `fields`, значения и цитаты — не присылать (принцип I).

### Б6. Запись итогов

Цифры Б3–Б5 — в `docs/tech-context.md` («Извлечение полей (фича 05), замер …»),
как у фичи 04; до фичи 02 таблицы результатов нет (plan.md, Complexity Tracking).
