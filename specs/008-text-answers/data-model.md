# Data model: ответ по тексту (фича 09, минимальная версия)

Новых таблиц и миграции нет: `ask` и скрипт замера только читают базу и ничего
не пишут (FR-011, research R-11). Таблица `answer` из наброска tech-context появится
в следующей итерации вместе с записью ответов (сценарий 5 файла фичи).

## Что читается

| Таблица | Столбцы | Зачем |
|---|---|---|
| всё, что читает поиск фичи 08 | ([data-model фичи 08](../007-hybrid-search/data-model.md)) | найденные отрывки (`search.search`) |
| `passage` | `document_id`, `clause_key`, `part`, `start`, `end_`, `first_page`, `last_page`, `label` | границы показанных отрывков; отрывок преамбулы (`part = 'preamble'`, R-5) |
| `document_text` | `text`, `text_sha256` | текст договора для проверки цитат; актуальность отрывка преамбулы |
| `text_span` | `start`, `end_`, `page_number`, `line_index` | страницы цитаты (R-4) |

Отрывок преамбулы берётся только актуальный — то же условие `search.CURRENT_PASSAGE`.
Найденные поиском отрывки актуальны по построению поиска.

## Значения в памяти

### `AnswerSettings` (раздел `[answer]`, research R-2)

| Поле | Тип | По умолчанию | Проверка |
|---|---|---|---|
| `passages` | int | 8 | 1…`[search] rerank_candidates` |
| `max_tokens` | int | 2048 | 64…32768 |
| `max_retries` | int | 2 | 0…5 |

Неизвестный ключ раздела — ошибка настроек (код 2), как у других разделов.
Соединение с моделью — `[extraction]` (R-2).

### Схема ответа модели (`answer_prompt.py`, R-3)

| Тип | Поле | Правило |
|---|---|---|
| `AnswerReply` | `kind` | `"answer"` или `"not_found"` |
| | `claims` | `answer` — 1…10 утверждений; `not_found` — пусто |
| `ClaimReply` | `text` | непустой |
| | `clause` | идентификатор пункта, как его написала модель (может быть пустым) |
| | `quote` | цитата, как её написала модель (пустая — итог «нет цитаты», R-4) |

### `ShownPassage` — отрывок, показанный модели

| Поле | Тип | Что |
|---|---|---|
| `clause_id` | str | `D-0015/2.2.1` |
| `document_id`, `clause_key` | str | |
| `label` | str | метка фичи 07 |
| `start`, `end` | int | границы в `document_text.text` |
| `first_page`, `last_page` | int | страницы отрывка |
| `search_place` | int \| None | место в поиске; `None` — добавлен правилом (R-5) |
| `word_place`, `vector_place`, `fused_place` | int \| None | места по способам (из `search.Hit`) |
| `added_by_rule` | bool | преамбула добавлена правилом FR-010 |

Текст договора и строки `text_span` для проверки — отдельно, по договору:
`DocumentText(text, spans)` (не копируется в каждый отрывок).

### `CheckedClaim` — утверждение после проверки (R-4)

| Поле | Тип | Что |
|---|---|---|
| `text` | str | текст утверждения модели |
| `quote` | str | цитата, как её дала модель |
| `named_clause` | str | пункт, указанный моделью |
| `status` | `ClaimStatus` | `confirmed` / `confirmed_elsewhere` / `quote_not_found` / `no_quote` |
| `clause_id` | str \| None | фактический отрывок цитаты (для подтверждённых) |
| `quote_text` | str \| None | цитата, как она стоит в договоре (`text[start:end]`) |
| `start`, `end` | int \| None | место цитаты в `document_text.text` |
| `pages` | tuple[int, …] | страницы цитаты |
| `from_retry` | bool | утверждение из ответа повтора (R-6) |

`confirmed` и `confirmed_elsewhere` — подтверждённые; остальные — нет.

### `Answer` — итог вопроса (R-8)

| Поле | Тип | Что |
|---|---|---|
| `question` | str | |
| `document_id` | str \| None | ограничение договором |
| `outcome` | `AnswerOutcome` | `answered` / `unconfirmed` / `not_found` / `failed` |
| `claims` | list[CheckedClaim] | подтверждённые по порядку, затем неподтверждённые |
| `shown` | list[ShownPassage] | просмотренные отрывки в порядке показа |
| `retried` | bool | был ли повтор (R-6) |
| `not_found_first`, `not_found_final` | int | цитат не найдено в первом ответе и в итоге |
| `failure` | str \| None | причина `failed` (без текста ответа модели) |
| `warnings` | list[str] | предупреждения поиска и ответа, без текста договоров |
| `provenance` | `Provenance` | чем получено (FR-008) |
| `seconds` | float | время от поиска до итога |

`Provenance`: `code_version`, `llm_model` (как назвал сервер), `prompt_version`,
`embedding_model`, `reranker_model`, `passages`, `candidates`, `rrf_k`,
`rerank_candidates`.

`Answer.to_json()` — вид для `--json` ([contracts/cli.md](contracts/cli.md)); в файл
ответов замера идёт текстовый вывод `ask` (R-10); все типы — `dataclass` (tech-context «Правила
кода»).

## Правила итога (R-8)

- поиск не нашёл отрывков → `not_found`, модель не вызывается;
- первый ответ не по форме или ошибка HTTP → `failed`;
- `kind = "not_found"` → `not_found`;
- после проверки и повтора есть подтверждённое → `answered`, иначе → `unconfirmed`.

## Файлы замера (R-10)

| Файл | Где | Что | Кому |
|---|---|---|---|
| вопросы, TOML | папка данных (аналитик) | `[[question]]`: `text`, `document`, `expected` = `answer` / `none` | никому |
| `answers-b4-<время>.txt` | рядом с файлом вопросов | полный вывод `ask` по каждому вопросу | только аналитику |
| `answers-b4-summary-<время>.txt` | рядом с файлом вопросов | числа и идентификаторы (contracts/cli.md) | можно агенту |
