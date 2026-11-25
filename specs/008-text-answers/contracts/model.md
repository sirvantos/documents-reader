# Языковая модель ответа: подсказка, схема, повтор, записи (фича 09)

Решения — [research.md](../research.md) R-2, R-3, R-6, R-9. Клиент модели —
`docreader/llm.py` фичи 05 без изменений
([contracts/model.md фичи 05](../../005-field-extraction/contracts/model.md)).

## Соединение

```text
llm.load_client(dataclasses.replace(settings.extraction,
                max_tokens=settings.answer.max_tokens,
                max_retries=settings.answer.max_retries))
    адрес, модель, mode, timeout_s, temperature (0), seed, extra_body — из [extraction]
    защиты llm.py: петлевой адрес, DOCREADER_FORBID_MODELS, тихие журналы
ModelClient.check() — до поиска (R-7)
ModelClient.extract(messages, AnswerReply) — первый запрос и повтор
```

## `docreader/answer_prompt.py`

```text
PROMPT_VERSION = "09.1"
SYSTEM_PROMPT, USER_TEMPLATE, RETRY_TEMPLATE — строки
AnswerReply, ClaimReply — Pydantic-схема (data-model.md), проверки формы — в валидаторе
build_messages(question: str, shown: Sequence[PromptPassage]) -> list[dict]
build_retry(messages, first_reply_json: str, unconfirmed: Sequence[tuple[int, str]]) -> list[dict]
prompt_sha256() -> str   # SYSTEM_PROMPT + USER_TEMPLATE + RETRY_TEMPLATE + схема
```

`PromptPassage` — `clause_id`, `label`, `text`. Модуль не импортирует библиотек модели.

### Пользовательское сообщение (образец формы)

```text
Вопрос: {question}

<<<ОТРЫВКИ
[D-0015/2.2.1] D-0015 · раздел 2. Цена и порядок расчётов · пункт 2.2.1
{текст отрывка}

[D-0015/преамбула] D-0015 · преамбула
{текст отрывка}
ОТРЫВКИ>>>
```

Подстановка — `str.replace`, не `format`. Порядок отрывков — порядок показа (R-5).

### Повтор (R-6)

Сообщения повтора = сообщения первого запроса + `{"role": "assistant", "content":
<первый ответ модели как JSON>}` + пользовательское сообщение `RETRY_TEMPLATE`:
список «номер. текст утверждения» тех утверждений, цитаты которых не найдены
дословно, и просьба вернуть только их — исправленными, с цитатами, скопированными
из отрывков без изменений, — или вид «не найдено», если подтвердить их нельзя.
Форма ответа — та же `AnswerReply`.

### Ответ модели

```json
{"kind": "answer",
 "claims": [{"text": "Оплата — в течение 30 дней с даты поставки.",
             "clause": "D-0015/2.2",
             "quote": "Срок оплаты товара составляет 30 дней с даты поставки."}]}
```

```json
{"kind": "not_found", "claims": []}
```

## Записи ответов — `tests/recordings/09-text-answers/<variant>.json`

Формат — как у фичи 05: `variant`, `generator_version` (версия
`make_answer_contracts`, `ANSWER_GENERATOR_VERSION`), `prompt_version` («09.1»),
`prompt_sha256`, `model`, `served_model`, `quantization`, `server`, `settings`,
`recorded_at`, `exchanges` (`request_sha256`, `attempt`, `response`). Варианты —
вопросы на синтетических договорах: `payment` (ответ есть), `parties` (ответ
в преамбуле, добавленной правилом), `absent` (ответа нет).

`RecordedModel(variant, prompt_version=answer_prompt.PROMPT_VERSION,
prompt_sha256=answer_prompt.prompt_sha256(), generator_version=ANSWER_GENERATOR_VERSION,
recordings_dir=…/09-text-answers)` — существующий класс `tests/fakes/llm.py`;
устаревшая запись или запрос не из записи → `StaleRecording` с подсказкой
«uv run python -m tests.synthetic.record_answers».

## Команда записи — `tests/synthetic/record_answers.py`

```text
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres \
  uv run python -m tests.synthetic.record_answers [VARIANT ...] \
    --quantization "4 бита" --server "mlx_lm.server 0.32.2"
```

- договоры — только `make_answer_contracts` в `tests/synthetic/out/` (другие пути
  не принимаются: защита `record_recognition.check_paths`, принцип I);
- договоры проходят настоящий конвейер во временной базе: `add`, `read`, `parse`,
  `index` с `TopicEmbedder`; поиск — `TopicEmbedder` и `TableReranker` с тем же
  порядком, что в тестах уровня 2 (задан в модуле тестов и импортируется отсюда);
- реальная только языковая модель: адрес `DOCREADER_RECORD_BASE_URL` или
  `[extraction] base_url`, только петлевой; при `DOCREADER_FORBID_MODELS` — код 2;
- защиты — общим кодом с `record_extraction` (вынести, не копировать).

## Уровень 3 — `tests/real_model/test_answer_server.py`

Только ноутбук, `pytest -m real_model`: синтетический договор, реальная языковая
модель, подделки поиска. Вопрос с ответом → `answered`, у каждого подтверждённого
утверждения цитата найдена; вопрос без ответа → `not_found`. Проверяет подключение
и форму, не качество.
