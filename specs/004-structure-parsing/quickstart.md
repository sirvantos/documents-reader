# Quickstart: Разбор структуры (фича 04)

Часть А — на сервере разработки, только синтетика. Часть Б — на Mac аналитика,
реальные договоры; агенту присылается только то, что помечено «можно прислать».
Команды — [contracts/cli.md](contracts/cli.md), данные — [data-model.md](data-model.md).

## А. Сервер разработки

### А1. Автотесты

```bash
uv sync
scripts/check.sh
```

Ожидается: все тесты, ruff и mypy проходят; среди тестов — модульные тесты
`tests/unit/test_structure.py` и интеграционные `tests/integration/test_parse*.py`.

### А2. Ручной прогон на синтетическом договоре

Только временная папка данных и база `docreader_demo` (CLAUDE.md, «Machines»).

```bash
export DEMO=$(mktemp -d)
createdb docreader_demo 2>/dev/null || true
cat > "$DEMO/.env" <<EOF
DOCREADER_DATA_DIR=$DEMO/data
DOCREADER_DATABASE_URL=postgresql:///docreader_demo
DOCREADER_FORBID_MODELS=1
EOF
mkdir -p "$DEMO/data" "$DEMO/in"
uv run python -c "from tests.synthetic.make_pdfs import make_structured_contract as m; m('$DEMO/in/c.pdf')"
uv run --env-file "$DEMO/.env" docreader migrate
uv run --env-file "$DEMO/.env" docreader add "$DEMO/in"
uv run --env-file "$DEMO/.env" docreader read
uv run --env-file "$DEMO/.env" docreader parse
uv run --env-file "$DEMO/.env" docreader outline D-0001
uv run --env-file "$DEMO/.env" docreader clause D-0001/2.1
uv run --env-file "$DEMO/.env" docreader clause D-0001/2.1 --own
```

Ожидается:

- `parse`: D-0001 «требует просмотра» с причинами пропуска, повтора и непрочитанной
  страницы внутри основного текста (генератор их содержит);
- `outline`: преамбула, разделы, пункты до четвёртого уровня, строка «страница N
  не прочитана», хвост `D-0001/реквизиты`; приложение с «1.1» — внутри хвоста;
- `clause D-0001/2.1` — пункт с подпунктами, `--own` — только его текст;
- повторный `parse --all` даёт те же идентификаторы.

После проверки: `dropdb docreader_demo; rm -rf "$DEMO"`.

## Б. Mac аналитика

Перед началом: ветка `004-structure-parsing`, `uv sync --group ocr`, чтение
и распознавание набора выполнены (`docreader read` по текущим данным).

### Б1. Разбор набора и скорость (SC-005)

```bash
uv run --env-file .env docreader migrate
time uv run --env-file .env docreader parse --all
```

Ожидается: время `real` не больше минуты на 50 договоров; документов «ошибка» — 0;
«требует просмотра» — порядка 12 (обзор версии 3: пропуски и повторы) плюс единицы
по находкам «номер вне порядка», «заголовок раздела после его пункта» и «после начала
хвоста идёт раздел». Если помеченных намного больше — прислать вывод: правило
или порог нужно поправить.
**Можно прислать** вывод `parse` целиком и строку `real`: в нём только
идентификаторы, числа, номера пунктов и страниц.

### Б2. Ручная проверка границ на 5 договорах (SC-002)

Выбрать 5 договоров: D-0056 (у него основной текст — 5–20% по обзору), два
«готово» и два «требует просмотра» из Б1. Для каждого:

```bash
uv run --env-file .env docreader outline D-0056 > /tmp/outline-D-0056.txt
```

и сверить оглавление с исходным PDF: все ли разделы и пункты на месте, верны ли
номера, где начинается хвост (`D-0001/реквизиты` — строка «N. … реквизиты …»).
Спорный пункт посмотреть целиком: `docreader clause D-0056/5.2`.

**Можно прислать** только числа по каждому документу: сколько записей проверено,
сколько с неверным номером, сколько с неверной границей, где фактически начинается
хвост (номер раздела) — и для D-0056, совпал ли заголовок реквизитов с концом
договора. Текст оглавления не присылать.

Цель: не меньше 95% записей с верными номерами и границами.

### Б3. Повторный разбор даёт те же идентификаторы (SC-004)

```bash
ids() { for d in $(uv run --env-file .env docreader list --json | python3 -c 'import json,sys; print(" ".join(x["id"] for x in json.load(sys.stdin)))'); do
  uv run --env-file .env docreader outline "$d" --json 2>/dev/null | python3 -c 'import json,sys; print("\n".join(r["id"] for r in json.load(sys.stdin)["records"]))'
done | shasum -a 256; }
ids; uv run --env-file .env docreader parse --all >/dev/null; ids
```

Ожидается: две одинаковые строки отпечатка. **Можно прислать** обе строки.

## Что записать по итогам

- Время Б1 и итог числа — в `docs/tech-context.md` (раздел о разборе) и в отчёт фичи.
- Результат Б2 — число записей и доля верных по каждому из 5 договоров.
- Если Б2 показал систематическую ошибку — сначала синтетический случай
  в `tests/synthetic/` и падающий тест, потом исправление (CLAUDE.md, «Delivery»).
