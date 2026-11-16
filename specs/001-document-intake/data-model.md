# Data Model: Приём документов и реестр (фича 01)

**Дата**: 2026-11-16 · **План**: [plan.md](plan.md)

Основа — набросок модели данных в `docs/tech-context.md` (сущности `document`, `page`,
`stage_status`, `run`). Расширения относительно наброска отмечены **[+]**; все они
перенесены в tech-context.

Хранилище — PostgreSQL. Миграция `0001_intake.sql`. Время — `timestamptz`.

---

## Таблицы

### `run` — запуск обработки (FR-012)

| Поле | Тип | Ограничения | Смысл |
|---|---|---|---|
| `id` | `bigint` | PK, identity | номер запуска |
| `stage` | `text` | NOT NULL | этап: для этой фичи `intake` |
| `started_at` | `timestamptz` | NOT NULL, default `now()` | начало |
| `finished_at` | `timestamptz` | NULL | окончание; пусто — запуск прерван или идёт |
| `code_version` | `text` | NOT NULL | `git describe --always --dirty` или версия пакета |
| `model` | `text` | NULL | модель; в фиче 01 всегда пусто |
| `prompt_version` | `text` | NULL | версия подсказки; в фиче 01 всегда пусто |
| `settings` | `jsonb` | NOT NULL | применённые настройки и команда (`{"command": "add", "page_kinds": {...}, ...}`) |
| `label` | `text` | NULL | метка пользователя (`--label`) |

Записи не удаляются никогда, в том числе при удалении документов (уточнение спецификации
от 2026-11-15). Ссылки на `run` — с `ON DELETE RESTRICT`.

### `document_counter` [+] — счётчик идентификаторов

| Поле | Тип | Ограничения |
|---|---|---|
| `singleton` | `boolean` | PK, default `true`, CHECK (`singleton`) |
| `last_seq` | `integer` | NOT NULL, default 0, CHECK (`last_seq >= 0`) |

Одна строка. Значение только растёт (R-3).

### `document` — договор (FR-003…FR-006)

| Поле | Тип | Ограничения | Смысл |
|---|---|---|---|
| `id` | `text` | PK, CHECK (`id ~ '^D-[0-9]{4,}$'`) | `D-0001` |
| `seq` | `integer` | NOT NULL, UNIQUE | номер внутри идентификатора |
| `sha256` | `char(64)` | NOT NULL, UNIQUE, CHECK (`sha256 ~ '^[0-9a-f]{64}$'`) | отпечаток содержимого |
| `original_name` | `text` | NOT NULL | исходное имя файла (без пути) |
| `source_path` | `text` | NOT NULL | [+] абсолютный путь при добавлении — только для справки |
| `copy_path` | `text` | NOT NULL | путь копии относительно папки данных: `originals/<sha256>.pdf` |
| `size_bytes` | `bigint` | NOT NULL, CHECK (`> 0`) | [+] размер файла |
| `page_count` | `integer` | NOT NULL, CHECK (`> 0`) | число страниц |
| `added_at` | `timestamptz` | NOT NULL, default `now()` | дата добавления |
| `note` | `text` | NULL | заметка пользователя |
| `parent_document_id` | `text` | NULL, FK → `document(id)` ON DELETE SET NULL, CHECK (`parent_document_id IS NULL`) | зарезервировано; CHECK снимается фичей, которая начнёт его заполнять |
| `intake_run_id` | `bigint` | NOT NULL, FK → `run(id)` | [+] запуск, которым добавлен документ |

Индекс: `lower(original_name)` — для предупреждения о совпадении имён.

### `page` — страница (FR-007)

| Поле | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | `text` | FK → `document(id)` ON DELETE CASCADE | |
| `page_number` | `integer` | CHECK (`>= 1`) | с единицы |
| `kind` | `text` | NOT NULL, CHECK (`kind IN ('text','scan','scan_with_text')`) | вид страницы |
| `char_count` | `integer` | NOT NULL, CHECK (`>= 0`) | [+] показатель R-2 |
| `image_coverage` | `real` | NOT NULL, CHECK (`0 <= x <= 1`) | [+] показатель R-2 |
| `invisible_text_share` | `real` | NULL, CHECK (`0 <= x <= 1`) | [+] диагностика R-2; NULL, если текстовых объектов нет |
| `kind_run_id` | `bigint` | NOT NULL, FK → `run(id)` | [+] запуск, которым определён вид (добавление или `reclassify`) |

PK: (`document_id`, `page_number`).

Отображение вида: `text` — «готовый текст», `scan` — «скан», `scan_with_text` —
«скан со встроенным текстом».

### `stage_status` — состояние этапа (FR-008)

| Поле | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | `text` | FK → `document(id)` ON DELETE CASCADE | |
| `stage` | `text` | CHECK (`stage IN ('reading','structure','extraction','checks','indexing')`) | этап |
| `state` | `text` | NOT NULL, default `'pending'`, CHECK (`state IN ('pending','done','needs_review','failed')`) | состояние |
| `reason` | `text` | NULL; CHECK (`state IN ('pending','done') OR (reason IS NOT NULL AND btrim(reason) <> '')`) | причина |
| `run_id` | `bigint` | NULL, FK → `run(id)` | запуск этапа, который установил состояние; NULL, пока этап не запускался |
| `updated_at` | `timestamptz` | NOT NULL, default `now()` | |

PK: (`document_id`, `stage`).

Перечень этапов из уточнения спецификации: чтение (03), структура (04), извлечение (05),
проверки (06), индексация (07). Отображение: «ожидает», «готово», «требует просмотра»,
«ошибка». Новый этап добавляется миграцией своей фичи: расширяет CHECK и вставляет
строки `pending` для существующих документов. Перечень этапов в коде — одна константа,
совпадающая с CHECK.

### `deletion_log` [+] — журнал удалений (FR-011)

| Поле | Тип | Ограничения |
|---|---|---|
| `id` | `bigint` | PK, identity |
| `document_id` | `text` | NOT NULL (без FK — документа уже нет) |
| `original_name` | `text` | NOT NULL |
| `sha256` | `char(64)` | NOT NULL |
| `deleted_at` | `timestamptz` | NOT NULL, default `now()` |

### `schema_migrations` [+] — служебная

| Поле | Тип |
|---|---|
| `version` | `text` PK (`0001_intake`) |
| `applied_at` | `timestamptz` NOT NULL default `now()` |

---

## Связи

```
run 1 ──< document.intake_run_id
run 1 ──< page.kind_run_id
run 1 ──< stage_status.run_id
document 1 ──< page            (CASCADE)
document 1 ──< stage_status    (CASCADE)
document 0..1 ── parent_document_id (всегда пусто)
deletion_log — без связей
```

**Правило для последующих фич** (записано в tech-context): каждая таблица результатов
по документу ссылается на `document(id)` с `ON DELETE CASCADE`, а на `run(id)` —
без каскада. Тогда `remove` удаляет «все результаты по документу» (FR-011) одним
`DELETE FROM document`, а записи о запусках сохраняются.

---

## Жизненный цикл и переходы

**Документ**

```
(нет) ──add──> зарегистрирован ──remove (подтверждено)──> (нет) + запись в deletion_log
                     │
                     └─ reclassify: меняется page.kind
```

Повторный `add` того же содержимого — без изменений («уже есть»). После `remove` тот же
файл добавляется заново с новым идентификатором (FR-003, уточнение спецификации).

**Состояние этапа**

```
pending ──(этап 03…07)──> done | needs_review(reason) | failed(reason)
любое ──(reclassify изменил вид хотя бы одной страницы документа)──> pending
```

Сброс в `pending` при `reclassify` — частный случай договорённости tech-context «повторный
запуск этапа помечает результаты следующих этапов как устаревшие»: вид страницы влияет на
чтение (03), поэтому все этапы документа нужно пройти заново.

---

## Правила проверки (из требований)

| Правило | Где обеспечивается |
|---|---|
| Один документ на содержимое (FR-005) | UNIQUE `document.sha256` |
| Идентификатор не используется повторно (FR-003) | `document_counter` только растёт |
| Причина обязательна для `needs_review`, `failed` (FR-008) | CHECK в `stage_status` |
| Копия не меняется (FR-004) | файл 0444; `verify` сверяет SHA-256 |
| Нет частично добавленных документов (крайний случай) | копия до транзакции, документ + страницы + состояния — одна транзакция |
| `parent_document_id` всегда пуст | CHECK |
| Каждый файл ровно в одной группе отчёта (FR-009) | код приёма; группа — перечисление `added` / `existing` / `rejected` |
