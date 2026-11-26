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
"#подсказка";"как в договоре, без «№»";"как в преамбуле: ООО «…»";…;"ДД.ММ.ГГГГ или «25 марта 2026»; «отсутствует» — поля нет; варианты через « || »"
"D-0001";"";"";…;""
```

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

`answer`: `agree` (одно значение верно), `chosen` (`choice`: `model` или `rules`;
при нескольких значениях правил — `rules:N`), `typed` (`value`; `clause` — если выбрано
место), `absent`, `skip`. Охват файла (research R-6) — все карточки сборки, включая
`skip`. Значение и пункт для `agree` и `chosen` загрузка берёт из сборки страницы
(файл `cards.json` в её папке), а не из ответа, — так файл ответов не может подменить
значение системы.

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

Правила: ровно одно из `answer`, `answers`, `expected = "none"`; при `answers`
документ у всех пунктов один; `document`, если задан, совпадает с документом пунктов.

## Машиночитаемый файл ответов замера фичи 09 (JSON)

Пишет `scripts/quickstart_answers.py` рядом с `answers-b4-<время>.txt`; читает
`eval questions clauses`.

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
