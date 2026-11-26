# Quickstart: эталонный набор и таблица результатов (фича 02)

Часть А — сервер разработки (агент), только синтетика. Часть Б — ноутбук аналитика,
рабочий набор. Команды — [contracts/cli.md](contracts/cli.md), файлы —
[contracts/files.md](contracts/files.md).

**Что можно присылать агенту** из части Б: вывод команд `docreader eval …` в терминал
(числа, идентификаторы, названия полей, исходы, пути) и время, которое заняла работа.
**Не присылать никогда:** шаблоны и слепую разметку, страницу проверки, файл ответов
страницы, файлы разбора, сгенерированные вопросы, файлы вопросов, выгрузку таблицы
результатов — в них значения и текст договоров (принцип I).

## А. Сервер разработки

### А1. Проверки

```bash
DOCREADER_TEST_DATABASE_URL=postgresql:///postgres scripts/check.sh
```

Ожидается: тесты, ruff и mypy проходят; интеграционные тесты фичи прогоняют всю цепочку
на синтетике (research R-14).

### А2. Ручной прогон на синтетике

Временная папка данных и база `docreader_demo` (CLAUDE.md «Commands»). Результаты
фичи 05 на сервере не получить (модель запрещена), поэтому поля сравниваются
из синтетического файла результатов.

```bash
createdb docreader_demo 2>/dev/null || true
export DOCREADER_DATA_DIR=$(mktemp -d) DOCREADER_DATABASE_URL=postgresql:///docreader_demo
uv run docreader migrate
uv run python -c "from tests.synthetic.make_pdfs import make_extraction_contracts as m; m('$DOCREADER_DATA_DIR/in')"
uv run docreader add "$DOCREADER_DATA_DIR/in" && uv run docreader read --all && uv run docreader parse --all
uv run docreader eval template --fields prototype
uv run docreader eval load tests/synthetic/gold/template-filled.csv
uv run docreader eval fields --from tests/synthetic/gold/field-results.json --label demo
uv run docreader eval results && uv run docreader eval show 1 --outcome missed
```

Вопросы и замер поиска — на договорах генератора поиска (набор вопросов и файл
результатов рассчитаны на них как на `D-0001`…`D-0003`), поэтому в новой базе и папке:

```bash
dropdb docreader_demo && createdb docreader_demo
export DOCREADER_DATA_DIR=$(mktemp -d)
uv run docreader migrate
uv run python -c "from tests.synthetic.make_pdfs import make_search_contracts as m; m('$DOCREADER_DATA_DIR/in')"
uv run docreader add "$DOCREADER_DATA_DIR/in" && uv run docreader read --all && uv run docreader parse --all
uv run docreader eval questions load tests/synthetic/search_questions.toml
uv run docreader eval search --from tests/synthetic/gold/search-results.json --label demo
uv run docreader eval results && uv run docreader eval show 1 --outcome not_found
```

После проверки: `dropdb docreader_demo`.

Ожидается: шаблон с 6 столбцами полей и пустыми ячейками; загрузка называет число
значений и одну ошибку вида (намеренно в образце); сравнение — по одному случаю
каждого исхода; замер поиска — две записи; вывод без значений и текста.

## Б. Ноутбук аналитика

### Б0. Ветка и база

```bash
git pull && uv sync --group ocr
uv run --env-file .env docreader migrate
```

Ожидается: миграция `0007_evaluation` применена. Модели нужны только в Б5 (пункт 1)
и Б6 (замер поиска).

### Б1. Шаблон и табличный редактор (проверка формата, часть B файла фичи)

```bash
uv run --env-file .env docreader eval template --fields prototype --documents D-0001
```

Откройте файл в редакторе, которым будете размечать (Excel или Numbers): кириллица
в заголовке и подсказках читается? Впишите одно значение, сохраните **в том же
формате CSV** и загрузите:

```bash
uv run --env-file .env docreader eval load ~/…/eval/template-….csv
```

**Прислать:** вывод загрузки и одну строку — каким редактором открыт и сохранён файл,
читалась ли кириллица. Если кириллица испорчена — остановиться: формат меняется
отдельной задачей (research R-2).

### Б2. Слепой контроль: разметка до проверки (~30 мин)

```bash
uv run --env-file .env docreader eval blind pick
```

Заполните шаблон пяти договоров по их PDF, **не открывая** `fields` и страницу
проверки этих договоров. Загрузите:

```bash
uv run --env-file .env docreader eval blind load ~/…/eval/blind-….csv
```

**Прислать:** вывод обеих команд, время разметки и одну строку — хватило ли шаблона
и подсказок в нём без документации, понятны ли ошибки вида (SC-006).

### Б3. Проверка на странице (~1,5–2 ч, SC-008, SC-009)

```bash
uv run --env-file .env docreader eval review
```

Откройте страницу в браузере. Начните сверху (там карточки, требующие внимания);
«совпало» в конце — подтверждайте клавишей `1`, глядя на цитату. Можно прерваться:
ответы сохраняются в браузере. В конце нажмите «Скачать ответы», перенесите файл
из папки загрузок в папку данных (FR-006: в нём значения договоров) и загрузите:

```bash
mv ~/Downloads/gold-review-….json ~/…/eval/
uv run --env-file .env docreader eval load ~/…/eval/gold-review-….json
```

**Прислать:** вывод `review` (числа карточек по пометкам — для SC-009), вывод `load`,
время работы на странице (SC-008 ≤ 2,5 ч).

### Б4. Итог слепого контроля (SC-010)

```bash
uv run --env-file .env docreader eval blind report --label "первый эталон"
```

Расходящиеся пары — в файле разбора; откройте его сами, решите, кто прав, при
необходимости исправьте ответ на странице (`eval review` → новая страница уже
с ответами) и загрузите заново.

**Прислать:** вывод `blind report` (числа).

### Б5. Вопросы

1. Пункты для вопросов замера фичи 09 без пункта: скопируйте эти восемь вопросов
   (без `answer` и без `expected = "none"`) из `answers-09.toml` в
   `answers-09-no-clause.toml` и повторите замер только на них, чтобы получить
   машиночитаемый файл ответов (три сервера моделей, ~8 мин):

   ```bash
   scripts/answers_b4.sh --questions ~/…/questions/answers-09-no-clause.toml
   uv run --env-file .env docreader eval questions clauses \
     --answers ~/…/questions/answers-b4-….json --questions ~/…/questions/answers-09.toml
   ```

   Откройте предложенный файл, проверьте пункты (они уже подтверждены вами
   в замере 2026-11-26), сохраните.
2. Сгенерируйте вопросы из эталона и просмотрите файл (~15 мин), уберите неудачные:

   ```bash
   uv run --env-file .env docreader eval questions generate
   ```

3. Загрузите всё:

   ```bash
   uv run --env-file .env docreader eval questions load \
     ~/…/questions/rerank-08.toml ~/…/questions/answers-09-clauses-….toml \
     ~/…/questions/generated-….toml
   ```

**Прислать:** вывод трёх команд (составы и предупреждения).

### Б6. Первые записи таблицы результатов (SC-001, SC-007)

```bash
time uv run --env-file .env docreader eval fields --label "подсказка 05.1"
uv run --env-file .env docreader eval fields --source rules --label "правила 02.1"
uv run --env-file .env docreader eval search --label "после 02"
uv run --env-file .env python scripts/quickstart_search.py --questions ~/…/questions/rerank-08.toml
uv run --env-file .env docreader eval results
```

Ожидается: сравнение полей меньше минуты (SC-001); на вопросах набора фичи 08 места
`eval search` совпадают с местами `quickstart_search.py` того же запуска (SC-007;
сопоставьте через `eval show` записи поиска по ключам этих вопросов).

**Прислать:** вывод всех команд и время `eval fields`.

### Б7. Запись итогов (агент)

Агент записывает в `docs/tech-context.md` пункт «Эталонный набор (фича 02), …»:
состав эталона и путь его сборки, время ручной работы (SC-008), доля «совпало»
(SC-009), слепой контроль (SC-010), состав вопросов (SC-011), первые цифры полей,
правил и поиска; формат файлов (Б1). Невыполненный ориентир записывается, не
подгоняется.
