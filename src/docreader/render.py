"""Rendering of the `docreader add` intake report (pure functions, no I/O).

The report dict has the shape described in specs/001-document-intake/contracts/cli.md.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import PurePath

from docreader.quality import FLAG_NAMES, FLAG_ORDER

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
    "pending": "ожидает",
    "done": "готово",
    "needs_review": "требует просмотра",
    "failed": "ошибка",
}
KIND_LABELS = {
    "text": "готовый текст",
    "scan": "скан",
    "scan_with_text": "скан со встроенным текстом",
}
_STAGE_ORDER = ("reading", "structure", "extraction", "checks", "indexing")
_STAGE_NAMES = {
    "reading": "Чтение",
    "structure": "Структура",
    "extraction": "Извлечение",
    "checks": "Проверки",
    "indexing": "Индексация",
}
_LIST_HEADER = [
    "ID", "Имя", "Стр.", "Текст", "Скан", "Скан+т",
    "Чтение", "Структура", "Извлеч.", "Проверки", "Индекс.",
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
        row += [_state_label(doc["stages"], stage) for stage in _STAGE_ORDER]
        rows.append(row)
    widths = [max(len(row[col]) for row in rows) for col in range(len(_LIST_HEADER))]
    lines = []
    for row in rows:
        cells = [
            cell.rjust(width) if col in _LIST_NUMERIC_COLUMNS else cell.ljust(width)
            for col, (cell, width) in enumerate(zip(row, widths))
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def _minute_text(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M")


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
    for stage in _STAGE_ORDER:
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
    "done": "готово",
    "needs_review": "требует просмотра",
    "failed": "ошибка",
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
        f"Итого: готово {totals['done']}, требует просмотра {totals['needs_review']}, "
        f"ошибка {totals['failed']}"
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


def _line_marker(line: dict) -> str:
    table = line["table"]
    if table is not None:
        return f"табл. {table['t']} стр. {table['row']} яч. {table['cell']}"
    if line["column"] is not None:
        return f"кол. {line['column']}"
    return ""


def _page_line_text(line: dict) -> str:
    cells = [f"{line['i']:>3}", line["role"]]
    marker = _line_marker(line)
    if marker:
        cells.append(marker)
    cells.append(line["text"])
    return "  ".join(cells)


def render_page_text(view: dict) -> str:
    blocks: list[str] = []
    for page in view["pages"]:
        lines = [f"{view['id']}, стр. {page['page']}"]
        lines.extend(_flag_lines(page["flags"]) or ["Флаги: нет"])
        if page["has_table"]:
            lines.append("Таблица: есть")
        if not page["lines"]:
            lines.append("(строк нет)")
        lines.extend(_page_line_text(line) for line in page["lines"])
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
    "Пустые", "Порядок", "Таблицы", "Состояние",
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
            for col, (cell, width) in enumerate(zip(row, widths))
        ]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines)


def render_read_report_csv(report: dict) -> str:
    """CSV text (`;` separated, CRLF); the writer adds the BOM through `utf-8-sig`."""
    buffer = io.StringIO()
    csv.writer(buffer, delimiter=";").writerows(_report_rows(report))
    return buffer.getvalue()
