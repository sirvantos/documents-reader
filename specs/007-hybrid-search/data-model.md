# Data model: гибридный поиск (фича 08, минимальная версия)

Новых таблиц и миграции нет: поиск только читает индексы фичи 07
([data-model фичи 07](../006-passages-and-indexes/data-model.md)) и ничего не пишет
(research R-10). Ниже — что читается и какие значения живут в памяти.

## Что читается

| Таблица | Столбцы | Зачем |
|---|---|---|
| `passage` | `document_id`, `clause_key`, `ordinal`, `start`, `end_`, `first_page`, `last_page`, `label`, `lemmas`, `source_text_sha256`, `structure_run_id` | кандидаты по словам (BM25 по `lemmas`, R-1), вывод |
| `passage_vector` | `document_id`, `clause_key`, `model`, `embedding` | кандидаты по смыслу (R-3) |
| `document_text` | `text`, `text_sha256` | текст отрывка `substr(text, start + 1, end_ - start)`; актуальность |
| `clause` | `document_id`, `run_id` | актуальность (запуск разбора, R-6) |
| `document` | `id` | неизвестный договор (R-5); число договоров без актуальных отрывков |

**Актуальный отрывок** (R-6): `p.source_text_sha256 = t.text_sha256` и
`p.structure_run_id` равен запуску текущих записей разбора договора — то же правило,
что `indexing.passages_current` фичи 07, записанное условием на весь набор.

## Значения в памяти

### `SearchSettings` (раздел `[search]`, R-9)

| Поле | Тип | По умолчанию | Проверка |
|---|---|---|---|
| `candidates` | int | 30 | 1…500 |
| `rrf_k` | int | 60 | 1…1000 |
| `rerank_candidates` | int | 30 | 1…200 |
| `results` | int | 8 | 1…200, не больше `rerank_candidates` |

### `RerankerSettings` (раздел `[reranker]`, R-9)

| Поле | Тип | По умолчанию | Проверка |
|---|---|---|---|
| `enabled` | bool | true | — |
| `base_url` | str | `http://127.0.0.1:8082/v1` | только эта машина (`is_local_model_url`, принцип I) |
| `model` | str | `bge-reranker-v2-m3` | не пустая |
| `timeout_s` | int | 60 | 1…3600 |
| `max_chars` | int | 16000 | 1…1 000 000 |

### `Candidate`

| Поле | Тип | Смысл |
|---|---|---|
| `document_id` | str | `D-0015` |
| `clause_key` | str | `2.2.1`, `preamble`, `tail` |
| `ordinal` | int | порядок отрывка в договоре (для равных оценок) |
| `word_place` | int \| None | место в поиске по словам, с 1; `None` — не найден этим способом |
| `vector_place` | int \| None | место в поиске по смыслу |
| `fused_place` | int | место после слияния |

### `Hit` (результат)

`Candidate` плюс `label`, `text`, `first_page`, `last_page`, `rerank_score`
(float \| None — реранкер выключен) и `place` — итоговое место с 1. Идентификатор
пункта для вывода — `D-0015/2.2.1` (`ids.format_clause_id`).

### `SearchResult`

| Поле | Тип | Смысл |
|---|---|---|
| `query` | str | как введён |
| `document_id` | str \| None | ограничение договором |
| `reranked` | bool | реранкер применён |
| `hits` | list[Hit] | по `place` |
| `word_candidates`, `vector_candidates` | int | сколько нашёл каждый способ |
| `warnings` | list[str] | обрезанный запрос, договоры без актуальных отрывков, «по словам ничего не найдено»; без текста договоров |
| `embedding_model`, `reranker_model` | str, str \| None | `served_model` из `check()` |
| `seconds` | float | время поиска без проверки моделей |

### Правило решения о реранкере (`decide`, FR-014)

Вход: по каждому варианту (`off`, `on`) — число вопросов, сколько на первом месте,
сколько в первых пяти, медиана времени. Выход: `keep` или `disable` и причина.

```text
top5(on) > top5(off)                               → keep, если median_s(on) ≤ 10
top5(on) = top5(off) и top1(on) > top1(off)        → keep, если median_s(on) ≤ 10
иначе                                              → disable
```

Доли сравниваются по числу вопросов (знаменатель у обоих вариантов один — вопросы без
ошибки в наборе). Медиана больше 10 с — `disable` с причиной «медленно».

## Файл вопросов замера (R-11)

TOML у аналитика в папке данных, не в репозитории:

| Ключ | Тип | Правило |
|---|---|---|
| `question[].text` | str | не пустой; не печатается |
| `question[].answer` | str | идентификатор пункта `D-0015/2.2.1` (`ids.parse_clause_id`); договор вопроса — из него |

Номер вопроса — порядковый, с 1. Тестовый набор на синтетике —
`tests/synthetic/search_questions.toml`.
