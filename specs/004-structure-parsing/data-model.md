# Data Model: Разбор структуры (фича 04, минимальная версия)

Миграция `src/docreader/migrations/0004_structure.sql`. Этап `structure` уже есть
в `stage_status` (фича 01), строки `pending` для всех документов созданы; схема
`stage_status` не меняется. Решения — в [research.md](research.md).

## Новая таблица `clause` — запись разбора

Одна строка на преамбулу, каждый раздел, каждый пункт и подпункт и хвост документа.
Заменяется целиком при повторном разборе документа.

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | text | NOT NULL, FK → `document(id)` ON DELETE CASCADE | документ |
| `key` | text | NOT NULL, не пустой; PK вместе с `document_id` | ключ в идентификаторе: `преамбула`, `5`, `5.2`, `5.2.1`, `реквизиты` (R-5) |
| `ordinal` | integer | NOT NULL, `>= 0`; UNIQUE (`document_id`, `ordinal`) | порядок в документе |
| `kind` | text | NOT NULL, `IN ('preamble', 'section', 'clause', 'tail')` | вид записи; часть документа: `preamble` — преамбула, `section`/`clause` — основной текст, `tail` — хвост |
| `number_printed` | text | NULL; NOT NULL для `section`/`clause` | номер как в тексте: `5.2.`, `5.2` |
| `number` | integer[] | NULL; NOT NULL для `section`/`clause` | номер числами: `{5,2}` |
| `depth` | smallint | NOT NULL; `= coalesce(array_length(number, 1), 0)` | 0 — преамбула, хвост; 1 — раздел; 2 — пункт; 3 и больше — подпункт |
| `parent_key` | text | NULL; FK (`document_id`, `parent_key`) → `clause` | ближайшая существующая вышестоящая запись (R-3); у разделов, преамбулы и хвоста — NULL |
| `title` | text | NULL | у раздела — текст строки заголовка после номера (может быть пустым) |
| `section_number` | integer | NULL | номер раздела записи; NULL, если строки раздела нет (заголовок не распознан) |
| `section_title` | text | NULL | заголовок раздела (копия `title` раздела) |
| `start` | integer | NOT NULL, `>= 0` | начало собственного текста в `document_text.text` |
| `end_` | integer | NOT NULL, `> start` | конец собственного текста (не включительно) |
| `first_page`, `last_page` | integer | NOT NULL, `first_page <= last_page` | страницы `start` и `end_ - 1` по `text_span` |
| `source_text_sha256` | char(64) | NOT NULL, `~ '^[0-9a-f]{64}$'` | отпечаток `document_text.text`, по которому получен разбор |
| `run_id` | bigint | NOT NULL, FK → `run(id)` ON DELETE RESTRICT | запуск разбора |

Индекс (`document_id`, `start`) — поиск записи по смещению (фичи 05, 07).

Правила, которые проверяет код и тесты (не схема):

- диапазоны записей документа не пересекаются, идут подряд и покрывают
  `[0, len(text))` целиком (FR-006, SC-003); пустая преамбула (текст начинается
  с номера) записи не получает;
- `ordinal` растёт вместе с `start`;
- у `clause` глубины 2 и больше `parent_key` — запись с номером-префиксом или NULL;
- ключи уникальны по построению (R-3): принятые номера строго растут.

Идентификатор записи для вывода и ссылок — `<document_id>/<key>`, например
`D-0001/5.2`; разбор идентификатора — функция рядом с `docreader.ids`
(`format_clause_id`, `parse_clause_id`), ошибка — `UserError` с примером вида.

## Запуск

`run.stage = 'structure'` (`RunStage.STRUCTURE` в `docreader/stages.py`; у `run.stage`
нет CHECK в схеме). `run.settings` — значения `[structure]` (`max_gap`,
`requisites_pattern`).

## Состояние этапа `structure`

```text
pending ──parse──▶ done            (находок нет)
        ──parse──▶ needs_review    (есть находки; причина — R-7)
        ──parse──▶ failed          (исключение при разборе документа; причина)
done/needs_review/failed ──parse ID / --all──▶ то же, заново
любое ──read: text_sha256 изменился──▶ pending «текст изменён» (фича 03, уже есть)
```

Запись одного документа — одна транзакция:

1. `stages.lock(conn, doc_id, Stage.STRUCTURE)`;
2. `DELETE FROM clause WHERE document_id = …`;
3. `INSERT` записей по порядку `ordinal` (родители раньше детей);
4. `stages.set_state(…, Stage.STRUCTURE, state, reason, run_id)`.

При `failed` шаги 2–3 не выполняются: прежние записи остаются, но их состояние
уже не `done`.

## Настройки `[structure]`

`StructureSettings` в `docreader/config.py` (как `ReadingSettings`):

| Поле | Тип | По умолчанию | Проверка |
|---|---|---|---|
| `max_gap` | int | 5 | 0–20 |
| `requisites_pattern` | str | `реквизит|подписи\s+сторон|адреса\s+сторон|юридические\s+адреса` | непустая, `re.compile` без ошибки |

## Что читает разбор (без изменений схемы)

| Откуда | Что |
|---|---|
| `stage_status` (`reading`) + `document_text.read_pages` | доступность документа (R-9) |
| `document_text` | `text`, `text_sha256` |
| `text_span` | строки: `start`, `end_`, `page_number`, `line_index` |
| `page_text` | `source` страницы; `lines[line_index].table` — признак строки таблицы |
| `page_flag` | `scan_unread`, `scan_no_text`, `unreadable` — непрочитанные страницы |

## Результат разбора между модулями

Чистая функция `structure.parse_lines(lines, text_length, settings, unread_pages) -> ParseResult` (dataclass):
записи (`ClauseRecord`: ключ, вид, номер, напечатанный номер, глубина, родитель,
заголовок, раздел, `start`, `end`), находки (`Finding`: вид, номера, страница) и
причина состояния. Вход — `Line` (dataclass: `start`, `end`, `page`, `text`,
`table: bool`). Номера непрочитанных страниц слой этапа (`parsing.py`) передаёт на вход; все находки
и текст причины строит `structure.py` в одном месте (R-7). Страницы записей добавляет
слой этапа. Вывод
команд — `dataclass`/`TypedDict` (tech-context «Правила кода»).
