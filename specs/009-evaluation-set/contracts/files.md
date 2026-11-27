# Contract: файлы эталона, вопросов и результатов

Все файлы лежат в папке данных (`$DOCREADER_DATA_DIR/eval/`, `questions/`) и содержат
значения и текст договоров: агенту не передаются (FR-025). В репозитории — только
синтетические образцы в `tests/synthetic/` на вымышленных договорах генераторов.

## Шаблон эталона и слепой разметки (CSV)

UTF-8 с BOM, разделитель `;`, все ячейки в кавычках (research R-2). Загрузка принимает
и `,`, с BOM и без.

```
"document_id";"contract_number";"customer_name_short";…;"contract_end_date"
"#вид";"идентификатор";"наименование";…;"дата"
"#подсказка";"как в договоре; пусто = не размечено; «отсутствует» = в договоре нет; варианты через « || »";"краткое, с формой: АО «Альфа»; пусто = …";…;"ДД.ММ.ГГГГ или «25 марта 2026»; пусто = …"
"D-0001";"";"";…;""
```

- Подсказка — по виду поля (у кратких наименований — «краткое, с формой: АО «Альфа»»,
  у сумм — «с копейками, например 1 000 000,60»; дополнено 2026-11-27 по слепому
  контролю), в каждом столбце с одним и тем же пояснением про пустую ячейку,
  «отсутствует» и « || ».
- Строки, у которых первая ячейка начинается с `#`, пропускаются.
- Столбец `document_id` обязателен; лишний столбец не из каталога — файл не загружается.
- Пустая ячейка — «не размечено»; `отсутствует` (регистр и пробелы по краям не важны) —
  «в договоре отсутствует»; ` || ` разделяет варианты.

## Ответы страницы проверки (JSON)

Отдаётся страницей кнопкой; загружается `eval load`.

```json
{
  "format": "docreader-gold-review/1",
  "build": "20261127-102000-3f9c",
  "cards": [
    {"key": "D-0001/contract_number", "answer": "agree"},
    {"key": "D-0001/amount_with_vat", "answer": "chosen", "choice": "rules"},
    {"key": "D-0002/contract_end_date", "answer": "typed", "value": "…", "clause": "D-0002/12.1"},
    {"key": "D-0003/customer_name_short", "answer": "absent"},
    {"key": "D-0004/contractor_name_short", "answer": "skip"}
  ]
}
```

`answer`: `agree` («верно»: при пометке карточки `agree` путь эталона `agree`, при `model_only` / `rules_only` — `confirmed`), `chosen` (`choice`: `model` или `rules`;
при нескольких значениях правил — `rules:N`), `typed` (`value`; `clause` — если выбрано
место), `absent`, `skip`. Охват файла (research R-6) — все карточки сборки, включая
`skip`. Значение и пункт для `agree` и `chosen` загрузка берёт из сборки страницы
(файл `cards.json` в её папке), а не из ответа, — так файл ответов не может подменить
значение системы. Вместе со значением загрузка сохраняет показанное на карточке
приведённое значение фичи 05 (`gold_field.system_normalized`) — по нему следующая
страница ставит пометку `changed`.

## Файл вопросов (TOML)

Вид наборов фич 08 и 09 принимается без изменений; новые ключи необязательны.

```toml
[[question]]
text = "Какая цена договора без НДС?"
answer = "D-0015/5.2"            # пункт ответа (документ — из пункта)
contains = ["1000000.00"]        # ожидаемые значения (необязательно)

[[question]]
text = "Какой размер аванса?"
document = "D-0015"
expected = "none"                # ответа в договоре нет

[[question]]
text = "Почему цена договора без НДС — 5 000 000 руб.?"
answers = ["D-0015/5.2", "D-0015/5.3"]  # несколько правильных пунктов
false_premise = true
kind = "text"                    # text | table | both
contains = ["1000000.00"]
```

```toml
origin = "set09"                 # необязательно, в начале файла: own | set08 | set09 | generated

[[question]]
text = "Какой срок оплаты?"
document = "D-0015"
expected = "answer"              # ответ есть, пункт не указан: вне метрик поиска
```

Правила: ровно одно из `answer`, `answers`, `expected = "none"`, `expected =
"answer"`; при `expected` нужен `document`; при `answers` документ у всех пунктов
один; `document`, если задан, совпадает с документом пунктов. `origin` в файле
важнее ключа `--origin` команды; без обоих — `own`.

## Машиночитаемый файл ответов замера фичи 09 (JSON)

Пишет `scripts/quickstart_answers.py` рядом с `answers-b4-<время>.txt`; читает
`eval questions clauses`. Вопросы этого файла сопоставляются с файлом вопросов по
документу и тексту (ключ вопроса), а не по номеру: замер мог идти по части вопросов.

```json
{
  "format": "docreader-answers-b4/1",
  "questions": [
    {"number": 21, "document": "D-0012", "text": "…", "outcome": "answered",
     "confirmed_clauses": ["D-0012/4.2"]}
  ]
}
```

## Результаты из файла (JSON, FR-023)

Для `eval fields --from`:

```json
{
  "format": "docreader-field-results/1",
  "source": "описание источника для provenance",
  "values": [
    {"document": "D-0001", "field": "contract_number", "result": "found", "value": "…"},
    {"document": "D-0001", "field": "amount_with_vat", "result": "rejected"}
  ]
}
```

`result`: `found` (с `value`), `not_found`, `rejected`, `failed`; пары без строки —
«нет результата».

Для `eval search --from`:

```json
{
  "format": "docreader-search-results/1",
  "source": "…",
  "variants": {
    "search_plain":  {"Q-3f9c0a1b2d": ["D-0015/5.2", "D-0015/преамбула"]},
    "search_rerank": {"Q-3f9c0a1b2d": ["D-0015/преамбула", "D-0015/5.2"]}
  }
}
```

## Файлы разбора и выгрузка (CSV)

Тот же вид CSV, что у шаблона.

- Разбор полей: `document_id; field; outcome; flags; gold; system; clause; quote`.
- Разбор поиска: `question_key; document_id; question; correct_clauses; place_plain;
  place_rerank; top5_plain; top5_rerank`.
- Разбор слепого контроля: `document_id; field; outcome; blind; reviewed; path`.
- Выгрузка таблицы: `id; created_at; label; stage; gold_version; current_gold;
  reviewed_share; blind; <метрики этапа>`.
