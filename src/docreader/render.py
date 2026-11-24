"""Rendering of the `docreader add` intake report (pure functions, no I/O).

The report dict has the shape described in specs/001-document-intake/contracts/cli.md.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import PurePath
from typing import TYPE_CHECKING

from docreader.fields import Result
from docreader.fields import spec as field_spec
from docreader.quality import FLAG_NAMES, FLAG_ORDER
from docreader.stages import STAGES, Stage, State

if TYPE_CHECKING:
    from docreader.clauseview import ClauseView, Outline, OutlineRecord
    from docreader.extraction import ExtractedDocument, ExtractRun
    from docreader.fieldview import FieldsView, FieldView
    from docreader.indexing import IndexedDocument, IndexRun
    from docreader.parsing import ParsedDocument, ParseRun
    from docreader.passageview import PassageView
    from docreader.search import Hit, SearchResult

_KIND_LABELS = (
    ("text", "текст"),
    ("scan", "скан"),
    ("scan_with_text", "скан с текстом"),
)
_MIN_NAME_WIDTH = 20
_INTERRUPTED_LINE = (
    "Прервано: уже добавленные документы сохранены, "
    "повторный запуск добавит остальные"
)


def render_intake_json(report: dict) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def render_intake_text(report: dict, report_path: str) -> str:
    lines = [_header(report), ""]

    files = report["files"]
    groups = (
        ("added", "Добавлено", _added_lines),
        ("existing", "Уже есть", _existing_lines),
        ("rejected", "Не добавлено", _rejected_lines),
    )
    for status, title, render_group in groups:
        entries = [entry for entry in files if entry["status"] == status]
        if not entries:
            continue
        lines.append(f"{title}: {len(entries)}")
        lines.extend(render_group(entries))

    lines.append("")
    lines.append(_footer(report, report_path))
    if report.get("interrupted"):
        lines.append(_INTERRUPTED_LINE)
    return "\n".join(lines) + "\n"


def _header(report: dict) -> str:
    started = datetime.fromisoformat(report["started_at"])
    return (
        f"Запуск {report['run_id']}, {started.strftime('%Y-%m-%d %H:%M')}, "
        f"версия {report['code_version']}"
    )


def _footer(report: dict, report_path: str) -> str:
    totals = report["totals"]
    return (
        f"Всего файлов: {totals['files']}, время {_elapsed(report)}. "
        f"Отчёт: {report_path}"
    )


def _elapsed(report: dict) -> str:
    if report.get("finished_at") is None:
        return "—"
    started = datetime.fromisoformat(report["started_at"])
    finished = datetime.fromisoformat(report["finished_at"])
    seconds = (finished - started).total_seconds()
    return f"{seconds:.1f}".replace(".", ",") + " с"


def _name(entry: dict) -> str:
    return PurePath(entry["path"]).name


def _name_width(entries: list[dict]) -> int:
    return max([_MIN_NAME_WIDTH] + [len(_name(entry)) for entry in entries])


def _kind_text(page_kinds: dict) -> str:
    return ", ".join(
        f"{label} {page_kinds[key]}"
        for key, label in _KIND_LABELS
        if page_kinds.get(key, 0)
    )


def _added_lines(entries: list[dict]) -> list[str]:
    width = _name_width(entries)
    lines: list[str] = []
    for entry in entries:
        line = (
            f"  {entry['document_id']}  {_name(entry).ljust(width)} "
            f"{entry['page_count']:>3} стр."
        )
        kinds = _kind_text(entry.get("page_kinds", {}))
        if kinds:
            line += f"  {kinds}"
        lines.append(line)
        for warning in entry.get("warnings", []):
            lines.append(f"          ! {warning['message']}")
    return lines


def _existing_lines(entries: list[dict]) -> list[str]:
    width = _name_width(entries)
    lines: list[str] = []
    for entry in entries:
        lines.append(f"  {_name(entry).ljust(width)} → {entry['document_id']}")
        for warning in entry.get("warnings", []):
            lines.append(f"          ! {warning['message']}")
    return lines


def _rejected_lines(entries: list[dict]) -> list[str]:
    width = _name_width(entries)
    return [f"  {_name(entry).ljust(width)} {entry['reason']}" for entry in entries]


# --- reclassify, page-kinds-check ----------------------------------------------------------

_KIND_NAMES = {
    "text": "готовый текст",
    "scan": "скан",
    "scan_with_text": "скан со встроенным текстом",
}
_KIND_CODES = ("text", "scan", "scan_with_text")


def _percent(share: float) -> str:
    return f"{share * 100:.1f}".replace(".", ",") + "%"


def render_reclassify_text(result: dict) -> str:
    lines = [
        f"Запуск {result['run_id']}: проверено документов {result['documents_checked']}, "
        f"страниц {result['pages_checked']}; изменили вид: {result['pages_changed']} стр."
    ]
    for doc in result["documents"]:
        changes = ", ".join(
            f"стр. {p['page_number']}: {_KIND_NAMES[p['old_kind']]} → {_KIND_NAMES[p['new_kind']]}"
            for p in doc["pages"]
        )
        lines.append(f"  {doc['document_id']}: {changes}")
    return "\n".join(lines) + "\n"


def render_page_kinds_text(result: dict) -> str:
    lines = [
        f"Страниц: {result['total']}, верно: {result['correct']}, "
        f"точность: {_percent(result['accuracy'])}",
        "",
        "Матрица ошибок (строки — разметка, столбцы — система):",
    ]
    width = max(len(code) for code in _KIND_CODES)
    lines.append(" " * width + "  " + "  ".join(code.rjust(width) for code in _KIND_CODES))
    for labelled in _KIND_CODES:
        cells = "  ".join(str(result["matrix"][labelled][s]).rjust(width) for s in _KIND_CODES)
        lines.append(f"{labelled.ljust(width)}  {cells}")
    if result["mismatches"]:
        lines += ["", "Несовпадения:"]
        for m in result["mismatches"]:
            invisible = m["invisible_text_share"]
            lines.append(
                f"  {m['document_id']} стр. {m['page_number']}: разметка {m['labelled']}, "
                f"система {m['stored']}; символов {m['char_count']}, "
                f"доля картинок {m['image_coverage']:.2f}, "
                f"доля невидимого текста {'—' if invisible is None else f'{invisible:.2f}'}"
            )
    return "\n".join(lines) + "\n"


# --- list, show, verify --------------------------------------------------------------

STATE_LABELS = {
    State.PENDING: "ожидает",
    State.DONE: "готово",
    State.NEEDS_REVIEW: "требует просмотра",
    State.FAILED: "ошибка",
}
KIND_LABELS = {
    "text": "готовый текст",
    "scan": "скан",
    "scan_with_text": "скан со встроенным текстом",
}
_STAGE_NAMES = {
    Stage.RECOGNITION: "Распознавание",
    Stage.READING: "Чтение",
    Stage.STRUCTURE: "Структура",
    Stage.EXTRACTION: "Извлечение",
    Stage.CHECKS: "Проверки",
    Stage.INDEXING: "Индексация",
}
_LIST_HEADER = [
    "ID", "Имя", "Стр.", "Текст", "Скан", "Скан+т",
    "Распозн.", "Чтение", "Структура", "Извлеч.", "Проверки", "Индекс.",
]
_LIST_NUMERIC_COLUMNS = {2, 3, 4, 5}
_LIST_NAME_LIMIT = 40
_PROBLEM_TEXT = {
    "missing": "копия отсутствует",
    "mismatch": "копия изменена (SHA-256 не совпадает)",
}


def _truncate_name(name: str) -> str:
    if len(name) > _LIST_NAME_LIMIT:
        return name[: _LIST_NAME_LIMIT - 1] + "…"
    return name


def _state_label(stages: dict, stage: str) -> str:
    info = stages.get(stage)
    if info is None:
        return "—"
    return STATE_LABELS.get(info["state"], info["state"])


def render_list_text(docs: list[dict]) -> str:
    if not docs:
        return "Реестр пуст"
    rows = [_LIST_HEADER]
    for doc in docs:
        kinds = doc["page_kinds"]
        row = [
            doc["id"],
            _truncate_name(doc["original_name"]),
            str(doc["page_count"]),
            str(kinds.get("text", 0)),
            str(kinds.get("scan", 0)),
            str(kinds.get("scan_with_text", 0)),
        ]
        row += [_state_label(doc["stages"], stage) for stage in STAGES]
        rows.append(row)
    widths = [max(len(row[col]) for row in rows) for col in range(len(_LIST_HEADER))]
    lines = []
    for row in rows:
        cells = [
            cell.rjust(width) if col in _LIST_NUMERIC_COLUMNS else cell.ljust(width)
            for col, (cell, width) in enumerate(zip(row, widths, strict=True))
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def _minute_text(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")


def _decimal_text(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def _recognition_text(rec: dict) -> str:
    if rec["error"]:
        return f"ошибка распознавания: {rec['error']}"
    quality = "—" if rec["quality"] is None else _decimal_text(rec["quality"])
    return (
        f"распознано {rec['engine']} {rec['engine_version']}, {rec['dpi']} dpi, "
        f"{_minute_text(rec['recognized_at'])}, оценка {quality}"
    )


def _share_text(share: float | None) -> str:
    return "—" if share is None else f"{share * 100:.0f}%"


def render_show_text(doc: dict) -> str:
    kinds = doc["page_kinds"]
    lines = [
        f"{doc['id']}  {doc['original_name']}",
        f"SHA-256: {doc['sha256']}",
        f"Копия: {doc['copy_path']}",
        f"Источник: {doc['source_path']}",
        f"Размер: {doc['size_bytes']} байт",
        f"Добавлен: {_minute_text(doc['added_at'])}",
        f"Заметка: {doc['note'] or '—'}",
        f"Запуск добавления: {doc['intake_run_id']}",
        "Виды страниц: "
        + ", ".join(f"{label} {kinds.get(kind, 0)}" for kind, label in KIND_LABELS.items()),
        "",
        "Этапы:",
    ]
    for stage in STAGES:
        info = doc["stages"].get(stage)
        if info is None:
            lines.append(f"  {_STAGE_NAMES[stage]}: —")
            continue
        line = f"  {_STAGE_NAMES[stage]}: {STATE_LABELS.get(info['state'], info['state'])}"
        if info["reason"]:
            line += f" — {info['reason']}"
        lines.append(line)
    lines += ["", "Страницы:"]
    for page in doc["pages"]:
        lines.append(
            f"  {page['page_number']}  {KIND_LABELS[page['kind']]}"
            f"  символов {page['char_count']}"
            f"  изображения {page['image_coverage'] * 100:.0f}%"
            f"  невидимый текст {_share_text(page['invisible_text_share'])}"
            + (f"  {_recognition_text(page['recognition'])}" if page.get("recognition") else "")
        )
    return "\n".join(lines)


def render_verify_text(result: dict) -> str:
    problems = result["problems"]
    if not problems:
        return f"Копии в порядке: {result['checked']}"
    lines = [
        f"{p['document_id']}  {p['copy_path']}  — {_PROBLEM_TEXT[p['problem']]}"
        for p in problems
    ]
    lines.append(f"Проверено: {result['checked']}, с ошибками: {len(problems)}")
    return "\n".join(lines)


# --- read, text, text --page ---------------------------------------------------------

_READ_STATE_WORDS = {
    State.DONE: "готово",
    State.NEEDS_REVIEW: "требует просмотра",
    State.FAILED: "ошибка",
}


def _documents_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "документ"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "документа"
    return "документов"


def render_read_text(result: dict) -> str:
    documents = result["documents"]
    count = len(documents)
    lines = [f"Чтение, запуск {result['run_id']}: {count} {_documents_word(count)}"]
    for doc in documents:
        line = (
            f"{doc['id']}  {doc['pages']:>2} стр.  "
            f"{_READ_STATE_WORDS.get(doc['state'], doc['state'])}"
        )
        if doc["reason"]:
            line += f": {doc['reason']}"
        lines.append(line)
    changed = [doc["id"] for doc in documents if doc["text_changed"]]
    if changed:
        lines.append("Текст изменился, следующие этапы сброшены: " + ", ".join(changed))
    totals = result["totals"]
    lines.append(
        f"Итого: готово {totals[State.DONE]}, требует просмотра {totals[State.NEEDS_REVIEW]}, "
        f"ошибка {totals[State.FAILED]}"
    )
    return "\n".join(lines)


def _flag_lines(flags: list[dict]) -> list[str]:
    return [
        f"! {FLAG_NAMES.get(flag['code'], flag['code'])}: {flag['reason']}"
        for flag in flags
    ]


def render_document_text(view: dict) -> str:
    lines: list[str] = []
    for page in view["pages"]:
        lines.append(f"── стр. {page['page']} ──")
        lines.extend(_flag_lines(page["flags"]))
        text = page["text"]
        lines.append(text if text.strip() else "(нет текста)")
    return "\n".join(lines)


_ROLE_WORDS = {
    "body": "текст",
    "header": "колонтитул",
    "footer": "нижний колонтитул",
    "page_number": "номер стр.",
    "rotated": "повёрнут",
}


def _line_marker(line: dict) -> str:
    """Column or table-cell mark; table indices are 0-based in storage, shown 1-based."""
    table = line["table"]
    if table is not None:
        return f"табл. {table['t'] + 1} стр. {table['row'] + 1} яч. {table['cell'] + 1}"
    if line["column"] is not None:
        return f"кол. {line['column']}"
    return ""


def _page_line_rows(page_lines: list[dict]) -> list[str]:
    """One aligned row per line: index, role word, optional marker, confidence, text."""
    roles = [_ROLE_WORDS.get(line["role"], line["role"]) for line in page_lines]
    markers = [_line_marker(line) for line in page_lines]
    role_width = max((len(role) for role in roles), default=0)
    marker_width = max((len(marker) for marker in markers), default=0)
    rows: list[str] = []
    for line, role, marker in zip(page_lines, roles, markers, strict=True):
        cells = [f"{line['i']:>3}", role.ljust(role_width)]
        if marker_width:
            cells.append(marker.ljust(marker_width))
        if "confidence" in line:
            cells.append(_decimal_text(line["confidence"]))
        cells.append(line["text"])
        rows.append("  ".join(cells).rstrip())
    return rows


def _source_line(page: dict) -> str:
    if page.get("source") != "recognized":
        return "Источник: текстовый слой PDF"
    quality = page.get("quality")
    score = "—" if quality is None else _decimal_text(quality)
    return (
        f"Источник: распознано ({page.get('engine')} {page.get('engine_version')}, "
        f"оценка {score})"
    )


def render_page_text(view: dict) -> str:
    blocks: list[str] = []
    for page in view["pages"]:
        lines = [f"{view['id']}, стр. {page['page']}"]
        lines.extend(_flag_lines(page["flags"]) or ["Флаги: нет"])
        if "source" in page and page["lines"]:  # a page without lines has no source to name
            lines.append(_source_line(page))
        if page["has_table"]:
            lines.append("Таблица: есть")
        if not page["lines"]:
            lines.append("(строк нет)")
        lines.extend(_page_line_rows(page["lines"]))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_find_text(view: dict) -> str:
    """Matches of `text --find`; each match carries a `context` string."""
    if not view["matches"]:
        return "Не найдено"
    return "\n".join(
        f"стр. {m['page']}, строка {m['line']}, {m['role']}: …{m['context']}…"
        for m in view["matches"]
    )


# --- reading report ------------------------------------------------------------------

_REPORT_HEADER = [
    "ID", "Имя", "Стр.", "Прочит.", "Скан", "Распозн.", "Нечит.", "Не рус.",
    "Пустые", "Порядок", "Низк. кач.", "Без текста", "Таблицы", "Состояние",
]
_REPORT_TOTAL_LABEL = "Итого"
NO_READ_DOCUMENTS = "Нет прочитанных документов — выполните docreader read"


def _report_rows(report: dict) -> list[list[str]]:
    """Header, one row per document and the totals row, all as strings."""
    rows = [list(_REPORT_HEADER)]
    for doc in report["documents"]:
        rows.append(
            [
                doc["id"],
                doc["name"],
                str(doc["pages"]),
                str(doc["read"]),
                *(str(doc["flags"][code]) for code in FLAG_ORDER),
                str(doc["tables"]),
                _READ_STATE_WORDS.get(doc["state"], doc["state"]),
            ]
        )
    totals = report["totals"]
    rows.append(
        [
            _REPORT_TOTAL_LABEL,
            "",
            str(totals["pages"]),
            str(totals["read"]),
            *(str(totals["flags"][code]) for code in FLAG_ORDER),
            str(totals["tables"]),
            "",
        ]
    )
    return rows


def render_read_report_text(report: dict) -> str:
    rows = _report_rows(report)
    widths = [max(len(row[col]) for row in rows) for col in range(len(_REPORT_HEADER))]
    lines = []
    for row in rows:
        cells = [
            cell.ljust(width) if col in (0, 1, 11) else cell.rjust(width)
            for col, (cell, width) in enumerate(zip(row, widths, strict=True))
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def render_read_report_csv(report: dict) -> str:
    """CSV text (`;` separated, CRLF); the writer adds the BOM through `utf-8-sig`."""
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";").writerows(_report_rows(report))
    return buffer.getvalue()


# --- recognize (contracts/cli.md) ------------------------------------------------------

_RECOGNIZE_FLAG_LABELS = (
    ("low_recognition_quality", "низкое качество"),
    ("scan_no_text", "без текста"),
    ("empty", "пустых"),
)


def _scans_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "скан"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "скана"
    return "сканов"


def _decimal(value: float) -> str:
    """One decimal place with a decimal comma: 3.8 → «3,8»."""
    return f"{value:.1f}".replace(".", ",")


def render_recognize_progress(
    doc_id: str, page: int, done: int, total: int, seconds: float
) -> str:
    """One stderr line per recognised page: `D-0003 стр. 87 (1/52)  3,8 с`.

    `page` is the page number; `done` of `total` counts the pages of this run only.
    """
    return f"{doc_id} стр. {page} ({done}/{total})  {_decimal(seconds)} с"


def _recognize_head(doc: dict) -> str:
    """Document id, scan count and, when there are scans, the statistics."""
    head = f"{doc['id']}  {doc['scan_pages']:>2} {_scans_word(doc['scan_pages'])}"
    if not doc["scan_pages"]:
        return head
    flags = doc["flags"]
    parts = [
        f"распознано {doc['recognized']}",
        f"ошибок {doc['errors']}",
        *(f"{label} {len(flags.get(code, []))}" for code, label in _RECOGNIZE_FLAG_LABELS),
        f"{round(doc['seconds'])} с",
    ]
    return "  ".join([head, *parts])


def render_recognize_text(data: dict) -> str:
    documents = data["documents"]
    count = len(documents)
    run = f"запуск {data['run_id']}"
    if data["engine"] is None:
        header = f"Распознавание, {run}"
    else:
        engine = f"{data['engine']} {data['engine_version']}, {data['dpi']} dpi"
        header = f"Распознавание, {run} ({engine})"
    lines = [f"{header}: {count} {_documents_word(count)}"]

    heads = [_recognize_head(doc) for doc in documents]
    # rows without scans are padded so that their state lines up with the others
    width = max(
        (len(head) for doc, head in zip(documents, heads, strict=True) if doc["scan_pages"]),
        default=0,
    )
    for doc, head in zip(documents, heads, strict=True):
        state = STATE_LABELS.get(doc["state"], doc["state"])
        if doc["reason"]:
            state += f": {doc['reason']}"
        padded = head if doc["scan_pages"] else head.ljust(width)
        lines.append(f"{padded}  {state}")

    reset = [doc["id"] for doc in documents if doc["reading_reset"]]
    if reset:
        lines.append(
            "Чтение сброшено (распознанный текст изменён): "
            f"{', '.join(reset)} — выполните docreader read"
        )

    totals = data["totals"]
    total_line = (
        f"Итого: страниц {totals['pages']}, распознано {totals['recognized']}, "
        f"ошибок {totals['errors']}, "
        f"низкое качество {totals['flags'].get('low_recognition_quality', 0)}"
    )
    if totals["pages"]:
        average = totals["seconds"] / totals["pages"]
        total_line += (
            f"; {round(totals['seconds'])} с, в среднем {_decimal(average)} с/стр."
        )
    lines.append(total_line)
    return "\n".join(lines)


# --- recognize-eval (contracts/cli.md) -----------------------------------------------

_EVAL_VALUE_LABELS = (
    ("inn", "ИНН"),
    ("kpp", "КПП"),
    ("ogrn", "ОГРН"),
    ("amount", "суммы"),
    ("date", "даты"),
    ("clause", "пункты"),
)


def _pages_word(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "страница"
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return "страницы"
    return "страниц"


def render_recognize_eval_text(data: dict, report_path: str, *, with_diff: bool = False) -> str:
    """Numbers of `recognize-eval`; the contract text appears only with `with_diff`."""
    totals = data["totals"]
    lines = []
    head = (
        f"Замер распознавания: {totals['pages']} {_pages_word(totals['pages'])} "
        f"из {totals['documents']} {_documents_word(totals['documents'])}"
    )
    if data["engine"] is not None:
        head += f"; {data['engine']} {data['engine_version']}, {data['dpi']} dpi"
    lines.append(head)

    if totals["char_accuracy"] is None:
        lines.append("Верных знаков: нет распознанных страниц")
    else:
        per_page = sorted(p["char_accuracy"] for p in data["pages"])
        middle = len(per_page) // 2
        median = per_page[middle] if len(per_page) % 2 else (
            (per_page[middle - 1] + per_page[middle]) / 2
        )
        lines.append(
            f"Верных знаков: {_percent(totals['char_accuracy'])} "
            f"(по страницам: мин. {_percent(per_page[0])}, медиана {_percent(median)})"
        )

    if totals["values_share"] is None:
        lines.append("Реквизиты и числа без ошибок: в проверенных текстах значений нет")
    else:
        parts = [
            f"{label} {totals['values'][kind][0]}/{totals['values'][kind][1]}"
            for kind, label in _EVAL_VALUE_LABELS
            if kind in totals["values"]
        ]
        lines.append(
            f"Реквизиты и числа без ошибок: {_percent(totals['values_share'])} "
            f"({', '.join(parts)})"
        )

    control = data["control"]
    if control["share"] is None:
        lines.append("Контрольные строки: нет (нет файла control.csv или он пуст)")
    else:
        lines.append(
            f"Контрольные строки: {_percent(control['share'])} "
            f"({control['found']} из {control['total']})"
        )
    lines.append(
        f"Пропущено строк: {totals['missing_lines']}; повторено строк: {totals['repeated_lines']}"
    )
    flags = data.get("flags")
    if flags is None:
        lines.append("Флаг «низкое качество»: нет (нет файла flags.csv или он пуст)")
    else:
        lines.append(
            f"Флаг «низкое качество»: верен в {_percent(flags['accuracy'])} "
            f"(ложных {flags['false_positive']}, "
            f"пропущено {flags['false_negative']} из {flags['checked']})"
        )
    not_recognized = data["not_recognized"]
    if not_recognized:
        listed = ", ".join(f"{item['id']} стр. {item['page']}" for item in not_recognized)
        lines.append(f"Не распознаны: {listed}")
    else:
        lines.append("Не распознаны: нет")
    lines.append(f"Результат сохранён: {report_path}")

    if with_diff:
        lines.append("")
        lines.append("Расхождения (страница; ожидалось; распознано):")
        for item in data["diffs"]:
            got = item["recognised"] if item["recognised"] is not None else "(строки нет)"
            lines.append(f"{item['id']} стр. {item['page']}; {item['expected']}; {got}")
    return "\n".join(lines)


# --- recognize-report (contracts/cli.md, US7, FR-018) ----------------------------------

_RECOGNITION_HEADER = [
    "ID", "Имя", "Сканы", "Распозн.", "Ошибки", "Низк. кач.", "Без текста", "Пустые",
    "Ср. оценка", "Время, с", "Состояние",
]
_RECOGNITION_LEFT_COLUMNS = (0, 1, 10)
_RECOGNITION_TOTAL_LABEL = "Итого"
NO_SCAN_DOCUMENTS = "Нет документов со страницами-сканами"
NO_REVIEW_PAGES = "Нет страниц на просмотр"
_REVIEW_HEADER = ["ID", "Стр.", "Проблема", "Причина", "Оценка"]
_RECOGNITION_ERROR_CODE = "recognition_error"
_RECOGNITION_ERROR_NAME = "ошибка распознавания"


def _quality_cell(value: float | None) -> str:
    return "—" if value is None else _decimal_text(value)


def _aligned(rows: list[list[str]], left_columns: tuple[int, ...]) -> str:
    """Columns padded to the widest cell; numbers right-aligned, text left-aligned."""
    widths = [max(len(row[col]) for row in rows) for col in range(len(rows[0]))]
    lines = []
    for row in rows:
        cells = [
            cell.ljust(width) if col in left_columns else cell.rjust(width)
            for col, (cell, width) in enumerate(zip(row, widths, strict=True))
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def _csv_text(rows: list[list[str]]) -> str:
    """CSV text (`;` separated); the writer adds the BOM through `utf-8-sig`."""
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";").writerows(rows)
    return buffer.getvalue()


def _recognition_stats(label: str, name: str, data: dict, state: str) -> list[str]:
    flags = data["flags"]
    return [
        label,
        name,
        str(data["scan_pages"]),
        str(data["recognized"]),
        str(data["errors"]),
        str(flags["low_recognition_quality"]),
        str(flags["scan_no_text"]),
        str(flags["empty"]),
        _quality_cell(data["mean_quality"]),
        str(round(data["seconds"])),
        state,
    ]


def _recognition_rows(report: dict) -> list[list[str]]:
    """Header, one row per document and the totals row, all as strings."""
    rows = [list(_RECOGNITION_HEADER)]
    for doc in report["documents"]:
        state = STATE_LABELS.get(doc["state"], doc["state"])
        rows.append(_recognition_stats(doc["id"], doc["name"], doc, state))
    rows.append(_recognition_stats(_RECOGNITION_TOTAL_LABEL, "", report["totals"], ""))
    return rows


def render_recognition_table(report: dict) -> str:
    """Text table of `recognize-report` (the report dict is `RecognitionReport.to_json()`)."""
    return _aligned(_recognition_rows(report), _RECOGNITION_LEFT_COLUMNS)


def render_recognition_csv(report: dict) -> str:
    return _csv_text(_recognition_rows(report))


def _problem_name(code: str) -> str:
    if code == _RECOGNITION_ERROR_CODE:
        return _RECOGNITION_ERROR_NAME
    return FLAG_NAMES[code]


def render_review_text(pages: list[dict]) -> str:
    """One line per page to review: `D-0005  стр. 17  <problem>  <reason>`."""
    return "\n".join(
        f"{p['id']}  стр. {p['page']}  {_problem_name(p['code'])}  {p['reason']}"
        for p in pages
    )


def render_review_csv(pages: list[dict]) -> str:
    rows = [list(_REVIEW_HEADER)]
    rows += [
        [
            p["id"],
            str(p["page"]),
            _problem_name(p["code"]),
            p["reason"],
            _quality_cell(p["quality"]),
        ]
        for p in pages
    ]
    return _csv_text(rows)


_PARSE_STATE_WORDS = {
    "done": "готово",
    "needs_review": "требует просмотра",
    "failed": "ошибка",
}
_PARSE_STATE_WIDTH = 17
_PARSE_FAILED_WORD = "ошибка"


def _page_text(page: int | None) -> str:
    return "—" if page is None else str(page)


def _parse_document_line(doc: ParsedDocument) -> str:
    if doc.state == "failed":
        line = f"{doc.document_id}  {_PARSE_FAILED_WORD:<{_PARSE_STATE_WIDTH}}  "
        return line + doc.reason if doc.reason else line.rstrip()
    word = _PARSE_STATE_WORDS.get(doc.state, doc.state)
    line = (
        f"{doc.document_id}  {word:<{_PARSE_STATE_WIDTH}}  "
        f"разделов {doc.sections}, пунктов {doc.clauses}, "
        f"стр. {_page_text(doc.first_page)}–{_page_text(doc.last_page)}"
    )
    if doc.reason is not None:
        line += f" — {doc.reason}"
    return line


def render_parse_text(result: ParseRun) -> str:
    """Text of `docreader parse` (contracts/cli.md); no text of the contracts."""
    lines = [_parse_document_line(doc) for doc in result.documents]
    lines += [f"{item.document_id}  пропущен           {item.reason}" for item in result.skipped]
    totals = result.totals
    total = (
        f"Итого: разобрано {totals['parsed']}, требует просмотра {totals['needs_review']}, "
        f"ошибок {totals['failed']}, пропущено {totals['skipped']}"
    )
    if result.run_id is not None:
        total += f" (запуск {result.run_id})"
    lines.append(total)
    return "\n".join(lines)


NOTHING_TO_EXTRACT = (
    "Нечего извлекать: поля всех договоров заполнены (заново: docreader extract --all)"
)
_EXTRACT_STATE_WORDS = {
    "done": "готово",
    "needs_review": "требует просмотра",
    "failed": "ошибка",
}
_EXTRACT_STATE_WIDTH = 17
_EXTRACT_FAILED_WORD = "ошибка"


def _field_labels(names: list[str]) -> str:
    return ", ".join(field_spec(name).label for name in names)


def _extract_document_line(doc: ExtractedDocument) -> str:
    if doc.state == "failed":
        line = f"{doc.document_id}  {_EXTRACT_FAILED_WORD:<{_EXTRACT_STATE_WIDTH}}  "
        return line + doc.reason if doc.reason else line.rstrip()
    word = _EXTRACT_STATE_WORDS.get(doc.state, doc.state)
    not_found = f" ({_field_labels(doc.not_found_fields)})" if doc.not_found_fields else ""
    rejected = f" ({_field_labels(doc.rejected_fields)})" if doc.rejected_fields else ""
    line = (
        f"{doc.document_id}  {word:<{_EXTRACT_STATE_WIDTH}}  "
        f"найдено {doc.found}, не найдено {doc.not_found}{not_found}, "
        f"отклонено {doc.rejected}{rejected}"
    )
    if doc.reason is not None:
        line += f" — {doc.reason}"
    return line


def render_extract_text(result: ExtractRun) -> str:
    """Text of `docreader extract` (contracts/cli.md «docreader extract»).

    Field values and quotes are never printed: the result carries none of them.
    """
    if not result.documents and not result.skipped and result.stopped is None:
        return NOTHING_TO_EXTRACT
    lines = [_extract_document_line(doc) for doc in result.documents]
    lines += [f"{item.document_id}  пропущен           {item.reason}" for item in result.skipped]
    if result.stopped is not None:
        lines.append(f"Остановлено на {result.stopped.document_id}: {result.stopped.reason}")
    totals = result.totals
    total = (
        f"Итого: извлечено {totals['extracted']}, требует просмотра {totals['needs_review']}, "
        f"ошибок {totals['failed']}, пропущено {totals['skipped']}; "
        f"полей найдено {totals['fields_found']}, не найдено {totals['fields_not_found']}, "
        f"отклонено {totals['fields_rejected']}"
    )
    if result.run_id is not None:
        details = (
            f"запуск {result.run_id}, модель {result.model}, "
            f"подсказка {result.prompt_version}"
        )
        total += f" ({details})"
    lines.append(total)
    return "\n".join(lines)

_OUTLINE_STATE_WORDS: dict[str, str] = {
    State.DONE: "готово",
    State.NEEDS_REVIEW: "требует просмотра",
    State.FAILED: "ошибка",
    State.PENDING: "ожидает",
}
_RECOGNIZED_MARK = " [распознано]"
_LOW_QUALITY_MARK = " [низкое качество распознавания]"
_UNREAD_LABEL = "—"


def _pages_text(first: int, last: int) -> str:
    return f"стр. {first}" if first == last else f"стр. {first}–{last}"


def _outline_number_cell(record: OutlineRecord) -> str:
    """The printed number indented by depth; a section also shows its title after the number."""
    number = record.number_printed or ""
    if record.kind == "section" and record.title:
        number = f"{number} {record.title}" if number else record.title
    return " " * (2 * max(record.depth - 1, 0)) + number


def _head_without_number(record: OutlineRecord) -> str:
    """The head after the number, which the number column already shows (contracts/cli.md)."""
    number = record.number_printed
    if number and record.head.startswith(number):
        return record.head[len(number) :].lstrip()
    return record.head


def render_outline_text(outline: Outline) -> str:
    """Text of `docreader outline` (contracts/cli.md «docreader outline»)."""
    state_word = _OUTLINE_STATE_WORDS.get(outline.state, outline.state)
    header = (
        f"{outline.document_id} — разбор от {outline.parsed_at} "
        f"(запуск {outline.run_id}), {state_word}"
    )
    if outline.reason is not None:
        header += f" — {outline.reason}"
    records = outline.records
    id_width = max((len(r.id) for r in records), default=0) + 2
    cells = [_outline_number_cell(r) for r in records]
    cell_width = max((len(c) for c in cells), default=0) + 2
    pages = [_pages_text(r.first_page, r.last_page) for r in records]
    page_width = max((len(p) for p in pages), default=0) + 2

    # an unread page goes after the last record that ends before it
    unread_after: dict[int, list[int]] = {}
    for page in sorted(outline.unread_pages):
        anchor = max((i for i, r in enumerate(records) if r.last_page < page), default=-1)
        unread_after.setdefault(anchor, []).append(page)

    def unread_lines(anchor: int) -> list[str]:
        return [
            _UNREAD_LABEL.ljust(id_width) + f"страница {page} не прочитана"
            for page in unread_after.get(anchor, [])
        ]

    lines = [header, *unread_lines(-1)]
    for i, record in enumerate(records):
        text = "" if record.kind == "section" else _head_without_number(record)
        line = (
            record.id.ljust(id_width) + cells[i].ljust(cell_width) + pages[i].ljust(page_width)
            + text
        ).rstrip()
        if record.recognized:
            line += _RECOGNIZED_MARK
        if record.low_quality:
            line += _LOW_QUALITY_MARK
        lines.append(line)
        lines.extend(unread_lines(i))
    return "\n".join(lines)


def render_clause_text(view: ClauseView) -> str:
    """Text of `docreader clause` (contracts/cli.md «docreader clause»)."""
    header = view.id
    if view.section_title:
        header += f" — {view.section_title}"
    header += f", {_pages_text(view.first_page, view.last_page)}"
    if view.recognized:
        header += _RECOGNIZED_MARK
    if not view.records:
        return header
    # each part is stored with its number and a final newline; parts follow one another
    parts = [part.text.rstrip("\n") for part in view.records]
    return "\n".join([header, "", *parts])


_FIELDS_STATE_WORDS: dict[str, str] = {
    State.DONE: "готово",
    State.NEEDS_REVIEW: "требует просмотра",
    State.FAILED: "ошибка",
    State.PENDING: "ожидает",
}
_FIELDS_RESULT_WORDS: dict[str, str] = {
    Result.FOUND: "найдено",
    Result.NOT_FOUND: "не найдено",
    Result.REJECTED: "отклонено",
    Result.FAILED: "ошибка",
}
_FIELDS_LABEL_WIDTH = 20
_FIELDS_RESULT_WIDTH = 12
_FIELDS_INDENT = " " * (_FIELDS_LABEL_WIDTH + _FIELDS_RESULT_WIDTH)
_FIELDS_LOW_QUALITY_MARK = " [низкое качество распознавания]"


def _one_line(text: str) -> str:
    """A quote on one line: every line break becomes a space."""
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _field_block(view: FieldsView, field: FieldView) -> list[str]:
    """Lines of one field in `fields` output (contracts/cli.md «docreader fields»)."""
    word = _FIELDS_RESULT_WORDS.get(field.result, field.result)
    head = f"{field.label:<{_FIELDS_LABEL_WIDTH}}{word:<{_FIELDS_RESULT_WIDTH}}"
    if field.result == Result.NOT_FOUND:
        return [f"{field.label:<{_FIELDS_LABEL_WIDTH}}{word}"]
    if field.result == Result.FOUND:
        line = (
            f"{head}{field.value_normalized or ''}"
            f"  (как в тексте: «{field.value_text or ''}»)"
        )
        if field.low_quality:
            line += _FIELDS_LOW_QUALITY_MARK
        if field.clause_id:
            where = field.clause_id
            if field.page is not None:
                where += f", стр. {field.page}"
        else:
            where = f"пункт не найден в разборе — выполните docreader extract {view.document_id}"
        return [
            line,
            _FIELDS_INDENT + where,
            _FIELDS_INDENT + f"«{_one_line(field.quote or '')}»",
        ]
    if field.result == Result.REJECTED:
        lines = [f"{head}{field.reason or ''}"]
        proposed = f"модель: «{field.proposed_value or ''}»"
        if field.proposed_clause:
            proposed += f", пункт {field.proposed_clause}"
        lines.append(_FIELDS_INDENT + proposed)
        if field.proposed_quote:
            lines.append(
                _FIELDS_INDENT + f"цитата модели: «{_one_line(field.proposed_quote)}»"
            )
        return lines
    return [f"{head}{field.reason or ''}"]


def render_fields_text(view: FieldsView) -> str:
    """Text of `docreader fields` (contracts/cli.md «docreader fields»)."""
    state_word = _FIELDS_STATE_WORDS.get(view.state, view.state)
    started = view.run_started_at.strftime("%Y-%m-%d")
    header = (
        f"{view.document_id} — извлечение от {started} "
        f"(запуск {view.run_id}, модель {view.model or '—'}, "
        f"подсказка {view.prompt_version or '—'}), {state_word}"
    )
    lines = [header]
    if view.reason is not None:
        lines.append(f"  {view.reason}")
    if not view.fields:
        return "\n".join(lines)
    lines.append("")
    for field in view.fields:
        lines.extend(_field_block(view, field))
    return "\n".join(lines)


NOTHING_TO_INDEX = (
    "Нечего индексировать: индексы всех договоров построены (заново: docreader index --all)"
)


def _index_document_line(doc: IndexedDocument) -> str:
    word = _EXTRACT_STATE_WORDS.get(doc.state, doc.state)
    prefix = f"{doc.document_id}  {word:<{_EXTRACT_STATE_WIDTH}}  "
    if doc.state == "failed":
        return prefix + doc.reason if doc.reason else prefix.rstrip()
    line = (
        f"{prefix}отрывков {doc.passages}, по словам {doc.word_entries}, "
        f"по смыслу {doc.vectors}"
    )
    if doc.reason is not None:
        line += f" — {doc.reason}"
    return line


def render_index_text(result: IndexRun) -> str:
    """Text of `docreader index` (contracts/cli.md «docreader index»); no labels, no text."""
    if not result.documents and not result.skipped and result.stopped is None:
        return NOTHING_TO_INDEX
    lines = [_index_document_line(doc) for doc in result.documents]
    lines += [f"{item.document_id}  пропущен           {item.reason}" for item in result.skipped]
    if result.stopped is not None:
        lines.append(f"Остановлено на {result.stopped.document_id}: {result.stopped.reason}")
    totals = result.totals
    total = (
        f"Итого: готово {totals['indexed']}, требует просмотра {totals['needs_review']}, "
        f"ошибок {totals['failed']}, пропущено {totals['skipped']}; "
        f"отрывков {totals['passages']}"
    )
    if result.run_id is not None:
        total += f" (запуск {result.run_id}, модель {result.model}, размерность {result.dims})"
    lines.append(total)
    return "\n".join(lines)


_PART_NAMES = {"preamble": "преамбула", "main": "основной текст", "tail": "реквизиты"}


def render_passage_text(view: PassageView) -> str:
    """Text of `docreader passage` (contracts/cli.md «docreader passage»)."""
    if view.first_page == view.last_page:
        pages = f"стр. {view.first_page}"
    else:
        pages = f"стр. {view.first_page}–{view.last_page}"
    part = _PART_NAMES.get(view.part, view.part)
    lines = [
        f"{view.clause_id} — {pages}, {part} "
        f"(индексация: запуск {view.run_id}, {view.run_date})",
        f"Метка: {view.label}",
        "В индексе по словам: да" if view.word_index else "В индексе по словам: нет",
    ]
    for vec in view.vectors:
        line = f"В индексе по смыслу: {vec.model}, размерность {vec.dims}"
        if vec.truncated:
            line += f" (вход обрезан до {vec.input_chars} знаков)"
        lines.append(line)
    lines += ["Текст:", view.text]
    return "\n".join(lines)


_SEARCH_TEXT_INDENT = "   "
_SEARCH_NOTHING_FOUND = "Ничего не найдено"


def _search_header(result: SearchResult) -> str:
    where = f" в {result.document_id}" if result.document_id else " по всем договорам"
    reranker = f"реранкер {result.reranker_model}" if result.reranked else "без реранкера"
    seconds = f"{result.seconds:.1f}".replace(".", ",")
    return (
        f"Запрос{where}, {reranker} — результатов {len(result.hits)} "
        f"(кандидатов по словам {result.word_candidates}, по смыслу {result.vector_candidates}), "
        f"{seconds} с"
    )


def _search_hit_lines(hit: Hit) -> list[str]:
    head = f"{hit.place}. {hit.clause_id}"
    if hit.first_page is not None:
        if hit.first_page == hit.last_page or hit.last_page is None:
            head += f"  стр. {hit.first_page}"
        else:
            head += f"  стр. {hit.first_page}–{hit.last_page}"
    lines = [head]
    if hit.rerank_score is not None:
        lines.append(f"  оценка {hit.rerank_score:.3f}")
    word = "—" if hit.word_place is None else str(hit.word_place)
    vector = "—" if hit.vector_place is None else str(hit.vector_place)
    lines.append(f"  (слова {word}, смысл {vector}, слияние {hit.fused_place})")
    lines.append(f"{_SEARCH_TEXT_INDENT}{hit.label}")
    lines += [f"{_SEARCH_TEXT_INDENT}{line}" for line in hit.text.splitlines()]
    return lines


def render_search_text(result: SearchResult) -> str:
    """Text of `docreader search` (contracts/cli.md «docreader search»)."""
    lines = [_search_header(result)]
    lines += [f"! {warning}" for warning in result.warnings]
    if not result.hits:
        lines.append(_SEARCH_NOTHING_FOUND)
        return "\n".join(lines) + "\n"
    lines.append("")
    blocks = [_search_hit_lines(hit) for hit in result.hits]
    for position, block in enumerate(blocks):
        if position:
            lines.append("")
        lines += block
    return "\n".join(lines) + "\n"
