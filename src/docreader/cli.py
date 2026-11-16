"""Command line interface `docreader` (see specs/001-document-intake/contracts/cli.md)."""

import argparse
import sys
from collections.abc import Callable

import psycopg

from docreader import db
from docreader.config import Settings, load_settings
from docreader.errors import DocreaderError, UserError
from docreader.intake import run_intake
from docreader.render import render_intake_json, render_intake_text


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

    return parser


def _not_implemented(name: str) -> UserError:
    return UserError(f"Команда «{name}» ещё не реализована")


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
    raise _not_implemented("list")


def _cmd_show(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    raise _not_implemented("show")


def _cmd_remove(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    raise _not_implemented("remove")


def _cmd_verify(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    raise _not_implemented("verify")


def _cmd_reclassify(
    args: argparse.Namespace, settings: Settings, conn: psycopg.Connection
) -> int:
    raise _not_implemented("reclassify")


def _cmd_page_kinds_check(
    args: argparse.Namespace, settings: Settings, conn: psycopg.Connection
) -> int:
    raise _not_implemented("page-kinds-check")


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
