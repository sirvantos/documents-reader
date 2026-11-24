# Интерфейс модели поиска по смыслу и подделки (фича 07)

Решения — [research.md](../research.md) R-1, R-2, R-6, R-9.

## `docreader/embedding.py`

Единственный модуль, который обращается к модели поиска. Импортирует `openai`
и `httpx2` (уже в зависимостях, фича 05); других моделей и библиотек не знает.

```python
class EmbeddingRequestError(Exception): ...   # ответ 4xx/5xx или не по форме — ошибка договора
# ModelUnavailable (общий с llm.py, подкласс EnvironmentProblem) — нет связи, тайм-аут: остановка

@dataclass(frozen=True)
class EmbedderInfo:
    served_model: str   # id модели из ответа сервера
    dims: int

class Embedder:
    def check(self) -> EmbedderInfo: ...
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...  # длина 1, порядок как у texts

def load_embedder(settings: EmbeddingSettings,
                  transport: httpx2.BaseTransport | None = None) -> Embedder: ...
```

Правила:

- `DOCREADER_FORBID_MODELS` и `transport is None` → `EnvironmentProblem` «На этой
  машине модель поиска не запускается (DOCREADER_FORBID_MODELS)» до создания клиента
  и без сокетов.
- `base_url` не петлевой → ошибка настроек при загрузке (`config.is_local_model_url`).
- Клиент `openai.OpenAI(base_url=…, api_key="local", max_retries=0, timeout=timeout_s,
  http_client=httpx2.Client(transport=…))`; переменные `OPENAI_*` не читаются.
- `embed` шлёт пачки по `batch_size`; тексты длиннее `max_chars` в `embed` не попадают
  (обрезает вызывающий, `indexing.py`, R-6) — `embed` проверяет и падает `ValueError`.
- Ответ: `len(data) == len(batch)`, у всех векторов одна длина, равная `dims` из
  `check()`, числа конечные; иначе `EmbeddingRequestError`. Порядок — по `index`
  элементов ответа.
- Сообщения исключений не содержат входных текстов.

## Подделки — `tests/fakes/embedding.py`

| Класс | Поведение |
|---|---|
| `HashEmbedder(dims=8, served_model="fake-embedder")` | `/v1/embeddings`: вектор каждого входа — первые `dims` байт SHA-256 текста, отображённые в [-1, 1], нормированные; `.inputs` — все принятые тексты по порядку; `.requests` — число запросов |
| `FailingEmbedder(fail_on: str, kind)` | как `HashEmbedder`, но на пачке, где есть текст с подстрокой `fail_on`: `kind="http_500"` — ответ 500; `"wrong_count"` — на один вектор меньше; `"connect"` — `httpx2.ConnectError` |
| `DownEmbedder()` | любой запрос — `httpx2.ConnectError` (сервер не запущен) |

Фикстура `use_embedder(fake)` в `tests/conftest.py` подменяет транспорт в
`embedding.load_embedder` (как `use_model` у `llm.load_client`).

## Уровень 3 — `tests/real_model/test_embedding_server.py`

Только Mac, `pytest -m real_model`, синтетические строки: `check()` возвращает
размерность 1024 (BGE-M3); один и тот же текст — один и тот же вектор; длина 1;
пачка из 16 текстов — 16 векторов в порядке входа; строка ровно в `max_chars` знаков
из групп цифр и слов реквизитов принимается без ошибки (R-6); выключенный сервер —
`ModelUnavailable`.
