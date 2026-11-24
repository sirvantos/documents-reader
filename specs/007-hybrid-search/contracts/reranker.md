# Интерфейс реранкера и подделки (фича 08)

Решения — [research.md](../research.md) R-7, R-8. Устройство — как у модели поиска
([фича 07](../../006-passages-and-indexes/contracts/embedding.md)).

## `docreader/reranker.py`

```python
class RerankRequestError(Exception): ...      # HTTP-ошибка или ответ не по форме

@dataclass(frozen=True)
class RerankerInfo:
    served_model: str

class Reranker:
    settings: RerankerSettings
    def check(self) -> RerankerInfo: ...
    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...

def rerank_input(query: str, label: str, text: str, max_chars: int) -> tuple[str, str, bool]: ...
def load_reranker(settings: RerankerSettings,
                  transport: httpx2.BaseTransport | None = None) -> Reranker: ...
```

- `load_reranker`: адрес не на этой машине → `EnvironmentProblem` (принцип I);
  `transport is None` и `DOCREADER_FORBID_MODELS` → `EnvironmentProblem` «На этой машине
  реранкер не запускается (DOCREADER_FORBID_MODELS)», до создания клиента. Клиент —
  `httpx2.Client(base_url=…, timeout=timeout_s, transport=…)`, без повторов,
  без переменных окружения прокси (`trust_env=False`).
- `score(query, documents)`: один `POST rerank` с телом
  `{"model": settings.model, "query": query, "documents": documents}`; ответ
  `{"model"?: str, "results": [{"index": int, "relevance_score": float}]}`. Оценки
  возвращаются в порядке `documents`. Пустой `documents` → `[]` без запроса.
- Ошибки:

  | Что случилось | Исключение | Сообщение (без текста запроса и документов) |
  |---|---|---|
  | соединение не установлено | `ModelUnavailable` | «Реранкер недоступен по адресу … — запустите его или выполните поиск с --no-rerank» |
  | тайм-аут | `ModelUnavailable` | «реранкер не ответил (тайм-аут 60 с)» |
  | HTTP 4xx/5xx | `RerankRequestError` | «сервер реранкера отклонил запрос: HTTP 500» |
  | тело не JSON / нет `results` | `RerankRequestError` | «ответ реранкера не по форме» |
  | индексы не 0…n−1 или их число ≠ n | `RerankRequestError` | «ответ реранкера не по форме: 29 оценок на 30 отрывков» |
  | оценка не конечное число | `RerankRequestError` | «ответ реранкера не по форме: оценка не число» |

- `check()`: `score("проверка", ["проверка"])`; `served_model` — `model` из ответа или
  `settings.model`.
- `rerank_input(query, label, text, max_chars)`: документ — `label + "\n" + text`;
  запрос длиннее `max_chars // 4` обрезается до него (флаг `True`); документ обрезается
  до `max_chars - len(query)`. Чистая функция, тестируется отдельно.

## `tests/fakes/reranker.py`

Транспорты `httpx2.MockTransport`; сокеты не открываются.

| Подделка | Поведение |
|---|---|
| `TableReranker(scores: dict[str, float], default=0.0)` | оценка документа — значение первого ключа (подстрока, без учёта регистра), найденного в документе, иначе `default`; `.requests` — принятые тела |
| `FailingReranker(kind)` | `http_500`, `wrong_count`, `bad_index`, `not_json`, `timeout`, `connect` |
| `DownReranker()` | любой запрос — ошибка соединения |

Фикстура `use_reranker(fake)` в `tests/conftest.py` подменяет `reranker.load_reranker`
так, что он получает `fake.transport` (как `use_embedder`).

## `tests/fakes/embedding.py`: `TopicEmbedder`

`TopicEmbedder(topics: dict[str, list[str]], dims=16)`: тема → ось; вектор текста —
единица по каждой оси темы, чьё слово-признак (подстрока в нижнем регистре) есть
в тексте, плюс 0,01 × `hash_vector(text)`; нормирован. Текст без тем — почти
случайный вектор. Тот же протокол `/v1/embeddings`, что `HashEmbedder`.

## Уровень 3: `tests/real_model/test_reranker_server.py` (только Mac)

`pytest -m real_model`, реранкер на `[reranker] base_url`:

- `check()` отвечает, `served_model` не пуст;
- форма ответа: n оценок на n документов, порядок по `index`;
- «срок оплаты»: «оплата в течение 30 дней» получает оценку выше, чем «гарантийный
  срок 12 месяцев»;
- адрес без сервера (`127.0.0.1:1`) → `ModelUnavailable`.
