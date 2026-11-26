"""Gold questions (feature 02): kinds and origins (research R-11).

The enums equal the CHECK constraints of `0007_evaluation.sql`.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

import psycopg
from psycopg.types.json import Jsonb

from docreader import catalog, textnorm
from docreader.errors import UserError
from docreader.ids import format_clause_id, format_document_id, parse_clause_id, parse_document_id


class QuestionKind(StrEnum):
    """Where the answer comes from."""

    TEXT = "text"
    TABLE = "table"
    BOTH = "both"


class QuestionOrigin(StrEnum):
    """Which file kind a question came from."""

    OWN = "own"
    SET08 = "set08"
    SET09 = "set09"
    GENERATED = "generated"


# One question per prototype field (feature 08 quickstart Б3; the places of the review page
# of feature 02 use the same wording). The answer is the clause of the field's quote.
TEMPLATES: dict[str, str] = {
    "contract_number": "Какой номер договора?",
    "customer_name_short": "Кто заказчик по договору?",
    "contractor_name_short": "Кто подрядчик (исполнитель) по договору?",
    "amount_without_vat": "Какая цена договора без НДС?",
    "amount_with_vat": "Какая цена договора с учётом НДС?",
    "contract_end_date": "До какого срока действует договор?",
}


# --- question key and file parsing ---------------------------------------------------------

_DOCUMENT_ID = re.compile(r"D-\d{4,}")
_QUESTION_SELECTORS = ("answer", "answers", "expected")
ANSWERS_FORMAT = "docreader-answers-b4/1"
MIN_WITHOUT_ANSWER = 10
MIN_FALSE_PREMISE = 5


def question_key(document_id: str, text: str) -> str:
    """`Q-` and 10 hex of the SHA-256 of the document and the text in comparison form."""
    folded = textnorm.compare_form(unicodedata.normalize("NFC", text).strip())[0].casefold()
    digest = hashlib.sha256(f"{document_id}\n{folded}".encode()).hexdigest()
    return f"Q-{digest[:10]}"


@dataclass(frozen=True)
class QuestionDraft:
    """One question of a file as the file states it."""

    number: int
    text: str
    document_id: str
    kind: QuestionKind
    has_answer: bool
    false_premise: bool
    expected: tuple[str, ...]
    clause_keys: tuple[str, ...]

    @property
    def key(self) -> str:
        return question_key(self.document_id, self.text)


@dataclass(frozen=True)
class ParsedQuestions:
    origin: QuestionOrigin | None
    questions: list[QuestionDraft]
    errors: list[tuple[int, str]]  # (question number, reason); never holds a question text


class _Bad(Exception):
    """A problem of one question; the message is Russian and holds no question text."""


def _document_of(value: object) -> str:
    if not isinstance(value, str):
        raise _Bad("`document` — идентификатор документа вида D-0001")
    try:
        if not _DOCUMENT_ID.fullmatch(value.strip()):
            raise UserError("not D-NNNN")
        return format_document_id(parse_document_id(value))
    except UserError:
        raise _Bad("неверный идентификатор документа в `document`") from None


def _clauses_of(entry: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    """The document and the clause keys of `answer` / `answers`."""
    raw = entry["answer"] if "answer" in entry else entry["answers"]
    items = raw if isinstance(raw, list) else [raw]
    if "answer" in entry and isinstance(raw, list):
        raise _Bad("`answer` — один пункт; несколько пунктов пишутся в `answers`")
    if not items or not all(isinstance(i, str) for i in items):
        raise _Bad("неверный пункт ответа: нужны идентификаторы вида D-0001/5.2")
    documents: list[str] = []
    keys: list[str] = []
    for item in items:
        try:
            if not _DOCUMENT_ID.fullmatch(item.partition("/")[0]):
                raise UserError("document part is not D-NNNN")
            seq, key = parse_clause_id(item)
        except UserError:
            raise _Bad("неверный пункт ответа: нужен вид D-0001/5.2") from None
        documents.append(format_document_id(seq))
        if key not in keys:
            keys.append(key)
    if len(set(documents)) != 1:
        raise _Bad("пункты `answers` из разных договоров — нужен один документ")
    return documents[0], tuple(keys)


def _contains_of(value: object) -> tuple[str, ...]:
    items = [value] if isinstance(value, str) else value
    if (
        not isinstance(items, list)
        or not items
        or not all(isinstance(i, str) and i.strip() for i in items)
    ):
        raise _Bad("`contains` — непустая строка или список непустых строк")
    return tuple(items)


def _draft(number: int, entry: Any) -> QuestionDraft:
    if not isinstance(entry, dict):
        raise _Bad("нет текста вопроса (`text`)")
    text = entry.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _Bad("нет текста вопроса (`text`)")
    chosen = [k for k in _QUESTION_SELECTORS if k in entry]
    if len(chosen) != 1:
        raise _Bad("нужно ровно одно из `answer`, `answers`, `expected`")
    kind_raw = entry.get("kind", "text")
    try:
        kind = QuestionKind(kind_raw)
    except ValueError:
        raise _Bad("`kind` — text, table или both") from None
    false_premise = entry.get("false_premise", False)
    if not isinstance(false_premise, bool):
        raise _Bad("`false_premise` — true или false")
    document: str | None = _document_of(entry["document"]) if "document" in entry else None
    keys: tuple[str, ...] = ()
    if chosen[0] == "expected":
        if entry["expected"] not in ("answer", "none"):
            raise _Bad("`expected` — «answer» или «none»")
        if document is None:
            raise _Bad("с `expected` нужен `document`")
        has_answer = entry["expected"] == "answer"
    else:
        from_clause, keys = _clauses_of(entry)
        if document is not None and document != from_clause:
            raise _Bad("`document` не совпадает с документом пункта")
        document, has_answer = from_clause, True
    expected: tuple[str, ...] = ()
    if "contains" in entry:
        if not has_answer:
            raise _Bad("`contains` не нужен вопросу без ответа")
        expected = _contains_of(entry["contains"])
    return QuestionDraft(
        number, text.strip(), document, kind, has_answer, false_premise, expected, keys
    )


def parse_question_file(text: str) -> ParsedQuestions:
    """A questions file (TOML); a bad file raises `ValueError`, a bad question is listed."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise ValueError("файл вопросов — не TOML") from None
    origin: QuestionOrigin | None = None
    if "origin" in data:
        try:
            origin = QuestionOrigin(data["origin"])
        except ValueError:
            names = ", ".join(o.value for o in QuestionOrigin)
            raise ValueError(f"неизвестное значение `origin` (допустимо: {names})") from None
    entries = data.get("question", [])
    if not isinstance(entries, list):
        raise ValueError("`question` — список таблиц [[question]]")
    drafts: list[QuestionDraft] = []
    errors: list[tuple[int, str]] = []
    for number, entry in enumerate(entries, start=1):
        try:
            drafts.append(_draft(number, entry))
        except _Bad as exc:
            errors.append((number, str(exc)))
    return ParsedQuestions(origin, drafts, errors)


# --- TOML writing --------------------------------------------------------------------------


def toml_string(value: str) -> str:
    """A TOML basic string (JSON escaping is valid TOML; DEL is escaped too)."""
    return json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return toml_string(value)
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise ValueError(f"unsupported TOML value: {type(value).__name__}")


_KEY_ORDER = ("text", "document", "answer", "answers", "expected", "contains", "kind",
              "false_premise")


def _write_entry(entry: dict[str, Any], comment: str | None = None) -> str:
    lines = [f"# {comment}"] if comment else []
    lines.append("[[question]]")
    keys = [k for k in _KEY_ORDER if k in entry] + [k for k in entry if k not in _KEY_ORDER]
    lines += [f"{k} = {_toml_value(entry[k])}" for k in keys]
    return "\n".join(lines) + "\n"


def _write_set(origin: str | None, entries: list[tuple[dict[str, Any], str | None]]) -> str:
    head = f"origin = {toml_string(origin)}\n\n" if origin else ""
    return head + "\n".join(_write_entry(e, c) for e, c in entries)


# --- load ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionError:
    number: int
    reason: str


@dataclass(frozen=True)
class FileLoad:
    file: str
    loaded: int
    replaced: int
    errors: list[QuestionError]

    def to_json(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "loaded": self.loaded,
            "replaced": self.replaced,
            "errors": [{"number": e.number, "reason": e.reason} for e in self.errors],
        }


@dataclass(frozen=True)
class Composition:
    total: int
    text: int
    table: int
    both: int
    no_answer: int
    false_premise: int
    no_clause: int

    def to_json(self) -> dict[str, int]:
        return {
            "total": self.total, "text": self.text, "table": self.table, "both": self.both,
            "no_answer": self.no_answer, "false_premise": self.false_premise,
            "no_clause": self.no_clause,
        }


@dataclass(frozen=True)
class Conflict:
    key: str
    files: tuple[str, str]  # (the file the row came from, the file that replaced it)

    def to_json(self) -> dict[str, Any]:
        return {"key": self.key, "files": list(self.files)}


@dataclass(frozen=True)
class QuestionsReport:
    files: list[FileLoad]
    composition: Composition
    warnings: list[str]
    conflicts: list[Conflict]
    questions_sha256: str

    def to_json(self) -> dict[str, Any]:
        return {
            "files": [f.to_json() for f in self.files],
            "composition": self.composition.to_json(),
            "warnings": self.warnings,
            "conflicts": [c.to_json() for c in self.conflicts],
            "questions_sha256": self.questions_sha256,
        }


def current_sha256(conn: psycopg.Connection) -> str:
    """The version of the questions: SHA-256 over the rows sorted by key (data-model.md)."""
    rows = conn.execute(
        "SELECT key, document_id, kind, has_answer, false_premise, expected, clause_keys "
        "FROM gold_question ORDER BY key"
    ).fetchall()
    lines = [
        "\t".join((k, d, kind, str(a), str(f), "\x1f".join(e), "\x1f".join(c)))
        for k, d, kind, a, f, e, c in rows
    ]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def composition(conn: psycopg.Connection) -> Composition:
    row = conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE kind = 'text'), "
        "count(*) FILTER (WHERE kind = 'table'), count(*) FILTER (WHERE kind = 'both'), "
        "count(*) FILTER (WHERE NOT has_answer), count(*) FILTER (WHERE false_premise), "
        "count(*) FILTER (WHERE has_answer AND cardinality(clause_keys) = 0) FROM gold_question"
    ).fetchone()
    assert row is not None
    return Composition(*row)


def composition_warnings(c: Composition) -> list[str]:
    warnings: list[str] = []
    if c.no_answer < MIN_WITHOUT_ANSWER:
        warnings.append(f"вопросов без ответа меньше {MIN_WITHOUT_ANSWER} ({c.no_answer})")
    if c.false_premise < MIN_FALSE_PREMISE:
        warnings.append(f"вопросов с ложной посылкой меньше {MIN_FALSE_PREMISE} "
                        f"({c.false_premise})")
    if c.no_clause > 0:
        warnings.append(f"пункт не указан у {c.no_clause} вопросов — подберите пункты: "
                        "docreader eval questions clauses --answers ФАЙЛ.json "
                        "--questions ФАЙЛ.toml")
    return warnings


def source_name(path: Path, data_dir: Path) -> str:
    """The path relative to the data folder when inside it, else the file name."""
    try:
        return path.resolve().relative_to(data_dir.resolve()).as_posix()
    except ValueError:
        return path.name


def _problems(
    drafts: list[QuestionDraft],
    documents: set[str],
    clauses: set[tuple[str, str]],
) -> tuple[list[QuestionDraft], list[QuestionError]]:
    good: list[QuestionDraft] = []
    errors: list[QuestionError] = []
    for q in drafts:
        if q.document_id not in documents:
            errors.append(QuestionError(q.number, f"документа {q.document_id} нет в реестре"))
            continue
        missing = [k for k in q.clause_keys if (q.document_id, k) not in clauses]
        if missing:
            errors.append(QuestionError(
                q.number,
                f"пункта {q.document_id}/{missing[0]} нет в текущем разборе документа",
            ))
            continue
        good.append(q)
    return good, errors


def load_questions(
    conn: psycopg.Connection,
    files: list[Path],
    data_dir: Path,
    origin: QuestionOrigin | None,
) -> QuestionsReport:
    """Load the files in order; one transaction and one `gold_load` row per file."""
    parsed_files: list[tuple[Path, bytes, ParsedQuestions]] = []
    for path in files:
        try:
            raw = path.read_bytes()
        except OSError:
            raise UserError(f"Нет файла с вопросами {path.name}") from None
        try:
            parsed_files.append((path, raw, parse_question_file(raw.decode("utf-8"))))
        except (ValueError, UnicodeDecodeError) as exc:
            raise UserError(f"Файл {path.name}: {exc}") from None
    documents = {r[0] for r in conn.execute("SELECT id FROM document").fetchall()}
    clauses = {(r[0], r[1]) for r in conn.execute("SELECT document_id, key FROM clause")}
    results: list[FileLoad] = []
    conflicts: list[Conflict] = []
    for path, raw, parsed in parsed_files:
        name = source_name(path, data_dir)
        good, bad = _problems(parsed.questions, documents, clauses)
        errors = [QuestionError(n, r) for n, r in parsed.errors] + bad
        errors.sort(key=lambda e: e.number)
        file_origin = parsed.origin or origin or QuestionOrigin.OWN
        with conn.transaction():
            replaced = conn.execute(
                "DELETE FROM gold_question WHERE source_file = %s", (name,)
            ).rowcount
            load_id = conn.execute(
                "INSERT INTO gold_load (kind, file_name, file_sha256, gold_sha256, counts) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                ("questions", name, hashlib.sha256(raw).hexdigest(), "0" * 64,
                 Jsonb({"loaded": len(good), "replaced": replaced, "errors": len(errors)})),
            ).fetchone()[0]  # type: ignore[index]
            for q in good:
                key = q.key
                old = conn.execute(
                    "SELECT kind, has_answer, false_premise, clause_keys, source_file "
                    "FROM gold_question WHERE key = %s", (key,)
                ).fetchone()
                if old is not None and old[:4] != (
                    q.kind.value, q.has_answer, q.false_premise, list(q.clause_keys)
                ):
                    conflicts.append(Conflict(key, (old[4], name)))
                conn.execute(
                    "INSERT INTO gold_question (key, document_id, text, kind, has_answer, "
                    "false_premise, expected, clause_keys, origin, source_file, load_id) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (key) DO UPDATE SET text = EXCLUDED.text, kind = EXCLUDED.kind, "
                    "has_answer = EXCLUDED.has_answer, false_premise = EXCLUDED.false_premise, "
                    "expected = EXCLUDED.expected, clause_keys = EXCLUDED.clause_keys, "
                    "origin = EXCLUDED.origin, source_file = EXCLUDED.source_file, "
                    "load_id = EXCLUDED.load_id",
                    (key, q.document_id, q.text, q.kind.value, q.has_answer, q.false_premise,
                     list(q.expected), list(q.clause_keys), file_origin.value, name, load_id),
                )
            conn.execute("UPDATE gold_load SET gold_sha256 = %s WHERE id = %s",
                         (current_sha256(conn), load_id))
        results.append(FileLoad(name, len(good), replaced, errors))
    comp = composition(conn)
    return QuestionsReport(results, comp, composition_warnings(comp), conflicts,
                           current_sha256(conn))


# --- generate ------------------------------------------------------------------------------


@dataclass(frozen=True)
class GenerateReport:
    path: str  # relative to the data folder
    with_answer: int
    no_answer: int
    false_premise: int
    shortfall: int  # false-premise questions asked for and not made

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path, "with_answer": self.with_answer, "no_answer": self.no_answer,
            "false_premise": self.false_premise, "shortfall": self.shortfall,
        }


def _stamp() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}"


def _output_path(data_dir: Path, out: Path | None, default_name: str) -> Path:
    """Where a new file goes: inside the data folder, never over an existing file."""
    path = out if out is not None else data_dir / "questions" / default_name
    resolved = path.resolve()
    try:
        resolved.relative_to(data_dir.resolve())
    except ValueError:
        raise UserError("Файл можно записать только в папку данных") from None
    if resolved.exists():
        raise UserError("Такой файл уже есть — укажите другой путь, поверх файла не пишем")
    return path


def _write_new(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:  # "x": never over an existing file
        handle.write(content)


def _relative(path: Path, data_dir: Path) -> str:
    return path.resolve().relative_to(data_dir.resolve()).as_posix()


def question_text(field_name: str) -> str:
    if field_name in TEMPLATES:
        return TEMPLATES[field_name]
    return f"Какой показатель «{_label(field_name)}» по договору?"


def _label(field_name: str) -> str:
    try:
        return catalog.field(field_name).label
    except KeyError:
        return field_name


_T = TypeVar("_T")


def _even_pick(items: list[_T], n: int) -> list[_T]:
    if len(items) <= n:
        return items
    return [items[i * len(items) // n] for i in range(n)]


def generate_questions(
    conn: psycopg.Connection, data_dir: Path, out: Path | None, false_premise: int = 10
) -> GenerateReport:
    """Questions from the gold set of fields (research R-11) into a new TOML file."""
    path = _output_path(data_dir, out, f"generated-{_stamp()}.toml")
    rows = conn.execute(
        "SELECT document_id, field, state, values_text, values_normalized, clause_key "
        "FROM gold_field ORDER BY document_id, field"
    ).fetchall()
    entries: list[tuple[dict[str, Any], str | None]] = []
    with_answer = no_answer = 0
    by_field: dict[str, list[tuple[str, list[str], list[str]]]] = {}
    candidates: list[tuple[str, str]] = []
    for doc, field_name, state, texts, norms, clause in rows:
        if state == "absent":
            entries.append(({"text": question_text(field_name), "document": doc,
                             "expected": "none"}, None))
            no_answer += 1
            continue
        by_field.setdefault(field_name, []).append((doc, texts, norms))
        if clause is None:
            continue
        entries.append(({"text": question_text(field_name),
                         "answer": format_clause_id(doc, clause), "contains": [norms[0]]}, None))
        with_answer += 1
        try:
            kind = catalog.field(field_name).kind
        except KeyError:
            continue
        if kind in (catalog.CatalogKind.AMOUNT, catalog.CatalogKind.DATE):
            candidates.append((doc, field_name))
    clauses = {(d, f): c for d, f, _s, _t, _n, c in rows}
    premises: list[tuple[dict[str, Any], str | None]] = []
    for doc, field_name in _even_pick(sorted(candidates), false_premise):
        peers = by_field[field_name]
        mine = next(p for p in peers if p[0] == doc)
        order = sorted(peers)
        start = order.index(mine)
        other = next(
            (p for p in order[start + 1:] + order[:start] if p[2][0] != mine[2][0]), None
        )
        if other is None:
            continue
        premises.append(({
            "text": f"Почему {_label(field_name)} по договору — {other[1][0]}?",
            "answer": format_clause_id(doc, str(clauses[(doc, field_name)])),
            "false_premise": True, "contains": [mine[2][0]],
        }, None))
    entries += premises
    _write_new(path, _write_set("generated", entries))
    return GenerateReport(_relative(path, data_dir), with_answer, no_answer, len(premises),
                          max(0, false_premise - len(premises)))


# --- clauses -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClausesReport:
    path: str  # relative to the data folder
    without_clause: int
    proposed: int
    no_confirmed: int

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path, "without_clause": self.without_clause,
            "proposed": self.proposed, "no_confirmed": self.no_confirmed,
        }


PROPOSAL_COMMENT = "пункт из ответа — проверить"


def propose_clauses(
    answers_json: Path, questions_toml: Path, data_dir: Path, out: Path | None
) -> ClausesReport:
    """Fill `answers` of the «пункт не указан» questions from the confirmed claims."""
    try:
        answers = json.loads(answers_json.read_text(encoding="utf-8"))
        source_text = questions_toml.read_text(encoding="utf-8")
    except (OSError, ValueError):
        raise UserError("Не удалось прочитать файл ответов или файл вопросов") from None
    if not isinstance(answers, dict) or answers.get("format") != ANSWERS_FORMAT:
        raise UserError(f"Файл ответов не в формате {ANSWERS_FORMAT}")
    confirmed: dict[str, list[str]] = {}
    for item in answers.get("questions", []):
        try:
            key = question_key(_document_of(item["document"]), item["text"])
            confirmed[key] = [str(c) for c in item["confirmed_clauses"]]
        except (_Bad, KeyError, TypeError):
            raise UserError("В файле ответов неверная запись вопроса") from None
    try:
        parsed = parse_question_file(source_text)
    except ValueError as exc:
        raise UserError(f"Файл вопросов: {exc}") from None
    raw_entries = tomllib.loads(source_text).get("question", [])
    drafts = {q.number: q for q in parsed.questions}
    path = _output_path(
        data_dir, out, f"{questions_toml.stem}-clauses-{_stamp()}.toml"
    )
    entries: list[tuple[dict[str, Any], str | None]] = []
    without = proposed = 0
    for number, entry in enumerate(raw_entries, start=1):
        draft = drafts.get(number)
        if draft is None or not draft.has_answer or draft.clause_keys:
            entries.append((entry, None))
            continue
        without += 1
        prefix = draft.document_id + "/"
        found = [c for c in confirmed.get(draft.key, []) if c.startswith(prefix)]
        if not found:
            entries.append((entry, None))
            continue
        proposed += 1
        changed = {k: v for k, v in entry.items() if k != "expected"}
        changed["answers"] = found
        entries.append((changed, PROPOSAL_COMMENT))
    origin = parsed.origin.value if parsed.origin else None
    _write_new(path, _write_set(origin, entries))
    return ClausesReport(_relative(path, data_dir), without, proposed, without - proposed)
