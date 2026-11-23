# Интерфейс языковой модели и записи ответов (фича 05)

Решения — [research.md](../research.md) R-1–R-3, R-11. Образец — интерфейс движка
распознавания фичи 13 (`docreader/ocr.py`, `ocr_engines.py`, `tests/fakes/ocr.py`).

## `docreader/llm.py` — единственное место, где импортируются `openai` и `instructor`

```text
load_client(settings: ExtractionSettings, transport: httpx2.BaseTransport | None = None) -> ModelClient
    DOCREADER_FORBID_MODELS задана и transport не передан → EnvironmentProblem (код 2)
    base_url не локальный → EnvironmentProblem — и с переданным transport (та же функция,
    что проверяет адрес при загрузке настроек; защита от настроек, собранных в обход загрузки)
    transport=None → настоящий сетевой транспорт; в тестах — MockTransport из tests/fakes/llm.py

ModelClient.check() -> str
    GET {base_url}/models; id первой модели (или settings.model, если она в списке);
    нет ответа → ModelUnavailable (EnvironmentProblem)

ModelClient.extract(messages: list[dict], response_model: type[T]) -> T
    response_model — Pydantic-схема ответа; этап передаёт ExtractionAnswer (llm.py не
    импортирует extraction_prompt)
    Instructor, mode из настроек, max_retries = settings.max_retries,
    temperature, seed, max_tokens, extra_body из настроек, timeout = timeout_s
    ответ не по форме после повторов → AnswerFormError(attempts)
    обрыв / тайм-аут → ModelUnavailable
```

Тесты подменяют только `transport`; защита `DOCREADER_FORBID_MODELS` пропускает
переданный транспорт (так уровни 1–2 работают в Docker и на сервере), но не настоящий.
Автоматическая фикстура `_forbid_models` (`tests/conftest.py`) уже ставит переменную
во всех тестах, кроме `real_model`. Тест: `load_client` без транспорта при заданной
переменной — `EnvironmentProblem`, и ни одного сокета.

## Поддельные модели — `tests/fakes/llm.py`

```text
ScriptedModel(*answers: str | Exception) -> httpx2.MockTransport-фабрика
    отвечает на POST /chat/completions по порядку: строка → ответ сервера с этим
    content; исключение httpx2 (ConnectError, ReadTimeout) → исключение транспорта;
    GET /models → {"data": [{"id": "fake-model"}]}
    .requests — список тел запросов (для проверки подсказки и параметров)

RecordedModel(variant: str) -> транспорт по записи tests/recordings/05-field-extraction/<variant>.json
    запись устарела (prompt_version, prompt_sha256, GENERATOR_VERSION) → StaleRecording
    тело запроса с отпечатком, которого нет в записи → StaleRecording
    сообщение: «запись <variant> устарела: перезапишите ответы на ноутбуке —
    uv run python -m tests.synthetic.record_extraction»
```

## Формат записи — `tests/recordings/05-field-extraction/<variant>.json`

```json
{
  "variant": "base",
  "generator_version": 1,
  "prompt_version": "05.1",
  "prompt_sha256": "…",
  "model": "qwen3.6-27b-4bit",
  "served_model": "…",
  "quantization": "4 бита",
  "server": "llama.cpp server b…",
  "settings": {"mode": "md_json", "temperature": 0.0, "seed": 0, "max_tokens": 2048, "extra_body": {"chat_template_kwargs": {"enable_thinking": false}}},
  "recorded_at": "2026-11-27T10:15:00+03:00",
  "exchanges": [
    {"request_sha256": "…", "attempt": 1, "response": {"…": "тело ответа сервера как есть"}}
  ]
}
```

- `request_sha256` — SHA-256 канонического JSON (`sort_keys`, без пробелов) полей
  запроса `messages`, `model`, `temperature`, `seed`, `max_tokens` и `extra_body`.
- `exchanges` — все попытки одного договора по порядку, включая повторы Instructor.
- `quantization` и `server` вписывает аналитик флагами команды записи
  (`--quantization`, `--server`): сервер о них не сообщает.
- Синтетические договоры не содержат реальных данных, поэтому ответы хранятся
  целиком; записи не правятся вручную (CLAUDE.md).

## Команда записи — `tests/synthetic/record_extraction.py`

```text
uv run python -m tests.synthetic.record_extraction [PATH…] --quantization "4 бита" --server "…"
```

1. Пути — только внутри `tests/synthetic/` (`check_paths` из `record_recognition`);
   иначе отказ «записываются только синтетические файлы из tests/synthetic/», код 1;
   проверка — до загрузки настроек и модели. Без путей — все варианты
   `make_extraction_contracts` в `tests/synthetic/out/`.
2. Временная папка данных и база `docreader_record_<pid>` на сервере
   `DOCREADER_TEST_DATABASE_URL` (нет переменной — ошибка окружения); `migrate`, `add`,
   `read`, `parse` — настоящими функциями конвейера.
3. `extract` с транспортом-самописцем поверх сетевого (`[extraction]` из `settings.toml`
   во временной папке, адрес — из `DOCREADER_RECORD_BASE_URL` или по умолчанию).
4. Запись JSON; база и папка удаляются в `finally`.
