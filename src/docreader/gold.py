"""The gold set of field values (feature 02): states, paths, loads (research R-5, R-6).

The enums equal the CHECK constraints of `0007_evaluation.sql`
(tests/integration/test_migration_0007.py checks it).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from docreader import catalog, values
from docreader.catalog import CatalogField, CatalogKind
from docreader.errors import UserError


class GoldState(StrEnum):
    """A marked pair: a value is given, or the field is absent from the contract."""

    VALUE = "value"
    ABSENT = "absent"


class GoldPath(StrEnum):
    """How a gold value was obtained (data-model.md)."""

    AGREE = "agree"  # review card «совпало», answer «верно»
    CONFIRMED = "confirmed"  # review card with one source, answer «верно»
    CHOSEN = "chosen"  # one of two differing values chosen
    TYPED = "typed"  # typed on the review page
    ABSENT_MARKED = "absent_marked"  # «отсутствует» on the review page
    TEMPLATE = "template"  # from a template file


REVIEW_PATHS: frozenset[GoldPath] = frozenset(GoldPath) - {GoldPath.TEMPLATE}
SYSTEM_CONFIRMED_PATHS: frozenset[GoldPath] = frozenset(
    {GoldPath.AGREE, GoldPath.CONFIRMED, GoldPath.CHOSEN}
)


class LoadKind(StrEnum):
    """What a `gold_load` row loaded."""

    REVIEW = "review"
    TEMPLATE = "template"
    BLIND = "blind"
    QUESTIONS = "questions"


REVIEW_FORMAT = "docreader-gold-review/1"
_ABSENT_WORD = "отсутствует"
_VARIANT_SEPARATOR = " || "


class GoldFileError(UserError):
    """The whole gold file is rejected (wrong encoding, format or columns)."""


@dataclass(frozen=True)
class CellValue:
    """A labeled cell of a gold file, ready to be stored."""

    state: GoldState
    values_text: tuple[str, ...]
    values_normalized: tuple[str, ...]
    path: GoldPath
    clause_key: str | None = None
    system_normalized: str | None = None


@dataclass(frozen=True)
class FileProblem:
    """A problem of one cell, row or card; `reason` never contains the cell value."""

    where: str
    reason: str


@dataclass(frozen=True)
class ParsedGold:
    """What a gold file says: covered pairs, labeled cells, problems."""

    kind: LoadKind
    coverage: frozenset[tuple[str, str]]
    values: dict[tuple[str, str], CellValue]
    errors: list[FileProblem]
    skipped_rows: list[FileProblem]


# --- template (CSV) ---


def parse_template(
    data: bytes, registry: set[str], *, kind: LoadKind = LoadKind.TEMPLATE
) -> ParsedGold:
    """Parse a template CSV (research R-2): `;` or `,`, UTF-8 with or without BOM."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise GoldFileError("файл не в кодировке UTF-8: сохраните его как CSV UTF-8") from None
    first_line = text.split("\n", 1)[0]
    delimiter = ";" if ";" in first_line else ","
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise GoldFileError("файл пустой: нет строки заголовка") from None
    header = [h.strip() for h in header]
    if "document_id" not in header:
        raise GoldFileError("в заголовке нет столбца document_id")
    fields: dict[int, CatalogField] = {}
    for index, name in enumerate(header):
        if name == "document_id":
            continue
        try:
            fields[index] = catalog.field(name)
        except KeyError:
            raise GoldFileError(f"неизвестный столбец в заголовке: {name}") from None
    doc_index = header.index("document_id")

    coverage: set[tuple[str, str]] = set()
    cells: dict[tuple[str, str], CellValue] = {}
    errors: list[FileProblem] = []
    skipped: list[FileProblem] = []
    seen: set[str] = set()
    last_line = reader.line_num
    for row in reader:
        line = last_line + 1  # the line where this row starts
        last_line = reader.line_num
        if not row or not any(c.strip() for c in row) or row[0].lstrip().startswith("#"):
            continue
        doc = row[doc_index].strip() if doc_index < len(row) else ""
        if doc not in registry:
            skipped.append(FileProblem(f"строка {line}", f"документ {doc} не найден в реестре"))
            continue
        if doc in seen:
            skipped.append(FileProblem(f"строка {line}", f"документ {doc} уже был выше в файле"))
            continue
        seen.add(doc)
        for index, field in fields.items():
            coverage.add((doc, field.name))
            raw = row[index].strip() if index < len(row) else ""
            if not raw:
                continue
            if raw.casefold() == _ABSENT_WORD:
                cells[(doc, field.name)] = CellValue(GoldState.ABSENT, (), (), GoldPath.TEMPLATE)
                continue
            texts = tuple(part.strip() for part in raw.split(_VARIANT_SEPARATOR))
            try:
                normalized = tuple(values.normalize_field(field, t) for t in texts)
            except ValueError as exc:
                errors.append(FileProblem(f"строка {line}, столбец {field.name}", str(exc)))
                continue
            cells[(doc, field.name)] = CellValue(
                GoldState.VALUE, texts, normalized, GoldPath.TEMPLATE
            )
    return ParsedGold(kind, frozenset(coverage), cells, errors, skipped)


_KIND_WORDS: dict[CatalogKind, str] = {
    CatalogKind.IDENTIFIER: "идентификатор",
    CatalogKind.DATE: "дата",
    CatalogKind.AMOUNT: "сумма",
    CatalogKind.PERCENT: "процент",
    CatalogKind.NUMBER: "число",
    CatalogKind.NAME: "наименование",
    CatalogKind.FREE_TEXT: "свободный текст",
    CatalogKind.LIST: "список",
    CatalogKind.RECORDS: "список записей",
}

_HINTS: dict[CatalogKind, str] = {
    CatalogKind.IDENTIFIER: "как в договоре",
    CatalogKind.DATE: "ДД.ММ.ГГГГ или «25 марта 2026»",
    CatalogKind.AMOUNT: "с копейками, например 1 000 000,60",
    CatalogKind.PERCENT: "например 20 или 0,1",
    CatalogKind.NUMBER: "целое число",
    CatalogKind.NAME: "как в договоре",
    CatalogKind.REQUISITE: "цифры как в договоре, пробелы и дефисы не важны",
    CatalogKind.CHOICE: "одно из перечисленных",
    CatalogKind.FREE_TEXT: "текст как в договоре",
    CatalogKind.LIST: "значения через ' || '",
    CatalogKind.RECORDS: "записи как в договоре",
}


# blind marking, record 32 (SC-006): «как в договоре» did not say a short name keeps its form
_SHORT_NAME_HINT = "краткое, с формой: АО «Альфа»"


def _hint(field: CatalogField) -> str:
    if field.kind is CatalogKind.NAME and field.name.endswith("_name_short"):
        return _SHORT_NAME_HINT
    return _HINTS[field.kind]


def _kind_word(field: CatalogField) -> str:
    if field.kind is CatalogKind.REQUISITE:
        return f"реквизит, цифр: {field.requisite_length}" if field.requisite_length else "реквизит"
    if field.kind is CatalogKind.CHOICE:
        return "выбор: " + ", ".join(field.choices)
    return _KIND_WORDS[field.kind]


def write_template(fields: Sequence[CatalogField], document_ids: Sequence[str]) -> bytes:
    """An empty template: header, kind row, hint row, one empty row per document."""
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(["document_id", *(f.name for f in fields)])
    writer.writerow(["#вид", *(_kind_word(f) for f in fields)])
    note = (
        f"пусто = не размечено; «{_ABSENT_WORD}» = в договоре нет; "
        f"варианты через «{_VARIANT_SEPARATOR}»"
    )
    writer.writerow(
        ["#подсказка", *(f"{_hint(f)}; {note}" if i == 0 else _hint(f)
                         for i, f in enumerate(fields))]
    )
    for doc in document_ids:
        writer.writerow([doc, *([""] * len(fields))])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")


# --- review answers (JSON) ---


def _source_of(card: dict[str, Any], choice: str) -> dict[str, str] | None:
    model = card.get("model")
    rules: list[dict[str, str]] = card.get("rules") or []
    if choice == "model":
        return model if model else None
    if choice == "rules":
        return rules[0] if rules else None
    if choice.startswith("rules:") and choice[6:].isdigit():
        n = int(choice[6:])
        return rules[n - 1] if 1 <= n <= len(rules) else None
    return None


def _from_source(src: dict[str, str], path: GoldPath, system: str | None) -> CellValue:
    return CellValue(
        GoldState.VALUE, (src["value"],), (src["normalized"],), path, src.get("clause"), system
    )


def parse_review_answers(data: bytes, cards: list[dict[str, Any]]) -> ParsedGold:
    """Parse the review page answers against the build's cards (contracts/files.md)."""
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise GoldFileError("файл ответов не читается: это не JSON в кодировке UTF-8") from None
    if not isinstance(doc, dict) or doc.get("format") != REVIEW_FORMAT:
        raise GoldFileError(f"неизвестный формат файла ответов, ожидается {REVIEW_FORMAT}")
    answers = doc.get("cards")
    if not isinstance(answers, list):
        raise GoldFileError("в файле ответов нет списка cards")
    by_key = {c["key"]: c for c in cards}
    coverage = frozenset((c["document_id"], c["field"]) for c in cards)
    cells: dict[tuple[str, str], CellValue] = {}
    errors: list[FileProblem] = []
    seen: set[str] = set()

    for item in answers:
        key = item.get("key") if isinstance(item, dict) else None
        where = f"карточка {key}"
        card = by_key.get(key) if isinstance(key, str) else None
        if card is None:
            errors.append(FileProblem(where, "такой карточки нет в сборке"))
            continue
        if str(key) in seen:
            errors.append(FileProblem(where, "на карточку дано больше одного ответа"))
            continue
        seen.add(str(key))
        pair = (card["document_id"], card["field"])
        model = card.get("model")
        system = model["normalized"] if model else None
        kind = item.get("answer")
        if kind == "agree":
            rules = card.get("rules") or []
            src = model or (rules[0] if rules else None)
            if src is None:
                errors.append(FileProblem(where, "«верно» на карточке без значений"))
                continue
            # «совпало» is decided by the values, not by the mark: a card marked «изменилось»
            # whose model and rules agree is still agreed (converge G8, FR-005)
            field = catalog.field(card["field"])
            agreed = model is not None and bool(rules) and all(
                values.same_value(field, model["normalized"], r["normalized"]) for r in rules
            )
            path = GoldPath.AGREE if agreed else GoldPath.CONFIRMED
            cells[pair] = _from_source(src, path, system)
        elif kind == "chosen":
            choice = item.get("choice")
            src = _source_of(card, choice) if isinstance(choice, str) else None
            if src is None:
                errors.append(FileProblem(where, "выбранного значения нет на карточке"))
                continue
            cells[pair] = _from_source(src, GoldPath.CHOSEN, system)
        elif kind == "typed":
            text = item.get("value")
            field = catalog.field(card["field"])
            try:
                if not isinstance(text, str) or not text.strip():
                    raise ValueError("значение не введено")
                normalized = values.normalize_field(field, text)
            except ValueError as exc:
                errors.append(FileProblem(where, str(exc)))
                continue
            clause = item.get("clause")
            clause_key = clause.rsplit("/", 1)[-1] if isinstance(clause, str) and clause else None
            cells[pair] = CellValue(
                GoldState.VALUE, (text.strip(),), (normalized,), GoldPath.TYPED, clause_key, system
            )
        elif kind == "absent":
            # the system value is kept, or a rebuilt page would mark the card «изменилось»
            # (converge G1, FR-004)
            cells[pair] = CellValue(
                GoldState.ABSENT, (), (), GoldPath.ABSENT_MARKED, None, system
            )
        elif kind == "skip":
            continue
        else:
            errors.append(FileProblem(where, "неизвестный вид ответа"))
    return ParsedGold(LoadKind.REVIEW, coverage, cells, errors, [])


# --- the replacement rule ---
# The replacement rule (research R-6) is pure; `load` applies it in one transaction.

Pair = tuple[str, str]


@dataclass(frozen=True)
class StoredGold:
    """A gold row as it is in the database, with the kind of file it came from."""

    cell: CellValue
    kind: LoadKind


@dataclass(frozen=True)
class GoldDiff:
    """The difference inside the coverage of a file (research R-6), pairs sorted."""

    added: list[Pair]
    changed: list[Pair]
    removed: list[Pair]
    same: list[Pair]
    other_kind: list[Pair]  # given by the file, last loaded from the other file kind

    @property
    def needs_confirmation(self) -> bool:
        return bool(self.removed)


def _content(cell: CellValue) -> tuple[GoldState, tuple[str, ...]]:
    return cell.state, cell.values_normalized


def diff(current: dict[Pair, StoredGold], parsed: ParsedGold) -> GoldDiff:
    """What loading `parsed` changes; pairs outside its coverage are never touched."""
    added: list[Pair] = []
    changed: list[Pair] = []
    removed: list[Pair] = []
    same: list[Pair] = []
    other: list[Pair] = []
    for pair in sorted(parsed.coverage):
        old = current.get(pair)
        new = parsed.values.get(pair)
        if new is None:
            if old is not None:
                removed.append(pair)
            continue
        if old is None:
            added.append(pair)
            continue
        (same if _content(old.cell) == _content(new) else changed).append(pair)
        if old.kind is not parsed.kind:
            other.append(pair)
    return GoldDiff(added, changed, removed, same, other)


def gold_sha256(rows: Iterable[tuple[str, str, str, Sequence[str]]]) -> str:
    """Version of the gold content: (document, field, state, normalized variants), any order."""
    lines = sorted(
        "\t".join((doc, field, state, "\x1f".join(norm))) for doc, field, state, norm in rows
    )
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# --- database ---

_TABLE = {LoadKind.REVIEW: "gold_field", LoadKind.TEMPLATE: "gold_field",
          LoadKind.BLIND: "gold_blind"}


@dataclass(frozen=True)
class LoadReport:
    kind: LoadKind
    diff: GoldDiff
    needs_confirmation: bool
    load_id: int | None  # None when nothing was written
    gold_sha256: str  # the version after the load (or the current one when nothing was written)
    paths: dict[str, int]  # given values by path, of this file
    absent: int
    unlabeled: int  # pairs of the coverage left unmarked
    errors: int


def _stored(conn: psycopg.Connection, table: str) -> dict[Pair, StoredGold]:
    has_path = table == "gold_field"
    columns = "f.path, l.kind" if has_path else "'template', l.kind"
    rows = conn.execute(
        f"SELECT f.document_id, f.field, f.state, f.values_text, f.values_normalized, {columns} "
        f"FROM {table} f JOIN gold_load l ON l.id = f.load_id"
    ).fetchall()
    return {
        (doc, field): StoredGold(
            CellValue(GoldState(state), tuple(text), tuple(norm), GoldPath(path)), LoadKind(kind)
        )
        for doc, field, state, text, norm, path, kind in rows
    }


def _sha_of(conn: psycopg.Connection, table: str) -> str:
    rows = conn.execute(
        f"SELECT document_id, field, state, values_normalized FROM {table}"
    ).fetchall()
    return gold_sha256((d, f, s, tuple(n)) for d, f, s, n in rows)


def current_sha256(conn: psycopg.Connection) -> str:
    """The version of the gold set of fields as it is now."""
    return _sha_of(conn, "gold_field")


def load(
    conn: psycopg.Connection,
    parsed: ParsedGold,
    *,
    file_name: str,
    file_bytes: bytes,
    yes: bool,
) -> LoadReport:
    """Replace the gold inside the coverage of `parsed` (research R-6).

    A removal of any value without `yes` writes nothing. The rows and the `gold_load`
    row are written in one transaction (autocommit connection, tech-context «Транзакции»).
    """
    table = _TABLE[parsed.kind]
    d = diff(_stored(conn, table), parsed)
    paths: dict[str, int] = {}
    for cell in parsed.values.values():
        paths[cell.path.value] = paths.get(cell.path.value, 0) + 1
    absent = sum(1 for c in parsed.values.values() if c.state is GoldState.ABSENT)
    unlabeled = len(parsed.coverage) - len(parsed.values)

    def report(load_id: int | None, version: str) -> LoadReport:
        return LoadReport(
            parsed.kind, d, load_id is None and d.needs_confirmation, load_id, version, paths,
            absent, unlabeled, len(parsed.errors),
        )

    if d.needs_confirmation and not yes:
        return report(None, current_sha256(conn))
    counts = {
        "added": len(d.added), "changed": len(d.changed), "removed": len(d.removed),
        "same": len(d.same), "other_kind": len(d.other_kind), "paths": paths,
        "absent": absent, "unlabeled": unlabeled, "errors": len(parsed.errors),
        "skipped_rows": len(parsed.skipped_rows),
    }
    docs = [doc for doc, _ in sorted(parsed.coverage)]
    fields = [f for _, f in sorted(parsed.coverage)]
    with conn.transaction():
        conn.execute(
            f"DELETE FROM {table} WHERE (document_id, field) IN "
            "(SELECT * FROM unnest(%s::text[], %s::text[]))",
            (docs, fields),
        )
        load_id = conn.execute(
            "INSERT INTO gold_load (kind, file_name, file_sha256, gold_sha256, counts) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (parsed.kind.value, file_name, hashlib.sha256(file_bytes).hexdigest(), "0" * 64,
             Jsonb(counts)),
        ).fetchone()[0]  # type: ignore[index]
        for (doc, field), cell in sorted(parsed.values.items()):
            if table == "gold_field":
                conn.execute(
                    "INSERT INTO gold_field (document_id, field, state, values_text, "
                    "values_normalized, path, system_normalized, clause_key, load_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (doc, field, cell.state.value, list(cell.values_text),
                     list(cell.values_normalized), cell.path.value, cell.system_normalized,
                     cell.clause_key, load_id),
                )
            else:
                conn.execute(
                    "INSERT INTO gold_blind (document_id, field, state, values_text, "
                    "values_normalized, load_id) VALUES (%s, %s, %s, %s, %s, %s)",
                    (doc, field, cell.state.value, list(cell.values_text),
                     list(cell.values_normalized), load_id),
                )
        version = _sha_of(conn, "gold_field")
        conn.execute("UPDATE gold_load SET gold_sha256 = %s WHERE id = %s", (version, load_id))
    return report(load_id, version)


# --- review build lookup (contracts/cli.md «eval load») ---

CARDS_FORMAT = "docreader-gold-cards/1"


def find_build_cards(data_dir: Path, build: str) -> list[dict[str, Any]]:
    """The cards of review build `build`, from `eval/review-*/cards.json` of the data folder."""
    for path in sorted((data_dir / "eval").glob("review-*/cards.json")):
        try:
            doc = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise GoldFileError(f"файл карточек {path.name} не читается") from None
        if not isinstance(doc, dict) or doc.get("format") != CARDS_FORMAT:
            raise GoldFileError(f"неизвестный формат файла карточек {path.name}")
        if doc.get("build") != build:
            continue
        cards = doc.get("cards")
        if not isinstance(cards, list):
            raise GoldFileError(f"в файле карточек {path.name} нет списка cards")
        return cards
    raise GoldFileError(
        f"сборка страницы проверки {build} не найдена в eval/ папки данных"
    )
