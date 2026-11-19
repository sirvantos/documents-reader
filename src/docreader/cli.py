"""Command line interface `docreader` (see specs/001-document-intake/contracts/cli.md)."""

import argparse
import json
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import psycopg

from docreader import db, reading, recognition, recognition_eval, registry, textview
from docreader.config import Settings, load_settings
from docreader.errors import DocreaderError, UserError
from docreader.ids import format_document_id, parse_document_id
from docreader.intake import run_intake
from docreader.render import (
    NO_READ_DOCUMENTS,
    render_document_text,
    render_find_text,
    render_intake_json,
    render_intake_text,
    render_list_text,
    render_page_kinds_text,
    render_page_text,
    render_read_report_csv,
    render_read_report_text,
    render_read_text,
    render_reclassify_text,
    render_recognize_eval_text,
    render_recognize_progress,
    render_recognize_text,
    render_show_text,
    render_verify_text,
)


class _Parser(argparse.ArgumentParser):
    """Argument errors are user errors: exit code 1 (code 2 is reserved for environment)."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: ошибка: {message}", file=sys.stderr)
        raise SystemExit(1)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="docreader",
        description="Приём и учёт документов-договоров: добавление, реестр, проверка копий.",
    )
    sub = parser.add_subparsers(dest="command", parser_class=_Parser, metavar="КОМАНДА")

    sub.add_parser("migrate", help="применить неприменённые миграции базы данных")

    p = sub.add_parser("add", help="добавить файлы или папки в реестр")
    p.add_argument("paths", nargs="+", metavar="путь", help="файл или папка (рекурсивно)")
    p.add_argument("--note", metavar="ТЕКСТ", help="заметка для каждого добавленного документа")
    p.add_argument("--label", metavar="МЕТКА", help="метка запуска")
    p.add_argument("--json", action="store_true", help="вывести отчёт в формате JSON")

    p = sub.add_parser("list", help="показать все документы")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("show", help="показать сведения о документе")
    p.add_argument("id", metavar="ID", help="идентификатор документа, например D-0001")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("remove", help="удалить документ")
    p.add_argument("id", metavar="ID", help="идентификатор документа")
    p.add_argument("--yes", action="store_true", help="не спрашивать подтверждения")

    p = sub.add_parser("verify", help="проверить целостность копий (SHA-256)")
    p.add_argument("ids", nargs="*", metavar="ID", help="идентификаторы (по умолчанию все)")

    p = sub.add_parser("reclassify", help="пересчитать вид страниц по текущим порогам")
    p.add_argument("ids", nargs="*", metavar="ID", help="идентификаторы (по умолчанию все)")
    p.add_argument("--label", metavar="МЕТКА", help="метка запуска")

    p = sub.add_parser("page-kinds-check", help="сверить виды страниц с ручной разметкой")
    p.add_argument("labels", metavar="labels.csv", help="CSV-файл с разметкой")

    p = sub.add_parser("read", help="прочитать текст документов")
    p.add_argument(
        "ids", nargs="*", metavar="ID", help="идентификаторы (по умолчанию — непрочитанные)"
    )
    p.add_argument("--all", action="store_true", help="перечитать все документы реестра")
    p.add_argument("--label", metavar="МЕТКА", help="метка запуска")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("recognize", help="распознать страницы-сканы")
    p.add_argument(
        "ids",
        nargs="*",
        metavar="ID",
        help="идентификаторы (по умолчанию — документы, где нужно распознавание)",
    )
    p.add_argument("--all", action="store_true", help="распознать все документы реестра")
    p.add_argument(
        "--force", action="store_true", help="распознать заново и страницы с готовым результатом"
    )
    p.add_argument("--pages", metavar="N[-M]", help="страница или диапазон страниц документа")
    p.add_argument("--label", metavar="МЕТКА", help="метка запуска")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("text", help="показать прочитанный текст документа")
    p.add_argument("id", metavar="ID", help="идентификатор документа, например D-0001")
    p.add_argument("--page", type=int, metavar="N", help="строки одной страницы")
    p.add_argument("--find", metavar="ФРАЗА", help="найти фразу в тексте")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("read-report", help="отчёт о чтении документов")
    p.add_argument(
        "--csv",
        nargs="?",
        const="",
        default=None,
        metavar="ПУТЬ",
        help="сохранить отчёт в CSV (без пути — в папку reports каталога данных)",
    )
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("recognize-eval", help="замер качества распознавания")
    p.add_argument("folder", metavar="ПАПКА", help="папка проверенных текстов в папке данных")
    p.add_argument("--label", metavar="МЕТКА", help="метка замера")
    p.add_argument("--diff", action="store_true", help="напечатать список расхождений с текстом")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    return parser


def _cmd_migrate(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    versions = db.apply_migrations(conn)
    if not versions:
        print("Схема актуальна")
    for version in versions:
        print(f"Применена миграция {version}")
    return 0


def _cmd_add(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    outcome = run_intake(conn, settings, args.paths, note=args.note, label=args.label)
    if args.json:
        text = render_intake_json(outcome.report)
    else:
        text = render_intake_text(outcome.report, str(outcome.report_path))
    print(text, end="" if text.endswith("\n") else "\n")
    if outcome.interrupted:
        print("Прервано", file=sys.stderr)
        return 130
    return 0


def _cmd_list(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    docs = registry.list_documents(conn)
    if args.json:
        print(json.dumps(docs, ensure_ascii=False, indent=2))
    else:
        print(render_list_text(docs))
    return 0


def _cmd_show(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seq = parse_document_id(args.id)
    doc = registry.show_document(conn, settings, seq)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(render_show_text(doc))
    return 0


def _cmd_remove(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seq = parse_document_id(args.id)
    row = registry.find_document(conn, seq)
    if row is None:
        raise UserError(
            f"Документ {format_document_id(seq)} не найден — список документов: docreader list"
        )
    print("Будет удалено:")
    print(f"  {row['id']}  {row['original_name']}  {row['page_count']} стр.")
    print(f"  копия: {settings.data_dir / row['copy_path']}")
    if not args.yes:
        if not sys.stdin.isatty():
            raise UserError("Нет подтверждения: stdin не терминал — добавьте --yes")
        print("Для подтверждения введите идентификатор документа: ", end="", flush=True)
        try:
            confirmed = parse_document_id(sys.stdin.readline()) == seq
        except UserError:
            confirmed = False
        if not confirmed:
            raise UserError("Удаление отменено")
    result = registry.remove(conn, settings, seq)
    print(f"Удалён {result['document_id']}")
    if result["warning"]:
        print(f"! {result['warning']}", file=sys.stderr)
    return 0


def _cmd_verify(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seqs = [parse_document_id(i) for i in args.ids] or None
    result = registry.verify(conn, settings, seqs)
    print(render_verify_text(result))
    return 1 if result["problems"] else 0


def _cmd_reclassify(
    args: argparse.Namespace, settings: Settings, conn: psycopg.Connection
) -> int:
    seqs = [parse_document_id(i) for i in args.ids]
    result = registry.reclassify(conn, settings, seqs or None, label=args.label)
    print(render_reclassify_text(result), end="")
    return 0


def _cmd_page_kinds_check(
    args: argparse.Namespace, settings: Settings, conn: psycopg.Connection
) -> int:
    result = registry.page_kinds_check(conn, args.labels)
    print(render_page_kinds_text(result), end="")
    if result["accuracy"] < 0.95:
        raise UserError(
            "Точность ниже 95% — подберите пороги в settings.toml и выполните "
            "docreader reclassify"
        )
    return 0


def _cmd_read(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    if args.all and args.ids:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    seqs = [parse_document_id(i) for i in args.ids] or None
    result = reading.read_documents(
        conn, settings, seqs, all_documents=args.all, label=args.label
    )
    if result["run_id"] is None and not result["documents"]:
        print("Нечего читать: все документы прочитаны (перечитать: docreader read --all)")
        return 0
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(render_read_text(result))
    if result["interrupted"]:
        print("Прервано", file=sys.stderr)
        return 130
    return 0


NOTHING_TO_RECOGNIZE = (
    "Нечего распознавать: все страницы-сканы распознаны "
    "(заново: docreader recognize --all --force)"
)


def _print_recognize_progress(doc_id: str, page: int, total: int, seconds: float) -> None:
    print(render_recognize_progress(doc_id, page, total, seconds), file=sys.stderr, flush=True)


def parse_page_range(text: str) -> list[int]:
    """Parse `--pages`: «3» → [3], «2-3» → [2, 3]; anything else is a user error."""
    parts = text.split("-")
    if len(parts) in (1, 2) and all(p.isascii() and p.isdigit() for p in parts):
        first, last = int(parts[0]), int(parts[-1])
        if 1 <= first <= last:
            return list(range(first, last + 1))
    raise UserError(f"--pages {text}: укажите номер страницы или диапазон N-M, N ≤ M")


def _cmd_recognize(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seqs = [parse_document_id(i) for i in args.ids] or None
    pages = parse_page_range(args.pages) if args.pages is not None else None
    result = recognition.recognize_documents(
        conn,
        settings,
        seqs,
        all_documents=args.all,
        label=args.label,
        force=args.force,
        pages=pages,
        progress=_print_recognize_progress,
    )
    if result.run_id is None and not result.documents:
        print(NOTHING_TO_RECOGNIZE)
        return 0
    data = result.to_json()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_recognize_text(data))
    if result.interrupted:
        print("Прервано", file=sys.stderr)
        return 130
    return 0


def _cmd_text(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seq = parse_document_id(args.id)
    if args.find is not None:
        if args.page is not None:
            raise UserError("Укажите либо --page, либо --find")
        view = textview.find_phrase(conn, seq, args.find, with_context=not args.json)
        text = "" if args.json else render_find_text(view)
    elif args.page is None:
        view = textview.load_document_text(conn, seq)
        text = render_document_text(view)
    else:
        view = textview.load_page(conn, seq, args.page)
        text = render_page_text(view)
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        print(text)
    return 0


def _cmd_read_report(
    args: argparse.Namespace, settings: Settings, conn: psycopg.Connection
) -> int:
    report = textview.reading_report(conn)
    if args.csv is not None:
        if args.csv:
            target = Path(args.csv)
        else:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            target = settings.reports_dir / f"reading-{stamp}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write(render_read_report_csv(report))
        print(f"Отчёт сохранён: {target}")
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not report["documents"]:
        print(NO_READ_DOCUMENTS)
    else:
        print(render_read_report_text(report))
    return 0


def _cmd_recognize_eval(
    args: argparse.Namespace, settings: Settings, conn: psycopg.Connection
) -> int:
    result = recognition_eval.run_eval(
        conn, settings, args.folder, label=args.label, diff=args.diff
    )
    data = result.to_json(with_diffs=args.diff)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_recognize_eval_text(data, str(result.report_path), with_diff=args.diff))
    return 0


_Handler = Callable[[argparse.Namespace, Settings, psycopg.Connection], int]

_HANDLERS: dict[str, _Handler] = {
    "migrate": _cmd_migrate,
    "add": _cmd_add,
    "list": _cmd_list,
    "show": _cmd_show,
    "remove": _cmd_remove,
    "verify": _cmd_verify,
    "reclassify": _cmd_reclassify,
    "page-kinds-check": _cmd_page_kinds_check,
    "read": _cmd_read,
    "recognize": _cmd_recognize,
    "text": _cmd_text,
    "read-report": _cmd_read_report,
    "recognize-eval": _cmd_recognize_eval,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help gives 0, argument errors give 1
        return exc.code if isinstance(exc.code, int) else 1
    if args.command is None:
        parser.print_help(sys.stderr)
        return 1

    try:
        settings = load_settings()
        conn = db.connect(settings)
        try:
            if args.command != "migrate":
                db.ensure_schema_current(conn)
            return _HANDLERS[args.command](args, settings, conn)
        finally:
            conn.close()
    except DocreaderError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Прервано", file=sys.stderr)
        return 130
