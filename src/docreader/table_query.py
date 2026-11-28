"""Checking, running and describing a table query (feature 10, research R-4, R-6, R-7, R-8).

Pure functions, no database and no model. `validate` turns the model's `TableReply` into
a `TableQuery` whose value is normalized by the rules of the extracted values (feature
05), or names the problem. The text of a problem for the analyst is built from its code
and the allowed names only: no string of the model's reply gets into it (FR-014); the
model's own string is kept apart, for the message of the one retry (research R-9).
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from docreader import catalog, values
from docreader.checks import CellState
from docreader.ids import parse_document_id
from docreader.table_prompt import ACTIONS, FIELD_OPS, PERIODS, TableReply

_KIND = {
    "contract_number": values.Kind.IDENTIFIER,
    "customer_name_short": values.Kind.NAME,
    "contractor_name_short": values.Kind.NAME,
    "party": values.Kind.NAME,
    "amount_without_vat": values.Kind.AMOUNT,
    "amount_with_vat": values.Kind.AMOUNT,
    "contract_end_date": values.Kind.DATE,
}
_KIND_WORD = {
    values.Kind.IDENTIFIER: "номер договора",
    values.Kind.NAME: "наименование",
    values.Kind.AMOUNT: "сумма в рублях",
    values.Kind.DATE: "дата ГГГГ-ММ-ДД или код периода",
}
# what a period code looks like: a misspelt code is `unknown_period`, not a bad date
_CODE_LIKE = re.compile(r"[a-z]+(?:_[a-z]+)+")


@dataclass(frozen=True)
class TableQuery:
    """A checked query (data-model.md). `side` is set by `execute` for `party`."""

    action: str
    field: str
    op: str
    value: str | Decimal
    value_to: str | None = None
    period: str | None = None
    other: str | None = None
    side: str | None = None


@dataclass(frozen=True)
class NonQuery:
    """A reply that is not a query: `refuse`, `clarify` or `unsupported` with its reason."""

    kind: str
    reason: str


@dataclass(frozen=True)
class Problem:
    """Why a reply is not a valid query (research R-4).

    `field` is an allowed field name or None; `detail` is the model's own string, used only
    in the retry message (it never leaves the machine), never in `text()`.
    """

    code: str
    field: str | None = None
    detail: str | None = None
    kind: str | None = None

    def text(self) -> str:
        return _problem_text(self)

    def retry_text(self) -> str:
        if self.detail is None:
            return self.text()
        return f"{self.text()} (в ответе: {self.detail})"


def _problem_text(p: Problem) -> str:
    fields = ", ".join(FIELD_OPS)
    if p.code == "unknown_action":
        return f"действие не из перечня; допустимы {', '.join(ACTIONS)}"
    if p.code == "unknown_field":
        return f"поле не из перечня; допустимы {fields}"
    if p.code == "op_not_allowed":
        ops = ", ".join(FIELD_OPS[p.field]) if p.field else ""
        return f"сравнение не допустимо для поля {p.field}; допустимы {ops}"
    if p.code == "value_not_normalized":
        word = _KIND_WORD[_KIND[p.field]] if p.field else "значение"
        return f"значение не приводится к виду поля {p.field} ({word})"
    if p.code == "missing_value":
        return f"нет значения value для поля {p.field}"
    if p.code == "missing_value_to":
        return "для between нужна вторая дата value_to или код периода в value"
    if p.code == "bad_range":
        return "начало периода позже его конца"
    if p.code == "unknown_period":
        return f"код периода не из перечня; допустимы {', '.join(PERIODS)}"
    if p.code == "missing_reason":
        return f"нет причины reason для исхода {p.kind}"
    raise ValueError(p.code)


# --- periods (research R-6) ---------------------------------------------------------


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _shift_month(year: int, month: int, by: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + by
    return index // 12, index % 12 + 1


def resolve_period(code: str, today: date) -> tuple[date, date]:
    """The first and the last day (both inclusive) of a period code relative to today."""
    if code not in PERIODS:
        raise ValueError(code)
    which, unit = code.split("_")
    shift = {"this": 0, "last": -1, "next": 1}[which]
    if unit == "year":
        year = today.year + shift
        return date(year, 1, 1), date(year, 12, 31)
    if unit == "quarter":
        first_month = (today.month - 1) // 3 * 3 + 1
        year, month = _shift_month(today.year, first_month, 3 * shift)
        end_year, end_month = _shift_month(year, month, 2)
        return date(year, month, 1), _month_end(end_year, end_month)
    year, month = _shift_month(today.year, today.month, shift)
    return date(year, month, 1), _month_end(year, month)


# --- validate (research R-4) --------------------------------------------------------


def _blank(text: str | None) -> bool:
    return text is None or not text.strip()


def _normalize(field: str, raw: str) -> str | Decimal | Problem:
    kind = _KIND[field]
    try:
        normalized = values.normalize(kind, raw)
    except values.ValueNotNormalized:
        return Problem("value_not_normalized", field, raw)
    return Decimal(normalized) if kind is values.Kind.AMOUNT else normalized


def _date_value(raw: str) -> str | Problem:
    got = _normalize("contract_end_date", raw)
    if isinstance(got, Problem) and _CODE_LIKE.fullmatch(raw.strip()):
        return Problem("unknown_period", "contract_end_date", raw)
    assert not isinstance(got, Decimal)
    return got


def _date_query(
    reply: TableReply, action: str, today: date, other: str | None
) -> TableQuery | Problem:
    raw = (reply.value or "").strip()
    op = reply.op or ""
    if raw in PERIODS:
        start, end = (d.isoformat() for d in resolve_period(raw, today))
        if op == "before":
            return TableQuery(action, "contract_end_date", op, start, period=raw, other=other)
        if op == "after":
            return TableQuery(action, "contract_end_date", op, end, period=raw, other=other)
        return TableQuery(action, "contract_end_date", "between", start, end, raw, other)
    first = _date_value(raw)
    if isinstance(first, Problem):
        return first
    if op != "between":
        return TableQuery(action, "contract_end_date", op, first, other=other)
    if _blank(reply.value_to):
        return Problem("missing_value_to", "contract_end_date")
    assert reply.value_to is not None
    second = _normalize("contract_end_date", reply.value_to)
    if isinstance(second, Problem):
        return second
    assert isinstance(second, str)
    if first > second:
        return Problem("bad_range", "contract_end_date")
    return TableQuery(action, "contract_end_date", "between", first, second, other=other)


def validate(reply: TableReply, today: date) -> TableQuery | NonQuery | Problem:
    """The checked query, the reply that is not a query, or the problem of the reply."""
    if reply.kind != "query":
        if _blank(reply.reason):
            return Problem("missing_reason", kind=reply.kind)
        assert reply.reason is not None
        return NonQuery(reply.kind, reply.reason.strip())
    if reply.action not in ACTIONS:
        return Problem("unknown_action", detail=reply.action)
    field = reply.field
    if field not in FIELD_OPS:
        return Problem("unknown_field", detail=field)
    if reply.op not in FIELD_OPS[field]:
        return Problem("op_not_allowed", field, reply.op)
    if _blank(reply.value):
        return Problem("missing_value", field)
    assert reply.value is not None
    other = None if _blank(reply.other) else (reply.other or "").strip()
    if field == "contract_end_date":
        return _date_query(reply, reply.action, today, other)
    value = _normalize(field, reply.value)
    if isinstance(value, Problem):
        return value
    return TableQuery(reply.action, field, reply.op, value, other=other)


# --- rows of the table (research R-5) ------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """One field of one contract as the answer sees it (data-model.md)."""

    state: CellState
    value: str | None
    clause_id: str | None
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocRow:
    """The six cells of one contract of the registry."""

    document_id: str
    cells: Mapping[str, Cell]


def counted_states(include_unreviewed: bool) -> frozenset[CellState]:
    """The cell states whose value is counted (research R-5, R-7)."""
    if include_unreviewed:
        return frozenset({CellState.EFFECTIVE, CellState.UNREVIEWED})
    return frozenset({CellState.EFFECTIVE})


# --- names (research R-7) ------------------------------------------------------------

# abbreviated legal forms that open a short name (as in `values`)
_FORMS = ("ОАО", "ЗАО", "ПАО", "НАО", "АО", "ООО", "ОДО", "ФГУП", "ГУП", "МУП")
_FORM_START = re.compile(r"^(" + "|".join(_FORMS) + r")\s+(.+)$", re.IGNORECASE)
_NAME_FIELD = catalog.field("customer_name_short")
_QUOTES = "\"'"  # quotes are already straight in a normalized name
_ANY_FORM = "ООО"  # a stand-in form, so that two names in quotes compare by the same rule


def _canonical(name: str) -> tuple[str, bool]:
    """`FORM "name"` and True, or the bare name without quotes and False."""
    text = values.canonical_short_name(name).strip()
    m = _FORM_START.match(text)
    if m is None:
        return text.strip(_QUOTES).strip(), False
    bare = m[2].strip().strip(_QUOTES).strip()
    return f'{m[1].upper()} "{bare}"', True


def match_names(name: str, table_value: str) -> bool:
    """Whether the name of the question is the table's name (research R-7).

    With a legal form: the rule of feature 02 (`values.same_value`: case, the form written
    out, initials). Without one: compared with the name in quotes of the table value by
    the same rule. Never by a part of the name.
    """
    q, q_form = _canonical(name)
    t, t_form = _canonical(table_value)
    if q_form or not t_form:
        return values.same_value(_NAME_FIELD, q, t)
    quoted = t.split(" ", 1)[1].strip('"')
    return values.same_value(_NAME_FIELD, f'{_ANY_FORM} "{q}"', f'{_ANY_FORM} "{quoted}"')


_SIDES = (("customer", "customer_name_short"), ("contractor", "contractor_name_short"))
CLARIFY_SIDE = "наименование есть и среди заказчиков, и среди подрядчиков: заказчик или подрядчик?"


def resolve_party(
    query: TableQuery, rows: Sequence[DocRow], include_unreviewed: bool
) -> TableQuery | NonQuery:
    """The side of a `party` query, chosen by the cells that are counted (research R-7)."""
    if query.field != "party":
        return query
    counted = counted_states(include_unreviewed)
    sides = {
        side
        for row in rows
        for side, field in _SIDES
        if (c := row.cells[field]).state in counted
        and c.value is not None
        and match_names(str(query.value), c.value)
    }
    if len(sides) > 1:
        return NonQuery("clarify", CLARIFY_SIDE)
    if not sides:
        return query
    side = sides.pop()
    return replace(query, field=dict(_SIDES)[side], side=side)


# --- execute (research R-7) ----------------------------------------------------------


@dataclass(frozen=True)
class ResultRow:
    """A contract that meets the condition; `unreviewed` — its value is not checked yet."""

    row: DocRow
    unreviewed: bool


@dataclass(frozen=True)
class Result:
    """The outcome of a query over the table (data-model.md)."""

    query: TableQuery
    rows: tuple[ResultRow, ...]
    matched_names: tuple[str, ...]
    excluded: Mapping[str, tuple[str, ...]]
    considered: int
    total: int
    include_unreviewed: bool

    @property
    def count(self) -> int:
        return len(self.rows)


def _order(document_id: str) -> int:
    return parse_document_id(document_id)


def _meets(query: TableQuery, value: str) -> bool:
    op = query.op
    if query.field in ("amount_without_vat", "amount_with_vat"):
        bound = query.value
        assert isinstance(bound, Decimal)
        number = Decimal(value)
        return {"eq": number == bound, "gt": number > bound, "ge": number >= bound,
                "lt": number < bound, "le": number <= bound}[op]
    if query.field == "contract_end_date":
        start = str(query.value)
        if op == "before":
            return value < start
        if op == "after":
            return value > start
        if op == "between":
            assert query.value_to is not None
            return start <= value <= query.value_to
        return value == start
    if query.field == "contract_number":
        return value == query.value
    return match_names(str(query.value), value)


def execute(query: TableQuery, rows: Sequence[DocRow], include_unreviewed: bool) -> Result:
    """Every contract counted by its condition cell, in document id order (research R-7).

    A contract whose condition cell is not counted is excluded under the cell's state. A
    `party` query with no side (the name matched neither) is counted only where both name
    cells are; otherwise excluded under the customer's state, else the contractor's.
    """
    counted = counted_states(include_unreviewed)
    found: list[ResultRow] = []
    names: list[str] = []
    excluded: dict[str, list[str]] = {}
    considered = 0
    for row in sorted(rows, key=lambda item: _order(item.document_id)):
        fields = [f for _, f in _SIDES] if query.field == "party" else [query.field]
        cells = [row.cells[f] for f in fields]
        missing = next((c for c in cells if c.state not in counted or c.value is None), None)
        if missing is not None:
            excluded.setdefault(missing.state.value, []).append(row.document_id)
            continue
        considered += 1
        hits = [c for c in cells if c.value is not None and _meets(query, c.value)]
        if not hits:
            continue
        found.append(ResultRow(row, any(c.state is CellState.UNREVIEWED for c in hits)))
        if _KIND.get(query.field) is values.Kind.NAME:
            names.extend(str(c.value) for c in hits)
    return Result(
        query=query,
        rows=tuple(found),
        matched_names=tuple(dict.fromkeys(names)),
        excluded={state: tuple(docs) for state, docs in excluded.items()},
        considered=considered,
        total=len(rows),
        include_unreviewed=include_unreviewed,
    )


# --- describe (research R-8) ---------------------------------------------------------

_FIELD_WORD = {
    "contract_number": "номер договора",
    "customer_name_short": "заказчик",
    "contractor_name_short": "подрядчик",
    "party": "заказчик или подрядчик",
    "amount_without_vat": "цена без НДС",
    "amount_with_vat": "цена с НДС",
    "contract_end_date": "дата окончания",
}
_OP_WORD = {"eq": "равна", "gt": "больше", "ge": "не меньше", "lt": "меньше", "le": "не больше"}


def format_amount(amount: Decimal | str) -> str:
    """`1 000 000,00`: plain-space thousands, comma decimals, two decimals."""
    return f"{Decimal(amount):,.2f}".replace(",", " ").replace(".", ",")


def describe(query: TableQuery) -> str:
    """The condition in words for the analyst, from the query's normalized value (R-8)."""
    head = _FIELD_WORD[query.field]
    if query.field in ("amount_without_vat", "amount_with_vat"):
        text = f"{head} {_OP_WORD[query.op]} {format_amount(query.value)} руб."
    elif query.field == "contract_end_date":
        if query.op == "between":
            text = f"{head} с {query.value} по {query.value_to}"
        elif query.op == "before":
            text = f"{head} раньше {query.value}"
        elif query.op == "after":
            text = f"{head} позже {query.value}"
        else:
            text = f"{head} — {query.value}"
    else:
        text = f"{head} — {query.value}"
    if query.side is not None:
        text += " (сторона выбрана по таблице)"
    return text
