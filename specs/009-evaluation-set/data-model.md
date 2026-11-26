# Data Model: эталонный набор и таблица результатов (фича 02)

Миграция `src/docreader/migrations/0007_evaluation.sql`. Новых этапов в `stage_status`
нет: сравнение — не этап конвейера, оно читает результаты этапов и ничего в них
не меняет. Таблицы фич 01–08 только читаются: `document`, `document_text`, `text_span`,
`page_text`, `clause`, `field_value`, `run`, `passage` (research R-7, R-9, R-12).

Эталон по документу ссылается на `document(id)` с `ON DELETE CASCADE` (договорённость
tech-context: удаление документа убирает его результаты). Таблица результатов на
документ **не** ссылается: её записи — история замеров и должны оставаться целыми
(FR-014); `eval_case.document_id` — текст без внешнего ключа.

## Перечисления (одно место в коде — `StrEnum`, совпадают с CHECK)

| Имя | Значения | Где |
|---|---|---|
| `GoldState` | `value`, `absent` | `gold_field.state`, `gold_blind.state` |
| `GoldPath` | `agree` (проверено, совпало), `chosen` (выбрано из двух), `typed` (вписано на странице), `absent_marked` (отметка «отсутствует» на странице), `template` (из шаблона) | `gold_field.path` |
| `LoadKind` | `review`, `template`, `blind`, `questions` | `gold_load.kind` |
| `QuestionKind` | `text`, `table`, `both` | `gold_question.kind` |
| `QuestionOrigin` | `own`, `set08`, `set09`, `generated` | `gold_question.origin` |
| `EvalStage` | `fields`, `rules`, `search_plain`, `search_rerank`, `gold_blind` | `eval_result.stage` |
| `Outcome` | `correct`, `wrong`, `missed`, `invented`, `unlabeled`, `no_result`, `manual` | `eval_case.outcome` для полей |
| `BlindOutcome` | `same`, `differs`, `blind_only`, `reviewed_only` | `eval_case.outcome` для `gold_blind` |

## `gold_load` — каждая загрузка файла

| Столбец | Тип | Правило |
|---|---|---|
| `id` | bigint identity PK | |
| `kind` | text | CHECK `LoadKind` |
| `file_name` | text | путь относительно папки данных, если файл в ней, иначе только имя |
| `file_sha256` | char(64) | отпечаток загруженного файла (для справки) |
| `loaded_at` | timestamptz | `now()` |
| `gold_sha256` | char(64) | версия эталона полей после загрузки (для `questions` — версия вопросов) |
| `counts` | jsonb | итог загрузки: добавлено, изменено, убрано, ошибок вида, по полям |

## `gold_field` — эталон полей (строка = размеченная пара)

| Столбец | Тип | Правило |
|---|---|---|
| `document_id` | text | FK `document(id)` ON DELETE CASCADE |
| `field` | text | имя поля каталога (проверяется кодом по `catalog.CATALOG`; CHECK не ставится: каталог растёт без миграции) |
| `state` | text | CHECK `GoldState` |
| `values_text` | text[] | варианты как записаны; пусто при `absent` |
| `values_normalized` | text[] | приведённые варианты той же длины (R-4) |
| `path` | text | CHECK `GoldPath` |
| `clause_key` | text NULL | пункт цитаты, по которой значение подтверждено (страница проверки), или выбранного места; для шаблона — NULL |
| `load_id` | bigint | FK `gold_load(id)` ON DELETE RESTRICT |
| | | PK (`document_id`, `field`); CHECK: `state = 'absent'` ⇔ массивы пусты; CHECK: длины массивов равны |

Неразмеченная пара — строки нет. Версия эталона полей —
`sha256` от строк, отсортированных по (`document_id`, `field`), в виде
`document_id \t field \t state \t values_normalized через \x1f` (research R-5).

## `blind_pick` и `gold_blind` — слепой контроль

`blind_pick`: `document_id` (PK, FK `document` CASCADE), `picked_at`.

`gold_blind`: те же столбцы, что `gold_field`, без `path` и `clause_key`; PK
(`document_id`, `field`); `load_id` → `gold_load` (вид `blind`). В эталон не входит.

## `gold_question` — эталонные вопросы

| Столбец | Тип | Правило |
|---|---|---|
| `key` | text PK | `Q-` + 10 hex SHA-256 от `document_id` и текста в форме сравнения `textnorm` (R-11) |
| `document_id` | text | FK `document(id)` ON DELETE CASCADE |
| `text` | text | непустой |
| `kind` | text | CHECK `QuestionKind`, по умолчанию `text` |
| `has_answer` | boolean | |
| `false_premise` | boolean | по умолчанию false |
| `expected` | text[] | ожидаемые значения ответа (`contains`, значение эталона); может быть пусто |
| `clause_keys` | text[] | правильные пункты (ключи записей разбора); пусто ⇔ `has_answer = false` |
| `origin` | text | CHECK `QuestionOrigin` |
| `source_file` | text | путь файла относительно папки данных (по нему повторная загрузка заменяет вопросы файла) |
| `load_id` | bigint | FK `gold_load(id)` |

Версия вопросов — `sha256` по строкам, отсортированным по `key`.

## `eval_result` — запись таблицы результатов

| Столбец | Тип | Правило |
|---|---|---|
| `id` | bigint identity PK | номер записи в командах (`eval show 12`) |
| `created_at` | timestamptz | |
| `label` | text | метка аналитика; может быть пустой |
| `stage` | text | CHECK `EvalStage` |
| `provenance` | jsonb | чем получены сравниваемые результаты (research R-13) |
| `gold_sha256` | char(64) NULL | версия эталона полей (для полей, правил, слепого контроля) |
| `questions_sha256` | char(64) NULL | версия вопросов (для поиска) |
| `reviewed_share` | numeric NULL | доля строк эталона с путём из страницы проверки на момент записи |
| `blind_summary` | jsonb NULL | итог последнего слепого контроля: пар, расхождений, из них при подтверждённом значении системы, номер записи `gold_blind` |
| `metrics` | jsonb | числа и доли по полям и в целом (поля) или доли и медиана (поиск) |
| `review_file` | text NULL | путь файла разбора относительно папки данных |
| `from_file` | text NULL | путь файла результатов, если сравнивались результаты из файла (FR-023) |

## `eval_case` — исход каждого случая записи

| Столбец | Тип | Правило |
|---|---|---|
| `result_id` | bigint | FK `eval_result(id)` ON DELETE CASCADE |
| `case_key` | text | `D-0001/contract_number` для полей; ключ вопроса для поиска |
| `document_id` | text | без внешнего ключа |
| `field` | text NULL | для полей и слепого контроля |
| `question_key` | text NULL | для поиска |
| `outcome` | text NULL | `Outcome` / `BlindOutcome`; для поиска — NULL |
| `place` | integer NULL | для поиска: место правильного пункта, NULL — «не найден» |
| `flags` | text[] | `rejected`, причина `no_result` (`not_run`, `failed`, `stale`, `not_extracted`), `excluded` (вопрос без ответа или вида `table`) |
| `gold_sha` | char(16) | отпечаток эталонного значения пары или вопроса на момент записи (группа «из-за эталона», R-13) |
| | | PK (`result_id`, `case_key`) |

Метрики записи пересчитываются из `eval_case` (SC-004): `metrics` — сохранённая копия,
тест проверяет, что она совпадает с пересчётом.

## Состояния и переходы

- Пара эталона: нет строки (не размечено) ⇄ `value` ⇄ `absent` — только загрузкой
  файла (R-6); убрать значение — загрузить файл с пустой ячейкой, с `--yes`.
- `blind_pick` меняется только `eval blind pick --again`; `gold_blind` — загрузкой
  слепой разметки (замена в пределах охвата, как у эталона).
- `eval_result` и `eval_case` только добавляются; не меняются и не удаляются командами
  фичи (история замеров).

## Что не хранится в базе

Страница проверки, картинки, файл ответов страницы, шаблоны, сгенерированные вопросы,
файлы разбора и выгрузки — файлы в папке данных (`eval/`, `questions/`). Значения правил
(R-8) и места поиска не хранятся отдельно: правила считаются на лету, места поиска —
в `eval_case.place`.
