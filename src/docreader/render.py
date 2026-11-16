"""Rendering of the `docreader add` intake report (pure functions, no I/O).

The report dict has the shape described in specs/001-document-intake/contracts/cli.md.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import PurePath

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
    return [
        f"  {_name(entry).ljust(width)} → {entry['document_id']}" for entry in entries
    ]


def _rejected_lines(entries: list[dict]) -> list[str]:
    width = _name_width(entries)
    return [f"  {_name(entry).ljust(width)} {entry['reason']}" for entry in entries]
