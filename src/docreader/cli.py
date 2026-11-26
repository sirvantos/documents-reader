"""Command line interface `docreader` (see specs/001-document-intake/contracts/cli.md)."""

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import psycopg

from docreader import (
    answer,
    clauseview,
    db,
    extraction,
    fieldview,
    gold,
    indexing,
    parsing,
    passageview,
    reading,
    recognition,
    recognition_eval,
    registry,
    search,
    textview,
)
from docreader.answer_check import AnswerOutcome
from docreader.config import Settings, load_settings
from docreader.errors import DocreaderError, UserError
from docreader.gold import GoldFileError
from docreader.ids import format_document_id, parse_clause_id, parse_document_id
from docreader.intake import run_intake
from docreader.render import (
    NO_READ_DOCUMENTS,
    NO_REVIEW_PAGES,
    NO_SCAN_DOCUMENTS,
    NOTHING_TO_EXTRACT,
    NOTHING_TO_INDEX,
    render_answer_json,
    render_answer_text,
    render_clause_text,
    render_document_text,
    render_eval_load_json,
    render_eval_load_text,
    render_extract_text,
    render_fields_text,
    render_find_text,
    render_index_text,
    render_intake_json,
    render_intake_text,
    render_list_text,
    render_outline_text,
    render_page_kinds_text,
    render_page_text,
    render_parse_text,
    render_passage_text,
    render_read_report_csv,
    render_read_report_text,
    render_read_text,
    render_reclassify_text,
    render_recognition_csv,
    render_recognition_table,
    render_recognize_eval_text,
    render_recognize_progress,
    render_recognize_text,
    render_review_csv,
    render_review_text,
    render_search_text,
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

    p = sub.add_parser("parse", help="разобрать структуру документов")
    p.add_argument(
        "ids", nargs="*", metavar="ID", help="идентификаторы (по умолчанию — неразобранные)"
    )
    p.add_argument("--all", action="store_true", help="разобрать все прочитанные документы")
    p.add_argument("--label", metavar="МЕТКА", help="метка запуска")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("extract", help="извлечь поля договоров")
    p.add_argument(
        "ids",
        nargs="*",
        metavar="ID",
        help="идентификаторы (по умолчанию — договоры с незаполненными полями)",
    )
    p.add_argument("--all", action="store_true", help="извлечь из всех доступных договоров")
    p.add_argument("--label", metavar="МЕТКА", help="метка запуска")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("index", help="нарезать договоры на отрывки и построить индексы")
    p.add_argument(
        "ids",
        nargs="*",
        metavar="ID",
        help="идентификаторы (по умолчанию — договоры без актуальных индексов)",
    )
    p.add_argument("--all", action="store_true", help="перестроить индексы всех договоров")
    p.add_argument("--label", metavar="МЕТКА", help="метка запуска")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("passage", help="показать один отрывок")
    p.add_argument("id", metavar="ID", help="идентификатор пункта, например D-0001/5.2")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("search", help="найти отрывки по словам и по смыслу")
    p.add_argument("query", metavar="ЗАПРОС", help="слова для поиска")
    p.add_argument("--no-rerank", action="store_true", help="без реранкера на этот запуск")
    p.add_argument("--results", type=int, metavar="N", help="сколько отрывков показать")
    p.add_argument("--document", metavar="ID", help="искать только в этом договоре (D-0015)")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("ask", help="ответить на вопрос по текстам договоров с проверкой цитат")
    p.add_argument("question", metavar="ВОПРОС", help="вопрос о договорах")
    p.add_argument("--document", metavar="ID", help="ответить по одному договору (D-0015)")
    p.add_argument("--passages", type=int, metavar="N", help="сколько отрывков дать модели")
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

    p = sub.add_parser("outline", help="показать оглавление разобранного документа")
    p.add_argument("id", metavar="ID", help="идентификатор документа, например D-0001")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("fields", help="показать поля договора")
    p.add_argument("id", metavar="ID", help="идентификатор документа, например D-0001")
    p.add_argument("--json", action="store_true", help="вывод в формате JSON")

    p = sub.add_parser("clause", help="показать пункт с подпунктами")
    p.add_argument(
        "id", metavar="ИДЕНТИФИКАТОР", help="идентификатор пункта, например D-0001/5.2"
    )
    p.add_argument("--own", action="store_true", help="только собственный текст пункта")
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

    p = sub.add_parser("recognize-report", help="отчёт о распознавании сканов")
    p.add_argument(
        "--review", action="store_true", help="список страниц на просмотр вместо отчёта"
    )
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

    p = sub.add_parser("eval", help="эталон полей: загрузка ответов и шаблонов")
    eval_sub = p.add_subparsers(dest="eval_command", parser_class=_Parser, metavar="КОМАНДА")
    p = eval_sub.add_parser("load", help="загрузить эталон из шаблона (.csv) или ответов (.json)")
    p.add_argument(
        "file",
        metavar="ФАЙЛ",
        help="файл .csv (шаблон) или .json (ответы страницы проверки)",
    )
    p.add_argument(
        "--yes", action="store_true", help="заменить значения, которые файл убирает из эталона"
    )
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


NOTHING_TO_PARSE = (
    "Нечего разбирать: все документы разобраны (заново: docreader parse --all)"
)


def _cmd_parse(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    if args.all and args.ids:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    seqs = [parse_document_id(i) for i in args.ids] or None
    result = parsing.parse_documents(
        conn, settings, seqs, all_documents=args.all, label=args.label
    )
    if result.run_id is None and not result.documents and not result.skipped:
        print(NOTHING_TO_PARSE)
        return 0
    if args.json:
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_parse_text(result))
    if result.interrupted:
        print("Прервано", file=sys.stderr)
        return 130
    return 0


def _cmd_extract(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    if args.all and args.ids:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    seqs = [parse_document_id(i) for i in args.ids] or None
    result = extraction.extract_documents(
        conn, settings, seqs, all_documents=args.all, label=args.label
    )
    if result.run_id is None and not result.documents and not result.skipped:
        print(NOTHING_TO_EXTRACT)
        return 0
    if args.json:
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_extract_text(result))
    if result.interrupted:
        print("Прервано", file=sys.stderr)
        return 130
    if result.stopped is not None:
        return 2
    return 0


def _cmd_index(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    if args.all and args.ids:
        raise UserError("Нельзя указать --all вместе с идентификаторами")
    seqs = [parse_document_id(i) for i in args.ids] or None
    result = indexing.index_documents(
        conn, settings, seqs, all_documents=args.all, label=args.label
    )
    if result.run_id is None and not result.documents and not result.skipped:
        print(NOTHING_TO_INDEX)
        return 0
    if args.json:
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_index_text(result))
    if result.interrupted:
        print("Прервано", file=sys.stderr)
        return 130
    if result.stopped is not None:
        return 2
    return 0


NOTHING_TO_RECOGNIZE = (
    "Нечего распознавать: все страницы-сканы распознаны "
    "(заново: docreader recognize --all --force)"
)


def _print_recognize_progress(
    doc_id: str, page: int, done: int, total: int, seconds: float
) -> None:
    print(
        render_recognize_progress(doc_id, page, done, total, seconds),
        file=sys.stderr,
        flush=True,
    )


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


def _cmd_outline(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seq = parse_document_id(args.id)
    outline = clauseview.load_outline(conn, seq)
    if args.json:
        print(json.dumps(outline.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_outline_text(outline))
    return 0


def _cmd_fields(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seq = parse_document_id(args.id)
    view = fieldview.load_fields(conn, seq)
    if args.json:
        print(json.dumps(view.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_fields_text(view))
    return 0


def _cmd_clause(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    seq, key = parse_clause_id(args.id)
    view = clauseview.load_clause(conn, seq, key, own=args.own)
    if args.json:
        print(json.dumps(view.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_clause_text(view))
    return 0


def _cmd_passage(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    view = passageview.load_passage(conn, args.id)
    if args.json:
        print(json.dumps(view.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_passage_text(view))
    return 0


def _cmd_ask(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    limit = settings.search.rerank_candidates
    if args.passages is not None and not 1 <= args.passages <= limit:
        raise UserError(f"--passages: целое от 1 до {limit}")
    result = answer.ask(
        conn,
        settings,
        args.question,
        document_id=args.document,
        passages=args.passages,
    )
    if args.json:
        print(render_answer_json(result))
    else:
        print(render_answer_text(result), end="")
    return 1 if result.outcome == AnswerOutcome.FAILED else 0


def _cmd_search(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    result = search.search(
        conn,
        settings,
        args.query,
        rerank=False if args.no_rerank else None,
        results=args.results,
        document_id=args.document,
    )
    if args.json:
        print(json.dumps(result.to_json(), ensure_ascii=False, indent=2))
    else:
        print(render_search_text(result), end="")
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


def _write_report_csv(text: str, arg: str | None, settings: Settings, prefix: str) -> Path:
    """Write a CSV report with a BOM; without a path, into the reports folder."""
    if arg:
        target = Path(arg)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = settings.reports_dir / f"{prefix}-{stamp}.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(text)
    return target


def _cmd_recognize_report(
    args: argparse.Namespace, settings: Settings, conn: psycopg.Connection
) -> int:
    if args.review:
        pages = [asdict(page) for page in textview.recognition_review(conn, settings)]
        if args.csv is not None:
            target = _write_report_csv(
                render_review_csv(pages), args.csv, settings, "recognition-review"
            )
            print(f"Отчёт сохранён: {target}")
        elif args.json:
            print(json.dumps({"pages": pages}, ensure_ascii=False, indent=2))
        elif not pages:
            print(NO_REVIEW_PAGES)
        else:
            print(render_review_text(pages))
        return 0

    report = textview.recognition_report(conn, settings).to_json()
    if args.csv is not None:
        target = _write_report_csv(
            render_recognition_csv(report), args.csv, settings, "recognition"
        )
        print(f"Отчёт сохранён: {target}")
    elif args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif not report["documents"]:
        print(NO_SCAN_DOCUMENTS)
    else:
        print(render_recognition_table(report))
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


def _review_build(data: bytes) -> str:
    """The build id of a review answers file (its cards are found by this id)."""
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GoldFileError("файл ответов не читается: это не JSON в кодировке UTF-8") from None
    build = doc.get("build") if isinstance(doc, dict) else None
    if not isinstance(build, str) or not build:
        raise GoldFileError("в файле ответов нет поля build: сохраните ответы со страницы проверки")
    return build


def _file_label(path: Path, data_dir: Path) -> str:
    """The file name stored with the load: relative to the data folder when it is inside it."""
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _cmd_eval(args: argparse.Namespace, settings: Settings, conn: psycopg.Connection) -> int:
    if args.eval_command != "load":  # no subcommand given
        raise UserError("укажите команду группы eval, например: docreader eval load ФАЙЛ")
    path = Path(args.file)
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".json"}:
        raise UserError("ожидается файл .csv (шаблон) или .json (ответы страницы проверки)")
    try:
        data = path.read_bytes()
    except OSError:
        raise UserError(f"файл не читается: {path}") from None
    if suffix == ".csv":
        registry = {row[0] for row in conn.execute("SELECT id FROM document").fetchall()}
        parsed = gold.parse_template(data, registry)
    else:
        cards = gold.find_build_cards(settings.data_dir, _review_build(data))
        parsed = gold.parse_review_answers(data, cards)
    report = gold.load(
        conn,
        parsed,
        file_name=_file_label(path, settings.data_dir),
        file_bytes=data,
        yes=args.yes,
    )
    if args.json:
        print(render_eval_load_json(parsed, report))
    else:
        print(render_eval_load_text(parsed, report))
    return 1 if report.needs_confirmation else 0


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
    "parse": _cmd_parse,
    "extract": _cmd_extract,
    "index": _cmd_index,
    "recognize": _cmd_recognize,
    "text": _cmd_text,
    "outline": _cmd_outline,
    "fields": _cmd_fields,
    "clause": _cmd_clause,
    "passage": _cmd_passage,
    "search": _cmd_search,
    "ask": _cmd_ask,
    "read-report": _cmd_read_report,
    "recognize-report": _cmd_recognize_report,
    "recognize-eval": _cmd_recognize_eval,
    "eval": _cmd_eval,
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
