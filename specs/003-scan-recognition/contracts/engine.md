# Contract: интерфейс движка распознавания

**Дата**: 2026-11-19 · **План**: [../plan.md](../plan.md) · **Research**: R-3, R-4, R-5, R-13

Единственная точка, через которую код проекта обращается к движку распознавания.
Весь остальной код (`recognition.py`, `reading.py`, тесты) знает только эти типы.
Код здесь — образец, не готовая реализация. Имена окончательные.

## Типы (`docreader/ocr.py`)

```python
Box = tuple[float, float, float, float]

@dataclass(frozen=True)
class EngineLine:
    text: str          # as given by the engine; never corrected (FR-010)
    box: Box           # pixels of the image passed in: left, top, right, bottom; origin top-left
    confidence: float  # 0..1; the adapter rescales the engine's own scale

@dataclass(frozen=True)
class EngineOutput:
    lines: tuple[EngineLine, ...]  # any order; reading builds the reading order
    orientation: int | None        # 0/90/180/270 clockwise the text is turned, if detected

class RecognitionEngine(Protocol):
    name: str      # key in ocr_engines.ENGINES
    version: str   # engine + language model version, recorded in page_recognition and run
    def recognize(self, image: PIL.Image.Image) -> EngineOutput: ...
```

Требования к реализации:

- `recognize` не пишет на диск ничего, кроме временного файла в
  `$DOCREADER_DATA_DIR/tmp/`, который тут же удаляется. По сети не обращается.
- Строка — это фрагмент текста на одной высоте. Две колонки на одной высоте можно
  вернуть двумя строками: чтение соберёт их (R-7).
- `box` лежит в границах изображения. Перекошенная строка отдаётся охватывающим
  прямоугольником.
- Пустая страница — `EngineOutput(lines=(), orientation=None)`, это не ошибка.
- Ошибка распознавания страницы — любое исключение. Вызывающий код записывает его
  в `page_recognition.error` и продолжает (FR-016).
- Один и тот же вход должен давать одинаковый результат (проверяется при замере,
  R-2).

## Загрузка (`docreader/ocr_engines.py`)

```python
EngineFactory = Callable[[RecognitionSettings, Path], RecognitionEngine]  # settings, data_dir

ENGINES: dict[str, EngineFactory] = {
    "tesseract": _load_tesseract,       # tesserocr + rus.traineddata
    "apple_vision": _load_apple_vision, # pyobjc-framework-Vision, macOS only
}

def load_engine(settings: RecognitionSettings, data_dir: Path) -> RecognitionEngine:
    """Check the guards, then call the factory. Raises EnvironmentProblem with a hint."""
```

Порядок проверок в `load_engine`:

1. `settings.engine` пуст — `EnvironmentProblem` «Не выбран движок распознавания…»;
2. имени нет в `ENGINES` — `EnvironmentProblem` с перечнем известных имён;
3. задана `DOCREADER_FORBID_MODELS` — `EnvironmentProblem` «На этой машине движок
   распознавания не запускается (DOCREADER_FORBID_MODELS)»;
4. выставить переменные отключения сети и телеметрии (R-4, п. 4);
5. вызвать фабрику. Внутри неё — ленивый `import`. `ImportError` превращается
   в `EnvironmentProblem` с подсказкой:
   - `tesseract`: «движок tesseract не установлен — на ноутбуке: brew install
     tesseract tesseract-lang && uv sync --group ocr»;
   - `apple_vision`: на не-macOS — «движок apple_vision работает только на macOS»;
     иначе — «uv sync --group ocr»;
6. фабрика проверяет, что языковые данные или файлы модели есть на диске. Если их
   нет — `EnvironmentProblem` с путём, по которому они искались. Ничего не
   скачивается.

Адаптер следующего кандидата (очередь 2–3, research R-1) добавляется новой строкой
в `ENGINES` и не меняет ничего вне `ocr_engines.py`.

## Зависимости

Группа `ocr` в `pyproject.toml` не входит в `default-groups`:

```toml
[dependency-groups]
ocr = [
    "tesserocr; sys_platform == 'darwin'",
    "pyobjc-framework-Vision; sys_platform == 'darwin'",
]
```

Маркер `darwin` у `tesserocr` стоит потому, что на Linux он собирается из исходников
и требует системных заголовков. Движок на Linux не запускается, поэтому эту сборку
незачем включать. Версии фиксируются в `uv.lock` при добавлении группы
**[проверить]**: на ноутбуке `uv sync --group ocr` и тест уровня 3.

## Подмены в тестах (`tests/fakes/ocr.py`)

| Подмена | Что делает | Уровень |
|---|---|---|
| `ScriptedEngine(outputs)` | отдаёт заданные `EngineOutput` по очереди или по номеру вызова; запоминает размеры полученных изображений | 1 |
| `TruthEngine(truth)` | по `truth.json` генератора отдаёт точный текст, переводит прямоугольники PDF в пиксели полученного изображения, `confidence = 0.99` | 1 |
| `FailingEngine(pages)` | бросает `RuntimeError` на заданных страницах, на остальных ведёт себя как `TruthEngine` | 1 |
| `InterruptingEngine(after)` | бросает `KeyboardInterrupt` на N-м вызове | 1 |
| `RecordedEngine(path, settings)` | отдаёт записанный выход реального движка; при несовпадении движка, версии, dpi или версии генератора бросает `AssertionError` «запись устарела — перезапишите её на ноутбуке» | 2 |

`recognition.recognize_documents(..., engine_factory=...)` принимает фабрику.
По умолчанию это `ocr_engines.load_engine`, в тестах передаётся подмена.
Фабрика вызывается не больше одного раза за запуск и только если есть страница
для распознавания.
