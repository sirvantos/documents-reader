# Quickstart: ответ по тексту с цитатами и проверкой (фича 09)

Проверка фичи по шагам. Команды — [contracts/cli.md](contracts/cli.md), модель
и записи — [contracts/model.md](contracts/model.md), решения — [research.md](research.md).

## А. Сервер разработки

### А1. Автотесты

```bash
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres scripts/check.sh
```

Ожидается: все тесты, ruff и mypy проходят. Ответ проверяется на синтетических
договорах `make_answer_contracts` с `ScriptedModel` (уровень 1), записями
`tests/recordings/09-text-answers/` (уровень 2, после Б2) и подделками поиска
`TopicEmbedder`/`TableReranker`; к реальным моделям никто не обращается
(`DOCREADER_FORBID_MODELS`).

### А2. Ручной прогон без моделей

Только временная папка данных и база `docreader_demo` (CLAUDE.md, «Machines»):

```bash
uv run --env-file "$DEMO/.env" docreader ask ""; echo "код $?"
uv run --env-file "$DEMO/.env" docreader ask "Какой срок оплаты?" --document D-0001; echo "код $?"
```

Ожидается: пустой вопрос — «Пустой вопрос — введите вопрос о договорах», код 1;
договор без отрывков — «Отрывков нет: выполните docreader index D-0001», код 1;
проиндексированный договор — остановка «На этой машине языковая модель
не запускается (DOCREADER_FORBID_MODELS)», код 2 (проверки до моделей, R-7). На сервере
разработки индекс построить нельзя (`index` требует модель поиска), поэтому вручную
здесь виден только первый случай; остановку по FORBID проверяют автотесты (T013).

## Б. Ноутбук аналитика

### Б0. Ветка, три сервера, настройки

```bash
git switch 008-text-answers && git pull && uv sync
cd ~/models && mlx_lm.server --model qwen3.6-27b-4bit --host 127.0.0.1 --port 8080
llama-server -m ~/models/bge-m3-Q8_0.gguf --embedding --pooling cls -c 8192 -b 8192 -ub 8192 -np 1 \
  --host 127.0.0.1 --port 8081
llama-server -m ~/models/bge-reranker-v2-m3-Q8_0.gguf --reranking -c 8192 -b 8192 -ub 8192 -np 1 \
  --host 127.0.0.1 --port 8082
```

`settings.toml` — без изменений: `[answer]` по умолчанию (R-2), соединение с моделью —
`[extraction]`.

### Б1. Реальная модель на синтетике (уровень 3)

```bash
uv run --env-file .env pytest -m real_model tests/real_model/test_answer_server.py
```

Ожидается: проходит; вопрос с ответом — `answered` с найденными цитатами, без
ответа — `not_found`. **Можно прислать**: вывод pytest.

### Б2. Записи ответов для автотестов (уровень 2)

```bash
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres \
  uv run python -m tests.synthetic.record_answers --quantization "4 бита" --server "mlx_lm.server 0.32.2"
git add tests/recordings/09-text-answers && git commit -m "test(answers): recordings of the real model on synthetic contracts" && git push
```

Ожидается: три записи (`payment`, `parties`, `absent`). Тест уровня 2
(`tests/integration/test_ask_recorded.py`) агент пишет и запускает на сервере
разработки после того, как записи отправлены (tasks.md, T019).
Записи — синтетика, их можно коммитить и присылать (CLAUDE.md).

### Б3. Один вопрос

```bash
uv run --env-file .env docreader ask "Какой срок оплаты?" --document D-0015
uv run --env-file .env docreader ask "Кто подрядчик по договору?" --document D-0015
uv run --env-file .env docreader ask "Какой срок оплаты?"
```

Ожидается: ответ с цитатами и ссылками, у каждого подтверждённого утверждения —
пункт и страница; во втором вопросе среди просмотренных — преамбула «добавлена
правилом» (если поиск её не нашёл), ответ — с цитатой из неё (FR-010). Вывод содержит
текст договоров — **не присылать** (принцип I). Можно прислать только первую строку
каждого ответа (итог, число утверждений, время).

### Б4. Замер ответов (история 3, SC-001, SC-003, SC-004)

Набор — файл в папке данных, не в репозитории: 15–20 вопросов с ответом в договоре
(можно взять вопросы замера фичи 08 `rerank-08.toml` — у каждого есть договор) и 5–10
вопросов, ответа на которые в договоре нет («Какой размер аванса?» там, где аванса
нет). Форма:

```toml
[[question]]
text = "Какой срок оплаты?"
document = "D-0015"
expected = "answer"

[[question]]
text = "Предусмотрен ли аванс?"
document = "D-0015"
expected = "none"
```

```bash
# переменная DOCREADER_DATA_DIR есть только в .env, поэтому путь раскрывает sh внутри uv run
uv run --env-file .env sh -c \
  'python scripts/quickstart_answers.py --questions "$DOCREADER_DATA_DIR/questions/answers-09.toml"'
```

Ожидается: таблица по вопросам, итоги по пометкам, время, «повторная проверка цитат:
… не найдено 0» (SC-001). Затем открыть файл ответов (`answers-b4-….txt`, только для
себя) и для каждого вопроса с пометкой `answer` отметить, верен ли подтверждённый
ответ. **Можно прислать**: вывод скрипта или сохранённую сводку и одно число — сколько
ответов на вопросы с ответом верны. Файл ответов и файл вопросов — **не присылать**.

Ориентиры: верных подтверждённых ответов ≥ 80% вопросов с ответом и отказов ≥ 80%
вопросов без ответа (SC-003); медиана времени ≤ 60 с (SC-004). Невыполненный ориентир
записывается, а не исправляется подгонкой на этих же вопросах (спецификация, SC-003).

### Б5. Запись итогов

Итог Б1, Б4 и число верных ответов — в `docs/tech-context.md`: строка «Языковая
модель» (ответ, время) и новый абзац «Ответ по тексту (фича 09), замер …» рядом
с замером фичи 08. Если медиана выше 60 с — сначала меньше `[answer] passages`
(R-12), с повтором Б4.
