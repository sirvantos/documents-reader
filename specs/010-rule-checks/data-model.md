# Data Model: Проверки правилами и статусы полей

Миграция `0008_checks.sql`. Таблицы фич 01–05 и 02 только читаются, кроме общих: запуск
в `run`, состояние этапа в `stage_status`, запись отчёта в `eval_result` / `eval_case`;
`field_value` и `gold_field` не меняются (research R-8).

## Перечисления (`StrEnum` в коде, CHECK в базе)

| Перечисление | Значения | Где |
|---|---|---|
| `RuleOutcome` | `passed`, `violated`, `not_applied` | `field_check.outcome` |
| `FieldStatus` | `accepted`, `needs_review`, `rejected`, `not_found` | `field_status.status` |
| `DecisionKind` | `confirm`, `correct`, `absent` | `field_decision.kind` |
| `EvalStage` | + `checks` | `eval_result.stage` (CHECK заменяется) |
| `CheckOutcome` | `queued_wrong`, `queued_right`, `accepted_wrong`, `accepted_right` | `eval_case.outcome` этапа `checks` (CHECK заменяется: исходы фичи 02 и эти четыре; research R-10) |

Пометки (`field_status.flags`, массив): `document_needs_review`, `system_changed`,
`human_confirmed`, `human_corrected`, `human_absent`. Коды причин правил — research R-2.

## `field_check` — исход каждого правила

| Столбец | Тип | Правило |
|---|---|---|
| `document_id` | text | FK `document(id)` ON DELETE CASCADE |
| `field` | text | одно из шести полей прототипа (CHECK как у `field_value`) |
| `rule` | text | код правила (`amount_words`, …) |
| `outcome` | text | `RuleOutcome` |
| `reason` | text NULL | код причины; NULL у `passed` |
| `run_id` | bigint | FK `run(id)` — запуск проверок |

PK (`document_id`, `field`, `rule`). Запуск `check` по договору заменяет все его строки
в одной транзакции с `field_status`.

## `field_status` — статус поля

| Столбец | Тип | Правило |
|---|---|---|
| `document_id` | text | FK `document(id)` ON DELETE CASCADE |
| `field` | text | одно из шести полей |
| `status` | text | `FieldStatus` |
| `reasons` | text[] | коды причин (нарушенные правила или причина извлечения); пустой у `accepted` без решения |
| `flags` | text[] | пометки (выше) |
| `extraction_run_id` | bigint | `field_value.run_id`, по которому вычислен статус (research R-7) |
| `checks_version` | text | `CHECKS_VERSION` |
| `run_id` | bigint | FK `run(id)` — запуск проверок |

PK (`document_id`, `field`). Устарел, если `extraction_run_id` ≠ текущий `field_value.run_id`
или `checks_version` ≠ текущей.

## `field_decision` — решение аналитика

| Столбец | Тип | Правило |
|---|---|---|
| `document_id` | text | FK `document(id)` ON DELETE CASCADE |
| `field` | text | одно из шести полей |
| `kind` | text | `DecisionKind` |
| `value_text` | text NULL | вписанное значение; только у `correct` |
| `value_normalized` | text NULL | приведённое по виду поля; только у `correct` |
| `clause_key` | text NULL | пункт, если аналитик указал; только у `correct` |
| `system_result` | text | `field_value.result` на карточке сборки, по которой принято решение (`cards.json`, research R-9) |
| `system_normalized` | text NULL | `field_value.value_normalized` на той же карточке |
| `answers_sha256` | char(64) | отпечаток загруженного файла ответов |
| `decided_at` | timestamptz | время загрузки |

PK (`document_id`, `field`); CHECK: `correct` ⇔ `value_text` и `value_normalized` не NULL.
Новая загрузка ответа по той же паре заменяет строку. Эталон фичи 02 (`gold_field`)
не читается и не пишется (уточнение 2026-11-27).

## `run` и `stage_status`

`run.stage = 'checks'` (`RunStage.CHECKS`); настройки запуска — `[checks]` и
`CHECKS_VERSION`. `stage_status` этапа `checks` (уже есть с фичи 01): `done` или
`needs_review` после `check` (research R-7).

## Связи и жизненный цикл

```text
field_value (фича 05) ──run_id──► field_status.extraction_run_id   (устаревание)
field_check ─┐
             ├─► field_status ◄── field_decision (решение; system_* — снимок значения системы)
check report: field_status (без решений) × gold_field (фича 02) ─► eval_result/eval_case (этап checks)
```

Повторный `extract` меняет `field_value.run_id` → статус устарел → следующий `check`
пересчитывает; если `system_*` решения ≠ новому значению системы — пометка
`system_changed`, статус «требует просмотра» (research R-6, строка 2). Удаление договора
удаляет его строки во всех трёх таблицах.
