# Data Model: Извлечение полей (фича 05, минимальная версия)

Миграция `src/docreader/migrations/0005_extraction.sql`. Этап `extraction` уже есть
в `stage_status` (фича 01), строки `pending` для всех документов созданы; схема
`stage_status` не меняется. Решения — в [research.md](research.md).

## Новая таблица `field_value` — результат поля

Ровно шесть строк на извлечённый договор (FR-001, FR-002). Заменяются целиком при
повторном извлечении договора.

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | text | NOT NULL, FK → `document(id)` ON DELETE CASCADE | документ |
| `field` | text | NOT NULL, `IN` шести имён прототипа; PK вместе с `document_id` | имя поля каталога (`docreader/fields.py`) |
| `result` | text | NOT NULL, `IN ('found', 'not_found', 'rejected', 'failed')` | результат (R-8) |
| `value_text` | text | NOT NULL для `found`, иначе NULL | значение как в тексте — найденный фрагмент цитаты (R-7) |
| `value_normalized` | text | NOT NULL для `found`, иначе NULL | приведённое значение (R-6): `64270348.83`, `2026-03-25` |
| `quote` | text | NOT NULL для `found`, иначе NULL | цитата — участок `document_text.text[quote_start:quote_end]` |
| `quote_start`, `quote_end` | integer | NOT NULL для `found`; `0 <= quote_start < quote_end` | место цитаты в очищенном тексте |
| `clause_key` | text | NOT NULL для `found`; без FK (см. ниже) | пункт: ключ записи разбора (`2.1`, `преамбула`, `реквизиты`) |
| `page` | integer | NOT NULL для `found` | страница начала цитаты |
| `pages` | integer[] | NOT NULL для `found` | все страницы цитаты (правило низкого качества, R-8) |
| `reason` | text | NOT NULL для `rejected` и `failed`, иначе NULL | причина без текста договора |
| `proposed_value` | text | NULL | запись значения от модели (`found` и `rejected`) |
| `proposed_quote` | text | NULL | цитата от модели (`rejected`; для просмотра, FR-006) |
| `proposed_clause` | text | NULL | пункт, названный моделью |
| `source_text_sha256` | char(64) | NOT NULL, `~ '^[0-9a-f]{64}$'` | отпечаток `document_text.text`, по которому получен результат |
| `run_id` | bigint | NOT NULL, FK → `run(id)` ON DELETE RESTRICT | запуск извлечения |

CHECK по результату:

```text
found      ⇒ value_text, value_normalized, quote, quote_start, quote_end, clause_key,
             page, pages NOT NULL; reason NULL
not_found  ⇒ value_text, value_normalized, quote, quote_start, quote_end, clause_key,
             page, pages, reason, proposed_quote NULL
rejected   ⇒ reason NOT NULL; value_text, value_normalized, quote … pages NULL
failed     ⇒ reason NOT NULL; value_text … pages NULL; proposed_* NULL
```

Так схема сама не даёт записать «найдено» без цитаты и места (принцип III, FR-006).

Внешнего ключа на `clause` нет: `parse` заменяет записи документа через `DELETE` +
`INSERT` (`parsing.py`), и каскад стёр бы поля даже при повторном разборе того же
текста, а FK без каскада не дал бы разбору перезаписать пункты. Ключ остаётся верным
по построению: тот же текст даёт те же ключи (SC-004 фичи 04), другой текст сбрасывает
этап и делает строки устаревшими по `source_text_sha256`. `fields` показывает пункт
по ключу и, если записи с таким ключом нет, пишет «пункт не найден в разборе» вместо
идентификатора. Тест: повторный `parse` того же текста не меняет `fields`.

Правила, которые проверяет код и тесты (не схема):

- у договора ровно шесть строк, по одной на поле прототипа, после каждого `extract`;
- `quote = document_text.text[quote_start:quote_end]` и цитата лежит в показанной
  части (R-4);
- `clause_key` — запись, чей диапазон содержит `quote_start`;
- `page = pages[0]`, `pages` по `text_span` возрастают.

## Запуск

`run.stage = 'extraction'` (`RunStage.EXTRACTION` в `docreader/stages.py`).
`run.model` — `[extraction] model`; `run.prompt_version` — `PROMPT_VERSION`;
`run.settings` — значения `[extraction]` без `base_url`, плюс `prompt_sha256`
и `served_model` (R-11). `fields` показывает запуск и его модель (FR-012).

## Состояние этапа `extraction`

```text
pending ──extract──▶ done          (поля только found / not_found, флагов нет)
        ──extract──▶ needs_review  (rejected, низкое качество страницы цитаты,
                                    непрочитанная страница в показанной части; R-8)
        ──extract──▶ failed        (ответ не по форме после повторов, текст слишком
                                    длинный, исключение при проверке)
done/needs_review/failed ──extract ID / --all──▶ то же, заново
любое ──read: text_sha256 изменился──▶ pending «текст изменён» (фича 03, уже есть)
модель недоступна / тайм-аут ──▶ без изменений (команда останавливается, код 2)
```

Запись одного договора — одна транзакция после ответа модели:

1. `stages.lock(conn, doc_id, Stage.EXTRACTION)`;
2. `DELETE FROM field_value WHERE document_id = …`;
3. `INSERT` шести строк;
4. `stages.set_state(…, Stage.EXTRACTION, state, reason, run_id)`.

При `failed` шесть строк тоже пишутся (все `failed` с причиной): прежние значения
заменяются, чтобы `fields` не показывал старое как текущее.

## Настройки `[extraction]`

`ExtractionSettings` в `docreader/config.py` — поля, значения по умолчанию и проверки —
research R-11.

## Что читает извлечение (без изменений схемы)

| Откуда | Что |
|---|---|
| `stage_status` (`structure`) | доступность (R-9) |
| `document_text` | `text`, `text_sha256` |
| `clause` | ключи, `kind`, `start`, `end_`, `source_text_sha256`; начало хвоста |
| `text_span` | страницы цитаты |
| `page_flag` | `low_recognition_quality`; `scan_unread`, `scan_no_text`, `unreadable` |

## Результаты между модулями

- `extraction_prompt.ExtractionAnswer`, `FieldAnswer` — Pydantic-схема ответа (R-3).
- `verify.check_field(field, answer, ctx) -> FieldResult` (dataclass): результат,
  значения, цитата, место, пункт, страницы, причина, предложенное. `ctx` — текст,
  конец показанной части, записи пунктов, строки `text_span` (dataclass `TextIndex`).
- `verify.document_state(results, low_quality_pages, unread_pages, shown_last_page) ->
  (state, reason)` — одна функция для состояния и причины (R-8).
- `extraction.ExtractRun` (как `parsing.ParseRun`): `run_id`, документы
  (`ExtractedDocument`: `document_id`, состояние, причина, числа found/not_found/rejected,
  имена ненайденных и отклонённых полей), пропущенные, `interrupted`, `stopped`
  (модель недоступна).
- `fieldview.FieldsView` для `fields`.

Вывод команд — `dataclass`/`TypedDict` (tech-context «Правила кода»).
