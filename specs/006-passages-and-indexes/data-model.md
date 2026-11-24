# Data Model: Нарезка, метки и индексы (фича 07, минимальная версия)

Миграция `src/docreader/migrations/0006_passages.sql`. Этап `indexing` уже есть
в `stage_status` (фича 01), строки `pending` для всех документов созданы; схема
`stage_status` не меняется. Решения — в [research.md](research.md).

## Расширение

`CREATE EXTENSION IF NOT EXISTS vector` — первая строка миграции (R-10).

## Новая таблица `passage` — отрывок и запись индекса по словам

Одна строка на запись разбора с собственным текстом (R-3). Заменяется целиком
при повторной индексации документа. Текст не копируется: он равен
`substring(document_text.text from start + 1 for end_ - start)`.

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | text | NOT NULL, FK → `document(id)` ON DELETE CASCADE | документ |
| `clause_key` | text | NOT NULL, не пустой; PK вместе с `document_id` | ключ записи разбора: `преамбула`, `5.2`, `реквизиты` |
| `ordinal` | integer | NOT NULL, `>= 0`; UNIQUE (`document_id`, `ordinal`) | порядок отрывков в документе |
| `part` | text | NOT NULL, `IN ('preamble', 'main', 'tail')` | часть документа: преамбула, основной текст (раздел, пункт, подпункт), хвост (реквизиты) |
| `start` | integer | NOT NULL, `>= 0` | начало текста отрывка в `document_text.text` |
| `end_` | integer | NOT NULL, `> start` | конец (не включительно) |
| `first_page`, `last_page` | integer | NOT NULL, `1 <= first_page <= last_page` | страницы `start` и `end_ - 1` по `text_span` |
| `label` | text | NOT NULL, не пустой | метка (R-4) |
| `lemmas` | text | NOT NULL, не пустой | метка и текст в словарных формах (R-5) |
| `tsv` | tsvector | GENERATED ALWAYS AS (`to_tsvector('simple', lemmas)`) STORED; индекс GIN | индекс по словам |
| `source_text_sha256` | char(64) | NOT NULL, `~ '^[0-9a-f]{64}$'` | отпечаток `document_text.text`, по которому нарезано |
| `structure_run_id` | bigint | NOT NULL, FK → `run(id)` ON DELETE RESTRICT | запуск разбора, чьи записи нарезаны (R-7) |
| `run_id` | bigint | NOT NULL, FK → `run(id)` ON DELETE RESTRICT | запуск индексации |

Внешнего ключа на `clause` нет (как у `field_value`): `parse` переписывает записи
документа через DELETE + INSERT. Актуальность проверяют читатели (R-7).

Правила, которые проверяет код и тесты (не схема): отрывки документа не пересекаются,
`ordinal` растёт вместе с `start`, покрытие SC-001 (R-3).

## Новая таблица `passage_vector` — запись индекса по смыслу

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id`, `clause_key` | text | NOT NULL; FK (`document_id`, `clause_key`) → `passage` ON DELETE CASCADE | отрывок |
| `model` | text | NOT NULL, не пустой; PK (`document_id`, `clause_key`, `model`) | модель (`[embedding] model`) |
| `embedding` | vector | NOT NULL | вектор, длина 1 (R-1) |
| `dims` | integer | NOT NULL, `> 0`, `= vector_dims(embedding)` | размерность |
| `input_chars` | integer | NOT NULL, `> 0` | знаков метки и текста, ушедших в модель |
| `truncated` | boolean | NOT NULL | вход обрезан по `max_chars` (R-6) |
| `run_id` | bigint | NOT NULL, FK → `run(id)` ON DELETE RESTRICT | запуск индексации |

Индекса ANN нет (R-6). Удаление документа удаляет его отрывки и векторы каскадом
(US2-5); записи `run` остаются.

## Запуск

`run.stage = 'indexing'` (`RunStage.INDEXING` в `docreader/stages.py`; у `run.stage`
нет CHECK). `run.model` — `[embedding] model`; `run.settings` — значения `[embedding]`
и `served_model`, `dims` из `check()`; `run.label` — `--label`.

## Состояние этапа `indexing`

```text
pending ──index──▶ done            (векторы построены, обрезки нет)
        ──index──▶ needs_review    (обрезанный вход или нет отрывков; причина — R-8)
        ──index──▶ failed          (ошибка модели или исключение на документе; причина)
done/needs_review/failed ──index ID / --all / разбор новее──▶ то же, заново
любое ──read: text_sha256 изменился──▶ pending «текст изменён» (фича 03, уже есть)
```

Модель недоступна — состояние не меняется (R-8).

## Что читает этап

`document_text` (текст, отпечаток), `clause` (ключ, вид, глубина, `start`, `end_`,
`section_number`, `section_title`, `source_text_sha256`, `run_id`), `text_span`
(страницы), `stage_status` (`structure`, `indexing`). Флаги страниц и поля фичи 05
в минимальной версии не читаются.
