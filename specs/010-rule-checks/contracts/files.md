# Contract: файлы фичи 06

Все файлы — в папке данных; агенту не отправляются (содержат значения договоров).

## `checks/queue-<сборка>/cards.json`

```json
{
  "format": "docreader-check-cards/1",
  "build": "20261128-101500-3fa2",
  "checks_version": "06.1",
  "cards": [
    {
      "key": "D-0001/amount_with_vat",
      "document_id": "D-0001",
      "field": "amount_with_vat",
      "status": "needs_review",
      "reasons": ["amount_words:words_differ"],
      "flags": [],
      "system": {"result": "found", "value": "…", "normalized": "…", "quote": "…",
                 "clause": "2.1", "pages": [2], "image": "img/D-0001-2.png"},
      "decision": null
    }
  ]
}
```

`decision` — прежнее решение (`kind`, `value`, `system_normalized`) для карточек
с `system_changed`. Рядом — `index.html` (страница фичи 02, `review_page.render_html`)
и `img/`.

## `check-review-<сборка>.json` — ответы страницы

```json
{
  "format": "docreader-check-review/1",
  "build": "20261128-101500-3fa2",
  "cards": [
    {"key": "D-0001/amount_with_vat", "answer": "agree"},
    {"key": "D-0002/amount_without_vat", "answer": "typed", "value": "…", "clause": "D-0002/2.1"},
    {"key": "D-0003/contract_end_date", "answer": "absent"},
    {"key": "D-0004/contract_number", "answer": "skip"}
  ]
}
```

`agree` → решение `confirm` (только на карточке с найденным значением; на остальных
отклоняется с причиной); `typed` → `correct` (значение приводится по виду поля при
загрузке, research R-9); `absent` → `absent`; `skip` — решения нет. Неизвестный ключ
или формат — карточка или файл отклоняются с причиной.

## `eval/checks-<запись>-<время>.csv` — разбор отчёта

UTF-8 с BOM, `;`, как файлы разбора фичи 02: `document_id;field;outcome;rules;system;gold`,
где `outcome` — `queued_wrong`, `queued_right`, `accepted_wrong`, `accepted_right`,
`rules` — сработавшие правила через « || ».
