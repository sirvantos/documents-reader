# Data Model: Распознавание страниц-сканов

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Research**: [research.md](research.md) | **Date**: 2026-11-19

Миграция `src/docreader/migrations/0003_recognition.sql`. Набросок `page_recognition`
взят из tech-context и уточнён здесь. Остальные таблицы фич 01 и 03 сохраняются,
меняются только перечисленные ниже CHECK и столбцы.

Правила связей те же (tech-context, «Договорённости между этапами»): результат
ссылается на `page` с `ON DELETE CASCADE`, на `run` — с `ON DELETE RESTRICT`.

## Новая таблица `page_recognition` — распознанная страница

Одна строка на страницу-скан. Повторное распознавание заменяет строку
(`INSERT … ON CONFLICT DO UPDATE`), а не добавляет вторую.

| Столбец | Тип | Ограничения | Смысл |
|---|---|---|---|
| `document_id` | text | PK, FK → `page` (вместе с `page_number`), CASCADE | документ |
| `page_number` | integer | PK | страница |
| `engine` | text | NOT NULL, не пустой | имя движка (`tesseract`, `apple_vision`, …) |
| `engine_version` | text | NOT NULL, не пустой | версия движка и модели, как её отдаёт адаптер |
| `dpi` | smallint | `BETWEEN 72 AND 1200` | разрешение отрисовки |
| `turn` | smallint | `IN (0, 90, 180, 270)` | доворот изображения перед распознаванием (research R-6) |
| `orientation_unknown` | boolean | NOT NULL, `DEFAULT false` | перебор доворотов не нашёл варианта выше порога (R-6, п. 4); чтение называет это в причине флага |
| `lines` | jsonb | NOT NULL, массив | распознанные строки (см. ниже) |
| `quality` | real | NULL или `[0, 1]` | средняя уверенность строк с хотя бы одной буквой или цифрой, взвешенная по их длине; строки из одних `_`, тире и точек не учитываются; `NULL`, если таких строк нет или ошибка (R-9) |
| `ink_share` | real | NULL или `[0, 1]` | доля тёмных точек изображения (R-10); `NULL` при ошибке до отрисовки |
| `result_sha256` | char(64) | NOT NULL, hex | отпечаток результата (R-11): по нему видно, изменился ли результат |
| `seconds` | real | NOT NULL, `>= 0` | время распознавания страницы, включая перебор доворотов |
| `error` | text | NULL или не пустой | ошибка распознавания страницы; если не NULL, то `lines = []` и `quality IS NULL` |
| `run_id` | bigint | NOT NULL, FK → `run`, RESTRICT | запуск распознавания |
| `recognized_at` | timestamptz | NOT NULL, `DEFAULT now()` | когда получен результат |

Элемент `lines`:

```json
{"i": 0, "text": "1.1. Подрядчик обязуется выполнить", "bbox": [51.0, 758.2, 374.1, 769.0], "confidence": 0.962}
```

- `i` — номер строки в том порядке, в каком её отдал движок. Порядок чтения
  строит чтение (R-7), здесь он не нужен;
- `text` — текст строки ровно как его отдал движок. Приведение знаков делает
  чтение (FR-010);
- `bbox` — `[left, bottom, right, top]` в координатах страницы PDF
  (неповёрнутое пространство), как в `page_text.lines[].bbox` (R-5);
- `confidence` — уверенность в [0, 1].

«Успешный результат» — строка с `error IS NULL`. Строка с пустым `lines`
и `error IS NULL` — страница, на которой текст не найден. Чтение даст ей
`empty` или `scan_no_text` по `ink_share` (R-8).

CHECK: `error IS NULL OR (jsonb_array_length(lines) = 0 AND quality IS NULL)`.

## Изменения существующих таблиц

### `stage_status`

- CHECK `stage` получает новое значение:
  `('recognition', 'reading', 'structure', 'extraction', 'checks', 'indexing')`;
- `INSERT INTO stage_status (document_id, stage) SELECT id, 'recognition' FROM
  document` — строка `pending` для каждого существующего документа;
- в коде: `Stage.RECOGNITION` первым в `docreader/stages.py`, `RunStage.RECOGNITION`.
  `tests/unit/test_stages.py` по-прежнему сверяет перечень с CHECK.

### `page_text`

- новый столбец `source text NOT NULL DEFAULT 'pdf' CHECK (source IN ('pdf',
  'recognized'))` — источник строк страницы (R-7). Существующие строки получают
  `'pdf'`;
- у строк распознанной страницы в `lines[]` появляется ключ `confidence`
  (значение из `page_recognition`), у строк PDF его нет. Остальные ключи (`i`,
  `text`, `bbox`, `role`, `column`, `table`) те же, `table` у распознанных строк
  всегда `null` (R-7).

### `page_flag`

CHECK `code` расширяется двумя кодами (R-8):

```text
'scan_unread', 'ocr_text', 'unreadable', 'maybe_not_russian', 'empty',
'reading_order_unknown', 'low_recognition_quality', 'scan_no_text'
```

В коде `quality.FLAG_NAMES` получает «низкое качество распознавания» и «текст на скане
не найден». `NEUTRAL_FLAGS` не меняется (`empty`).

### `run`

Схема не меняется. Запуск распознавания: `stage = 'recognition'`,
`model = '<engine> <engine_version>'`, `settings` = настройки запуска
с разделом `recognition` (ниже) и именем и версией движка. Если движок
не загружался, потому что распознавать было нечего, `model = NULL`.

## Состояние этапа `recognition`

Используются состояния `stage_status` фичи 01.

```text
pending ──recognize──▶ done          (у всех страниц-сканов успешный результат; без сканов — сразу)
        ──recognize──▶ needs_review  (у части страниц ошибка; причина — страницы и текст ошибки)
        ──recognize──▶ failed        (ошибка документа: копия, PDF, число страниц)
        ──Ctrl-C────▶ pending        (сохранённые страницы остаются; продолжение — следующий recognize)
done | needs_review | failed ──recognize ID [--force] [--pages]──▶ done | needs_review | failed
любое ──reclassify──▶ pending
```

Без идентификаторов `recognize` выбирает документы, где этап не `done` или есть
страница-скан без успешного результата (research R-11). Низкое качество в это
состояние не входит: это флаг чтения (R-8).

**Сброс чтения (FR-012).** Страница записана, и её `result_sha256` отличается
от прежнего (или прежнего не было), а `reading` не в `pending`. Тогда в той же
транзакции `reading` → `pending`, причина «распознанный текст изменён»,
`run_id` запуска распознавания. Этапы после чтения не трогаются: их сбросит
чтение, если изменится `text_sha256`.

## Порядок записи

**Страница** — одна транзакция (FR-013):

1. `stages.lock(conn, doc_id, Stage.RECOGNITION)`; прочитать прежний
   `result_sha256` страницы (`FOR UPDATE`);
2. `INSERT INTO page_recognition … ON CONFLICT (document_id, page_number) DO UPDATE`;
3. если отпечаток изменился — `stages.reset_stage(conn, doc_id, Stage.READING,
   "распознанный текст изменён", run_id)`.

**Документ** — после последней страницы, отдельная короткая транзакция:

1. удалить строки `page_recognition` страниц, которые больше не сканы
   (после `reclassify`);
2. `stages.set_state(conn, doc_id, Stage.RECOGNITION, state, reason, run_id)`.

Ошибка документа целиком (копия не найдена, PDF не открывается, число страниц
не совпадает) записывает `failed` с причиной отдельной транзакцией. Уже
сохранённые страницы документа остаются. Ctrl-C откатывает только текущую
страницу; состояние документа не пишется и остаётся прежним.

## Чтение распознанной страницы (изменения фичи 03)

`reading.py` для страницы вида `scan` с изображением:

1. есть успешный `page_recognition` → строки страницы строятся из `lines` (R-7):
   приведение знаков, сборка фрагментов в строки по высоте, колонки;
   `has_table = false`; `source = 'recognized'`. Флаги: `content_flags`
   (без `ocr_text`, `map_errors = 0`), `layout_flag`
   и `recognition_flags(lines, quality, ink_share, orientation_unknown, settings.recognition)`;
2. результата нет → `scan_unread`, причина «распознавание не выполнено —
   docreader recognize D-…»;
3. результат с ошибкой → `scan_unread`, причина «ошибка распознавания: <error>».

Сброс следующих этапов, `document_text`, `text_span` и состояние `reading`
работают как раньше. В `run.settings` запуска чтения теперь пишется и раздел
`recognition` с порогами, по которым поставлены флаги.

## Настройки

Новый раздел `[recognition]` в `$DOCREADER_DATA_DIR/settings.toml`,
`RecognitionSettings` в `config.py`. Разбор настроек начинает принимать строки
и логические значения (до этой фичи — только числа).

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `engine` | `"tesseract"` | движок; выбран замером 2026-11-20 (R-2, quickstart Б1). Пусто — «не выбран», `recognize` на странице-скане даёт `EnvironmentProblem` с подсказкой |
| `dpi` | 300 | разрешение отрисовки страницы, 72–1200; выбрано замером 2026-11-20 (200 хуже, 400 не лучше) |
| `try_rotations` | true | перебирать довороты 90/180/270°, если движок не определяет ориентацию и оценка ниже порога (R-6); проверено замером 2026-11-22 |
| `page_min_quality` | 0.90 | оценка страницы ниже — `low_recognition_quality` (R-9); подобрано по SC-007 2026-11-22 (было 0.80) |
| `line_min_confidence` | 0.60 | строка с уверенностью ниже считается неуверенной; при подборе 2026-11-22 на 40 страницах на результат не влиял, оставлен |
| `max_low_line_share` | 0.20 | доля неуверенных строк выше — `low_recognition_quality`; при подборе 2026-11-22 на 40 страницах на результат не влиял, оставлен |
| `blank_max_ink_share` | 0.003 | без строк и тёмных точек меньше — `empty`, иначе `scan_no_text` (R-10); не проверен: в рабочем наборе нет ни пустых страниц, ни страниц без текста (Б5, 2026-11-21), оставлен |
| `model_dir` | `""` | папка файлов модели для движков, которым она нужна; пусто — место по умолчанию у библиотеки (R-4) |

Порог флагов (`page_min_quality`, `line_min_confidence`, `max_low_line_share`,
`blank_max_ink_share`) применяет чтение. Смена порога требует `docreader read
--all`, но не повторного распознавания (FR-005, US4-2). `engine`, `dpi`
и `try_rotations` применяет распознавание. Записи уровня 2 сверяются с `engine`
и `dpi` (R-13).

Применённые значения пишутся в `run.settings` под ключом `recognition`
и в запуске распознавания, и в запуске чтения. В запуске распознавания
добавляются `engine_version` и платформа (`sys.platform`, `platform.machine()`).

## Файлы в папке данных (не в базе)

| Путь | Что | Кто пишет |
|---|---|---|
| `$DOCREADER_DATA_DIR/tmp/` | временный файл изображения, если адаптеру он нужен; удаляется сразу | адаптер движка |
| `$DOCREADER_DATA_DIR/<папка замера>/pages/*.txt`, `control.csv`, `flags.csv` | проверенные тексты, контрольные строки, ручная проверка флагов | аналитик |
| `$DOCREADER_DATA_DIR/reports/recognition-eval-*.json`, `*.csv` | цифры замера с `run_id` и настройками — до таблицы результатов фичи 02 (R-12) | `recognize-eval` |
| `$DOCREADER_DATA_DIR/reports/recognition-*.csv` | отчёт о распознавании | `recognize-report --csv` |

## Удаление документа

`remove` каскадом через `page` удаляет и `page_recognition`. Записи `run`
остаются (фича 01, FR-011).
