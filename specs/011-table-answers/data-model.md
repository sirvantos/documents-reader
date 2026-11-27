# Data model: ответ по таблице (фича 10)

Таблиц и миграции нет: ответ только читает базу и ничего не пишет (FR-013).
Решения — [research.md](research.md).

## Что читается

| Таблица | Фича | Что берётся |
|---|---|---|
| `document` | 01 | все договоры реестра (`id`) — набор ответа |
| `field_value` | 05 | `result`, `value_normalized`, `clause_key` шести полей; запуск извлечения (для устаревания) |
| `field_status` | 06 | `status`, `flags`, `extraction_run_id`, `checks_version`, `settings_sha256` |
| `field_decision` | 06 | `kind`, `value_normalized` решения аналитика |

## Сущности в памяти

### `TableReply` (ответ модели, `table_prompt.py`)

Схема R-3: `kind`, `action`, `field`, `op`, `value`, `value_to`, `reason`, `other` —
строки (или пусто), кроме `kind` (перечисление `query`/`refuse`/`clarify`/`unsupported`).

### `TableQuery` (проверенный запрос, `table_query.py`)

| Поле | Тип | Правило |
|---|---|---|
| `action` | `count` \| `list` | R-4 |
| `field` | одно из шести полей или `party` | R-4 |
| `op` | `eq`, `gt`, `ge`, `lt`, `le`, `before`, `after`, `between` | допустимо для вида поля (R-4) |
| `value` | приведённое значение: номер, наименование, `Decimal`, дата ISO | `values.normalize` по виду |
| `value_to` | дата ISO | только `between` |
| `period` | код периода или нет | R-6; даты уже вычислены в `value`/`value_to` |
| `other` | текст о втором запросе или нет | R-3 |

Проверка возвращает `TableQuery` или `Problem(code, detail)` с кодом из R-4.

### `Cell` и `DocRow` (строки таблицы, `table_answer.load_rows`)

`DocRow(document_id, cells: dict[поле, Cell])`; `Cell(state, value, clause_id, flags)`,
`state` — одно из `effective`, `unreviewed`, `needs_review`, `rejected`, `not_found`,
`no_extraction`, `checks_stale` (R-5). У договора без извлечения или с устаревшими
проверками все шесть ячеек в этом состоянии.

### `Result` (`table_query.execute`)

| Поле | Что |
|---|---|
| `query` | выполненный `TableQuery` (для `party` — со стороной) |
| `rows` | учтённые договоры, подошедшие под условие, по идентификатору: `DocRow` и пометка «непроверенное значение» |
| `count` | `len(rows)` |
| `matched_names` | разные написания из таблицы, совпавшие с наименованием условия |
| `excluded` | неучтённые: причина (состояние ячейки поля условия) → идентификаторы |
| `considered` | сколько договоров учтено (было с действующим значением поля условия) |
| `include_unreviewed` | была ли просьба учесть непроверенные |

### `TableAnswer` (`table_answer.ask_table`)

| Поле | Что |
|---|---|
| `question` | вопрос |
| `outcome` | `answered`, `refused`, `clarify`, `unsupported`, `rejected`, `failed` (R-8) |
| `result` | `Result` или нет |
| `reason` | причина отказа, уточнения, «не поддерживается», недопустимого запроса или ошибки |
| `other` | о втором запросе в вопросе |
| `retried` | был ли повтор R-9 |
| `today` | дата, от которой считались периоды |
| `provenance` | код, модель, `PROMPT_VERSION`, отпечаток подсказки, `CHECKS_VERSION` |
| `seconds` | время от проверки модели до ответа |

`to_json()` — всё это; значения договоров — только в `result.rows` и `matched_names`.

## Настройки

`[table]` в `settings.toml` (`TableSettings` в `config.py`): `max_tokens` 512,
`max_retries` 2, `list_rows` 20 (R-2). Соединение модели — `[extraction]`.
