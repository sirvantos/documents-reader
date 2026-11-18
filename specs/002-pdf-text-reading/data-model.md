# Data Model: Чтение текста из PDF и проверка его качества

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-11-17

Миграция `src/docreader/migrations/0002_reading.sql`. Таблицы фичи 01 (`document`,
`page`, `stage_status`, `run`) не меняются: этап `reading` уже есть в перечне
`stage_status`, строки `pending` для него создаются при приёме документа.

Правила связей (tech-context, «Договорённости между этапами»): результаты по документу
ссылаются на `document`/`page` с `ON DELETE CASCADE`, на `run` — с `ON DELETE RESTRICT`.

## Таблицы

### `page_text` — прочитанная страница

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | text | PK, FK → `page` (вместе с `page_number`), CASCADE | документ |
| `page_number` | integer | PK | страница |
| `rotation` | smallint | `IN (0, 90, 180, 270)` | поворот страницы `/Rotate` |
| `width`, `height` | real | `> 0` | размер страницы в pt (CropBox) |
| `lines` | jsonb | NOT NULL, массив | строки страницы в порядке чтения (см. ниже) |
| `has_table` | boolean | NOT NULL | на странице найдена таблица (FR-007) |
| `run_id` | bigint | NOT NULL, FK → `run`, RESTRICT | запуск чтения |

Элемент `lines`:

```json
{
  "i": 0,
  "text": "1.1. Подрядчик обязуется выполнить строительно-мон-",
  "bbox": [51.0, 758.2, 374.1, 769.0],
  "role": "body",
  "column": null,
  "table": null
}
```

- `i` — номер строки на странице, с 0, в порядке чтения;
- `text` — текст строки после приведения знаков (research R-5), до склейки переносов;
- `bbox` — `[left, bottom, right, top]` в координатах страницы PDF (неповёрнутое
  пространство, как отдаёт PDFium) — по ним строится подсветка;
- `role` — `body`, `header`, `footer`, `page_number`, `rotated`;
- `column` — `1` или `2` в области двух колонок, иначе `null`;
- `table` — `{"t": 0, "row": 2, "cell": 1}` для строк внутри таблицы, иначе `null`.

Страница с флагом `scan_unread` или `empty` получает строку `page_text`
с пустым `lines`, чтобы отчёт и `text` видели все страницы (SC-002).

### `page_flag` — флаги страницы

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id`, `page_number` | | PK, FK → `page_text`, CASCADE | страница |
| `code` | text | PK; `IN ('scan_unread', 'ocr_text', 'unreadable', 'maybe_not_russian', 'empty', 'reading_order_unknown')` | флаг (FR-006) |
| `reason` | text | NOT NULL, не пустой | пояснение с числами, например «4 буквы не русского алфавита: Қ, Ә, Ұ, І» |

Отдельная таблица, а не поле `jsonb`: отчёт (FR-011) считает флаги простым
`GROUP BY`, а `CHECK` не даёт записать неизвестный код.

### `document_text` — очищенный текст документа

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | text | PK, FK → `document`, CASCADE | документ |
| `text` | text | NOT NULL | очищенный текст (research R-4) |
| `text_sha256` | char(64) | NOT NULL | отпечаток текста: по нему видно изменение при повторном чтении (FR-012) |
| `read_pages` | integer | NOT NULL, `>= 0` | число страниц, давших хотя бы одну строку |
| `run_id` | bigint | NOT NULL, FK → `run`, RESTRICT | запуск чтения |

`read_pages = 0` ⇔ состояние «нет прочитанного текста»: документ недоступен
следующим этапам.

### `text_span` — соответствие очищенного текста строкам

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | text | PK, FK → `document_text`, CASCADE | документ |
| `start` | integer | PK, `>= 0` | начало диапазона в `document_text.text` |
| `end_` | integer | `> start` | конец диапазона (не включительно) |
| `page_number` | integer | NOT NULL | страница |
| `line_index` | integer | NOT NULL, `>= 0` | `i` строки в `page_text.lines` |

Диапазоны не пересекаются и идут по возрастанию. Две строки, склеенные по переносу,
дают два диапазона, стоящих вплотную. Индекс `(document_id, end_)` для поиска
диапазонов, пересекающих фрагмент.

## Состояние этапа `reading`

Используются состояния `stage_status` фичи 01.

```text
pending ──read──▶ done            (нет флагов, кроме empty)
        ──read──▶ needs_review    (есть флаги или нет прочитанного текста; причина обязательна)
        ──read──▶ failed          (исключение; причина — текст ошибки)
failed  ──read──▶ done | needs_review | failed
done | needs_review ──read ID / read --all──▶ done | needs_review | failed
```

Без идентификаторов `read` выбирает `pending` и `failed` (уточнение 1).

**Следующие этапы** (`structure`, `extraction`, `checks`, `indexing`): при повторном
чтении, если `text_sha256` изменился, их строки в состоянии, отличном от `pending`,
переходят в `pending` с причиной «текст изменён» и `run_id` запуска чтения (уточнение 2).

**Доступность следующим этапам** (FR-008): этап `reading` в `done` или `needs_review`
и `document_text.read_pages > 0`. Фича 04 выбирает документы по этому правилу.

## Порядок записи результата документа

Одна транзакция на документ (принцип VI, повторный запуск не создаёт дубликатов):

1. прочитать прежний `document_text.text_sha256` (`FOR UPDATE`);
2. `DELETE FROM page_text WHERE document_id = …` (каскадом уходят `page_flag`);
   `DELETE FROM text_span WHERE document_id = …`;
3. `INSERT` `page_text`, `page_flag`; `INSERT … ON CONFLICT (document_id) DO UPDATE`
   `document_text`; `INSERT` `text_span`;
4. при изменении отпечатка — сбросить следующие этапы;
5. обновить `stage_status` этапа `reading`.

Ошибка внутри — откат транзакции документа, отдельная короткая транзакция ставит
`failed` с причиной.

## Настройки

Раздел `[reading]` в `$DOCREADER_DATA_DIR/settings.toml`; значения по умолчанию:

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `header_band` | 0.1 | доля высоты страницы сверху и снизу, где ищутся колонтитулы |
| `header_min_share` | 0.5 | строка — колонтитул, если повторяется больше чем на этой доле страниц |
| `header_min_pages` | 3 | меньше страниц — колонтитулы не ищутся |
| `non_russian_min_letters` | 3 | порог флага `maybe_not_russian` |
| `unreadable_min_letter_share` | 0.6 | порог доли букв и цифр |
| `unreadable_max_bad_share` | 0.05 | порог доли знаков с ошибкой кодировки |
| `unreadable_max_vowelless_share` | 0.4 | порог доли «слов» без гласных |
| `column_min_lines` | 3 | минимум строк области двух колонок |
| `column_min_gap` | 20.0 | минимальный разрыв между колонками, pt |
| `column_gap_tolerance` | 15.0 | допуск положения разрыва, pt |
| `wide_gap_factor` | 2.5 | разрыв в строке не уже `max(column_min_gap, wide_gap_factor × высота строки)` делит строку на части; более узкий — пробел между словами (выравнивание по ширине). Части считаются для колонок и флага `reading_order_unknown` (исправление 2026-11-18) |
| `rotated_min_angle` | 5.0 | угол знака, начиная с которого текст считается повёрнутым, градусы |

Порог `text_min_chars` (фича 01) используется и здесь: короче — признаки нечитаемого
текста не считаются. Все применённые значения и версия словаря `pymorphy3`
записываются в `run.settings` под ключом `reading`.
