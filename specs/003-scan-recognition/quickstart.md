# Quickstart: проверка фичи 13 «Распознавание страниц-сканов»

**Дата**: 2026-11-19 · **План**: [plan.md](plan.md) · **CLI**: [contracts/cli.md](contracts/cli.md) ·
**Движок**: [contracts/engine.md](contracts/engine.md) · **Модель данных**: [data-model.md](data-model.md) ·
**Решения**: [research.md](research.md)

Quickstart из двух частей, как в фичах 01 и 03.

- **А. Сервер разработки и синтетика.** Здесь можно работать с ИИ-агентом. Движок
  распознавания не устанавливается и не запускается, вместо него работают
  заглушки и записи.
- **Б. Ноутбук аналитика.** Сюда относятся установка движка, замер кандидатов,
  запись ответов и прогон на реальном наборе. **Только аналитик, в своём терминале,
  без агента** (принцип I). Агенту передаются только цифры. Вывод `text`,
  `recognize-eval --diff` и `recognize-report --review` по реальным договорам ему
  не передаётся.

## Предварительные условия

Как в [quickstart фичи 01](../001-document-intake/quickstart.md#предварительные-условия).
После обновления ветки:

```
uv sync                      # Pillow переходит в основные зависимости; группа ocr не ставится
uv run docreader migrate     # «Применена миграция 0003_recognition»
```

Docker: после изменения зависимостей выполните `docker compose build tests`.

---

## А. Сервер разработки (синтетика, без движка)

### А0. Запрет движка на этой машине

```
echo 'export DOCREADER_FORBID_MODELS=1' >> ~/.profile   # один раз; в compose.yaml уже задано
```

### А1. Автотесты

```
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres uv run pytest
docker compose run --rm tests
uv run ruff check . && uv run mypy
```

`real_model` по умолчанию исключён. Уровень 2 (записи) до выбора движка
не включён (research R-13).

| Сценарий / требование | Что проверяется (заглушки уровня 1, синтетика `make_scans`) |
|---|---|
| US1-1, FR-001…FR-003 | договор из одних сканов: у каждой страницы строки, `bbox` внутри страницы, уверенность и оценка |
| US1-2 | `mixed`: распознаются только страницы-сканы, движок вызван столько раз, сколько их |
| US1-3 | документ без сканов: `done`, фабрика движка не вызывалась |
| US1-4 | `show` и `text --page`: «распознано», движок, dpi, время, оценка |
| US1-6, FR-013 | `InterruptingEngine` на 3-й странице, затем повторный запуск: распознаны только оставшиеся, строк по одной на страницу, результат совпадает с непрерывным прогоном |
| US1-7, FR-011 | `recognize` без аргументов не трогает распознанный документ |
| US2-1, US2-3, FR-009 | `TruthEngine` → `read` → `text --find` находит фразу через перенос строки; `bbox` совпадает с `truth.json` (допуск 1 pt); `page_text.source = 'recognized'`; нет `scan_unread` |
| US2-2 | нераспознанная страница-скан даёт `scan_unread` с причиной «распознавание не выполнено…», остальные читаются |
| US2-4 | колонтитул на каждой странице вынесен, «мон-»/«тажные» склеены |
| US2-5, FR-012 | документ прочитан до распознавания; после `recognize` этап чтения `pending` с причиной «распознанный текст изменён»; `read` без аргументов его перечитывает |
| US2-6 | ошибка внутри фразы в распознанном тексте: `textnorm.locate` её не находит |
| US3-1…3, FR-005 | `faded_noisy` (низкая уверенность из `ScriptedEngine`) получает `low_recognition_quality` с числами, `reading` = `needs_review`; при высокой уверенности `done` без флага |
| US4-1, FR-006 | `stamp_only` даёт `scan_no_text`, `blank` даёт `empty` (на просмотр не уходит) |
| US4-2 | порог в `settings.toml` изменён, `read --all`: флаги другие, фабрика движка не вызывалась |
| US5-1…3, FR-017 | `recognize-eval` на синтетике: известный текст с одной подменой даёт ожидаемую долю знаков, ИНН найден или не найден, контрольные строки найдены; файл в `reports/` содержит `run_id` и настройки; папка вне данных — код 1 |
| US6-1…3 | `--force` с тем же результатом: `result_sha256` тот же, чтение не сброшено; другой результат — сброшено; `--pages 2-3` распознаёт только их; ошибки `--pages` (код 1) |
| US7-1…3, FR-018 | `recognize-report`, `--csv`, `--review` (порядок от худших) |
| R-5 | координаты: 4 `/Rotate` × 4 доворота, CropBox со смещением; чёрный прямоугольник находится по пикселям отрисовки |
| R-6 | `ScriptedEngine` с плохим 0° и хорошим 180°: `turn = 180`, координаты верны; все варианты плохие — флаг с причиной «ориентация не определена» |
| R-7 | `requisites_two_columns`: левая колонка целиком, затем правая; `table`: ячейки строки рядом, `has_table = false` |
| FR-016, edge cases | `FailingEngine` на стр. 2: остальные распознаны, документ `needs_review` «стр. 2: ошибка распознавания…»; удалённая копия даёт `failed`, остальные документы обработаны |
| R-4, принцип I | под запретом `load_engine` падает для каждого имени; `engine = ""` даёт код 2 с подсказкой; сетевой сторож в conftest; команда записи отказывается от пути вне `tests/synthetic/` |
| SC-008 | второй `recognize` распознаёт 0 страниц и не меняет `stage_status` |

### А2. Ручной прогон на сервере (только синтетика, без движка)

> С ИИ-агентом работать только в одноразовой папке данных и отдельной базе:
> `createdb docreader_demo` до прогона и `dropdb docreader_demo` после.
> `~/docreader-data` и базу `docreader` не трогать.

```
export DOCREADER_DATA_DIR=/tmp/docreader-demo-data
export DOCREADER_DATABASE_URL=postgresql:///docreader_demo
createdb docreader_demo && uv run docreader migrate
uv run python -m tests.synthetic.make_scans /tmp/docreader-demo-in   # все варианты + один текстовый договор
uv run docreader add /tmp/docreader-demo-in
uv run docreader recognize
```

Ожидаемо: текстовый договор (без сканов) получает «готово». На первом документе
со сканами команда останавливается с кодом 2: «На этой машине движок
распознавания не запускается (DOCREADER_FORBID_MODELS)». Если запрет не задан,
сообщение будет «Не выбран движок распознавания…». `read` после этого даёт сканам `scan_unread` с причиной
«распознавание не выполнено — docreader recognize D-…».

```
dropdb docreader_demo && rm -rf /tmp/docreader-demo-data /tmp/docreader-demo-in
```

---

## Б. Ноутбук аналитика (без агента)

### Б0. Установка движка

Нужен родной (arm64) Homebrew в `/opt/homebrew` и arm64-Python: `tesserocr` —
C-расширение, оно не загрузится, если Python и `libtesseract` собраны под разные
процессоры. Проверка: `uv run python -c "import platform; print(platform.machine())"`
печатает `arm64`.

```
git pull
brew install tesseract tesseract-lang        # для кандидата tesseract
PKG_CONFIG_PATH=/opt/homebrew/lib/pkgconfig uv sync --group ocr --no-binary-package tesserocr
uv run python -c "import tesserocr; print(tesserocr.get_languages()[0])"   # /opt/homebrew/share/tessdata/
cp .env.example .env                         # рабочий набор: ~/docreader-data, база docreader
cp .env.example .env.bench                   # замер: ~/docreader-ocrbench, база docreader_ocrbench
```

Значения переменных окружения задаются в `.env` и `.env.bench` (они не коммитятся,
описание — в `.env.example`). Команды раздела Б подключают их флагом `--env-file`;
сокращения `dr` и `drb` — в `.env.example`. `DOCREADER_FORBID_MODELS` на ноутбуке
не задаётся совсем: любое непустое значение, даже `0`, запрещает движок. Проверить,
что сеть не нужна: выключить Wi-Fi на время Б1–Б3.

### Б1. Замер кандидатов (research R-2) — до выбора движка

1. Отдельная папка данных и база замера:

   ```
   createdb docreader_ocrbench && drb migrate     # drb = uv run --env-file .env.bench docreader
   drb add <5–10 договоров со страницами замера>
   ```

   Дальше в Б1 команды `docreader` запускаются через `drb`. Псевдоним раскрывается только
   первым словом, поэтому после `/usr/bin/time` пишется полная форма.

2. Положить проверенные тексты страниц в `~/docreader-ocrbench/ocr-eval/pages/`
   и контрольные строки в `control.csv` (формат: research R-12).
3. Для каждого кандидата (`tesseract`, `apple_vision`) и разрешения (300; лучшему
   ещё 200 и 400) прописать `[recognition] engine` и `dpi` в
   `~/docreader-ocrbench/settings.toml`, затем:

   ```
   /usr/bin/time -l uv run --env-file .env.bench docreader recognize --all --force --label "tesseract 300"
   drb read --all
   drb recognize-eval ~/docreader-ocrbench/ocr-eval --label "tesseract 300"
   drb recognize --all --force --json > /dev/null   # повтор для воспроизводимости:
   drb recognize-report --json                      # сравнить result_sha256 (R-2, п. 4)
   ```

4. На 3 страницах сравнить `docreader text D-… --page N --json` (`bbox`)
   с изображением страницы. На странице реквизитов и странице с таблицей
   проверить порядок строк.
5. Агенту передать **только** таблицу цифр: кандидат, dpi, доля знаков, реквизиты,
   контрольные строки, пропуски и повторы строк, с/стр., пиковая память,
   воспроизводимость, совпадение прямоугольников (да/нет), порядок колонок
   (да/нет).
6. Если ни один кандидат очереди 1 не проходит SC-002, SC-004 или 25 с/стр.,
   агент добавляет адаптер очереди 2 (research R-1), и замер повторяется.

После выбора записать результат в `docs/tech-context.md` (список в конце
[plan.md](plan.md)) и поменять значения по умолчанию `engine` и `dpi`.

### Б2. Тест уровня 3

```
uv run --env-file .env pytest -m real_model tests/real_model/test_ocr_engine.py
```

Ожидаемо: движок загружается, на синтетике `clean` доля знаков не ниже 95%, сетевых
соединений нет. Вывод (синтетика) можно передать агенту.

### Б3. Записи уровня 2

```
uv run --env-file .env python -m tests.synthetic.record_recognition
git add tests/recordings/13-scan-recognition && git commit -m "test(recognition): record <engine> <version> on synthetic scans"
git push
```

Записи вручную не правятся. Записи нет или она устарела — её перезаписывает
только аналитик этой командой.

### Б4. Перезапись после изменений

Тест уровня 2 падает с «запись устарела — перезапишите её на ноутбуке». Это
значит, что изменились движок, его версия, `dpi` или `SCAN_GENERATOR_VERSION`.
В этом случае повторить Б3.

### Б5. Рабочий прогон набора (SC-001, SC-006, SC-008, SC-009)

Команды `docreader` в Б5–Б6 запускаются через `dr` (`uv run --env-file .env docreader`).

```
dr migrate
caffeinate -i /usr/bin/time -l uv run --env-file .env docreader recognize --label "набор, <движок> <dpi>"
# прервано — тот же вызов продолжит с первой несохранённой страницы
time dr read                  # SC-008: не более 10 минут
dr recognize                  # SC-008: «Нечего распознавать»
dr recognize-report --csv
dr read-report
```

Языковую модель на время прогона не запускать, память общая. Записать общее
время и время на страницу (SC-006, не более 12 ч). Записать долю договоров,
доступных следующим этапам: `reading` в `done`/`needs_review` и
`read_pages > 0` (SC-009, не менее 95%).

### Б6. Замер качества на рабочем наборе (SC-002…SC-005, SC-007)

1. Выверить не менее 20 страниц из не менее чем 10 договоров. Среди них должны
   быть страница реквизитов и страница с суммой. Положить их в
   `~/docreader-data/ocr-eval/`. Выписать контрольные строки в `control.csv`.
2. По `recognize-report --review` проверить вручную 20 помеченных
   и 20 непомеченных страниц и заполнить `flags.csv`.
3. Запустить замер:

   ```
   dr recognize-eval ~/docreader-data/ocr-eval --label "SC-002…007"
   ```

4. Если флаг верен меньше чем в 80% случаев (SC-007), подобрать пороги
   `[recognition]`, выполнить `read --all` и повторить шаг 3. Повторно распознавать
   не нужно.
5. SC-005: на 10 страницах сравнить `bbox` строк с изображением.
6. Цифры лежат в `~/docreader-data/reports/recognition-eval-*.json`. Агенту
   передать только итоговые доли. Пороги и итоговые цифры записать
   в `docs/tech-context.md`.
