"""Checking, running and describing a table query (feature 10, research R-4, R-6, R-7, R-8).

Written by the main session (T007–T010): the implementer must not edit, weaken, skip or
delete these tests (CLAUDE.md «Model routing»).

Interface of `docreader.table_query`:
- `validate(reply: TableReply, today: date) -> TableQuery | NonQuery | Problem`;
- `TableQuery(action, field, op, value, value_to=None, period=None, other=None, side=None)`:
  `value` — normalized: identifier and name `str`, amount `Decimal`, date ISO `str`;
  a period code is resolved: with `eq`/`between` → `op="between"` with both dates,
  with `before` → the start, with `after` → the end; `period` keeps the code;
- `NonQuery(kind, reason)` for `refuse`, `clarify`, `unsupported` with a reason;
- `Problem(code, field=None, detail=None)`; `.text()` — Russian, built from the code and
  the allowed names only; `.retry_text()` — the text plus `detail` (the model's own
  string), only for the message of the retry (research R-9);
- `resolve_period(code, today) -> (date, date)`, both inclusive; unknown code → ValueError.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from docreader import table_query as tq
from docreader.checks import CellState
from docreader.table_prompt import TableReply

TODAY = date(2026, 11, 28)
SECRET = "Секрет-Вымысел-7781"


def r(**over) -> TableReply:
    base = {"kind": "query", "action": "list", "field": "amount_with_vat", "op": "gt",
            "value": "1000000"}
    base.update(over)
    return TableReply.model_validate(base)


def ok(reply: TableReply, today: date = TODAY) -> tq.TableQuery:
    got = tq.validate(reply, today)
    assert isinstance(got, tq.TableQuery), got
    return got


def problem(reply: TableReply, today: date = TODAY) -> tq.Problem:
    got = tq.validate(reply, today)
    assert isinstance(got, tq.Problem), got
    return got


# --- resolve_period (research R-6) ------------------------------------------------


@pytest.mark.parametrize(
    ("code", "today", "start", "end"),
    [
        ("this_year", date(2026, 11, 28), date(2026, 1, 1), date(2026, 12, 31)),
        ("last_year", date(2026, 1, 1), date(2025, 1, 1), date(2025, 12, 31)),
        ("next_year", date(2026, 12, 31), date(2027, 1, 1), date(2027, 12, 31)),
        ("this_quarter", date(2026, 11, 28), date(2026, 10, 1), date(2026, 12, 31)),
        ("this_quarter", date(2026, 1, 1), date(2026, 1, 1), date(2026, 3, 31)),
        ("this_quarter", date(2026, 6, 30), date(2026, 4, 1), date(2026, 6, 30)),
        ("last_quarter", date(2026, 11, 28), date(2026, 7, 1), date(2026, 9, 30)),
        ("last_quarter", date(2026, 2, 10), date(2025, 10, 1), date(2025, 12, 31)),
        ("next_quarter", date(2026, 11, 28), date(2027, 1, 1), date(2027, 3, 31)),
        ("next_quarter", date(2026, 5, 15), date(2026, 7, 1), date(2026, 9, 30)),
        ("this_month", date(2026, 2, 10), date(2026, 2, 1), date(2026, 2, 28)),
        ("this_month", date(2028, 2, 10), date(2028, 2, 1), date(2028, 2, 29)),
        ("last_month", date(2026, 1, 15), date(2025, 12, 1), date(2025, 12, 31)),
        ("last_month", date(2026, 3, 31), date(2026, 2, 1), date(2026, 2, 28)),
        ("next_month", date(2026, 12, 31), date(2027, 1, 1), date(2027, 1, 31)),
        ("next_month", date(2026, 1, 31), date(2026, 2, 1), date(2026, 2, 28)),
    ],
)
def test_resolve_period(code: str, today: date, start: date, end: date) -> None:
    assert tq.resolve_period(code, today) == (start, end)


def test_resolve_period_unknown_code() -> None:
    with pytest.raises(ValueError):
        tq.resolve_period("this_decade", TODAY)


# --- validate: actions, fields, comparisons ---------------------------------------


def test_valid_amount_query() -> None:
    q = ok(r())
    assert (q.action, q.field, q.op) == ("list", "amount_with_vat", "gt")
    assert q.value == Decimal("1000000")
    assert q.value_to is None and q.period is None and q.other is None


@pytest.mark.parametrize("action", ["count", "list"])
def test_both_actions(action: str) -> None:
    assert ok(r(action=action)).action == action


@pytest.mark.parametrize("action", [None, "sum", "COUNT", SECRET])
def test_unknown_action(action: str | None) -> None:
    p = problem(r(action=action))
    assert p.code == "unknown_action"
    assert "count" in p.text() and "list" in p.text()


@pytest.mark.parametrize("field", [None, "price", "Amount_With_Vat", SECRET])
def test_unknown_field(field: str | None) -> None:
    p = problem(r(field=field))
    assert p.code == "unknown_field"
    for name in ("contract_number", "party", "contract_end_date"):
        assert name in p.text()


ALLOWED = {
    "contract_number": {"eq"},
    "customer_name_short": {"eq"},
    "contractor_name_short": {"eq"},
    "party": {"eq"},
    "amount_without_vat": {"eq", "gt", "ge", "lt", "le"},
    "amount_with_vat": {"eq", "gt", "ge", "lt", "le"},
    "contract_end_date": {"before", "after", "eq", "between"},
}
ALL_OPS = ("eq", "gt", "ge", "lt", "le", "before", "after", "between")
GOOD_VALUE = {
    "contract_number": "К-1/2026",
    "customer_name_short": "ООО «Альфа»",
    "contractor_name_short": "Альфа",
    "party": "Альфа",
    "amount_without_vat": "1000000",
    "amount_with_vat": "1000000",
    "contract_end_date": "2026-12-31",
}


@pytest.mark.parametrize("field", list(ALLOWED))
@pytest.mark.parametrize("op", ALL_OPS)
def test_allowed_field_op_pairs(field: str, op: str) -> None:
    value_to = "2027-01-31" if op == "between" else None
    got = tq.validate(r(field=field, op=op, value=GOOD_VALUE[field], value_to=value_to), TODAY)
    if op in ALLOWED[field]:
        assert isinstance(got, tq.TableQuery), (field, op, got)
    else:
        assert isinstance(got, tq.Problem) and got.code == "op_not_allowed", (field, op, got)
        assert got.field == field
        for allowed in ALLOWED[field]:
            assert allowed in got.text()


@pytest.mark.parametrize("op", [None, "contains", SECRET])
def test_unknown_op_is_not_allowed(op: str | None) -> None:
    assert problem(r(op=op)).code == "op_not_allowed"


# --- validate: values -------------------------------------------------------------


def test_contract_number_normalized_as_identifier() -> None:
    q = ok(r(field="contract_number", op="eq", value="№ К-21/2026"))
    assert q.value == "К-21/2026"


@pytest.mark.parametrize("field", ["customer_name_short", "contractor_name_short", "party"])
def test_names_normalized_as_names(field: str) -> None:
    q = ok(r(field=field, op="eq", value="ооо «Альфа»"))
    assert q.value == 'ооо "Альфа"'


@pytest.mark.parametrize("value", ["1500000", "1 500 000,00", "1 500 000 руб.", "1500000.00"])
def test_amounts_are_decimals_whatever_the_spelling(value: str) -> None:
    q = ok(r(value=value))
    assert q.value == Decimal("1500000") and isinstance(q.value, Decimal)


@pytest.mark.parametrize(
    ("field", "value"),
    [("amount_with_vat", "полтора миллиона"), ("amount_without_vat", "-5"),
     ("contract_end_date", "в конце года"), ("customer_name_short", "«»"),
     ("contract_number", "№")],
)
def test_value_not_normalized(field: str, value: str) -> None:
    op = "before" if field == "contract_end_date" else "eq"
    p = problem(r(field=field, op=op, value=value))
    assert p.code == "value_not_normalized" and p.field == field


@pytest.mark.parametrize("field", list(ALLOWED))
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_value(field: str, value: str | None) -> None:
    op = "before" if field == "contract_end_date" else "eq"
    p = problem(r(field=field, op=op, value=value))
    assert p.code == "missing_value" and p.field == field


@pytest.mark.parametrize("value", ["2026-12-31", "31.12.2026", "31 декабря 2026 г."])
@pytest.mark.parametrize("op", ["before", "after", "eq"])
def test_single_date_is_iso(op: str, value: str) -> None:
    q = ok(r(field="contract_end_date", op=op, value=value))
    assert (q.op, q.value, q.value_to, q.period) == (op, "2026-12-31", None, None)


def test_value_to_ignored_outside_between() -> None:
    q = ok(r(field="contract_end_date", op="before", value="2026-12-31", value_to="2027-01-01"))
    assert q.value_to is None
    assert ok(r(value_to="2027-01-01")).value_to is None


def test_between_two_dates_inclusive_order() -> None:
    q = ok(r(field="contract_end_date", op="between", value="01.01.2026", value_to="2026-06-30"))
    assert (q.op, q.value, q.value_to, q.period) == ("between", "2026-01-01", "2026-06-30", None)
    same = ok(r(field="contract_end_date", op="between", value="2026-06-30", value_to="2026-06-30"))
    assert (same.value, same.value_to) == ("2026-06-30", "2026-06-30")


def test_between_without_second_date() -> None:
    p = problem(r(field="contract_end_date", op="between", value="2026-01-01", value_to=None))
    assert p.code == "missing_value_to"


def test_between_second_date_not_normalized() -> None:
    p = problem(r(field="contract_end_date", op="between", value="2026-01-01", value_to="потом"))
    assert p.code == "value_not_normalized"


def test_between_start_after_end_is_bad_range() -> None:
    p = problem(r(field="contract_end_date", op="between", value="2026-12-31",
                  value_to="2026-01-01"))
    assert p.code == "bad_range"


@pytest.mark.parametrize("op", ["eq", "between"])
def test_period_code_with_eq_or_between_is_the_whole_period(op: str) -> None:
    q = ok(r(field="contract_end_date", op=op, value="this_year"))
    assert (q.op, q.value, q.value_to, q.period) == ("between", "2026-01-01", "2026-12-31",
                                                     "this_year")


def test_period_code_with_before_is_before_the_start() -> None:
    q = ok(r(field="contract_end_date", op="before", value="next_quarter"))
    assert (q.op, q.value, q.value_to, q.period) == ("before", "2027-01-01", None, "next_quarter")


def test_period_code_with_after_is_after_the_end() -> None:
    q = ok(r(field="contract_end_date", op="after", value="last_month"))
    assert (q.op, q.value, q.value_to, q.period) == ("after", "2026-10-31", None, "last_month")


def test_period_follows_today() -> None:
    q = ok(r(field="contract_end_date", op="eq", value="this_quarter"), date(2027, 2, 1))
    assert (q.value, q.value_to) == ("2027-01-01", "2027-03-31")


@pytest.mark.parametrize("value", ["this_decade", "last_week", "next_years"])
def test_unknown_period(value: str) -> None:
    p = problem(r(field="contract_end_date", op="eq", value=value))
    assert p.code == "unknown_period"
    assert "this_year" in p.text() and "next_month" in p.text()


def test_other_carried() -> None:
    assert ok(r(other="и какие из них истекают")).other == "и какие из них истекают"
    assert ok(r(other="  ")).other is None


def test_query_has_no_side_before_execution() -> None:
    assert ok(r(field="party", op="eq", value="Альфа")).side is None


# --- validate: the other outcomes -------------------------------------------------


@pytest.mark.parametrize("kind", ["refuse", "clarify", "unsupported"])
def test_other_outcomes_with_a_reason(kind: str) -> None:
    got = tq.validate(TableReply.model_validate({"kind": kind, "reason": "нет поля «предмет»"}),
                      TODAY)
    assert got == tq.NonQuery(kind, "нет поля «предмет»")


@pytest.mark.parametrize("kind", ["refuse", "clarify", "unsupported"])
@pytest.mark.parametrize("reason", [None, "", "  "])
def test_other_outcomes_without_a_reason(kind: str, reason: str | None) -> None:
    got = tq.validate(TableReply.model_validate({"kind": kind, "reason": reason}), TODAY)
    assert isinstance(got, tq.Problem) and got.code == "missing_reason"


# --- Problem texts: no string of the reply (FR-014) -------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        r(action=SECRET),
        r(field=SECRET),
        r(op=SECRET),
        r(value=SECRET),
        r(field="contract_number", op="gt", value=SECRET),
        r(field="contract_end_date", op="before", value=SECRET),
        r(field="contract_end_date", op="eq", value="secret_vymysel_period"),
        r(field="contract_end_date", op="between", value="2026-01-01", value_to=SECRET),
        r(field="contract_end_date", op="between", value="2026-12-31", value_to="2026-01-01"),
        r(field="contract_end_date", op="between", value="2026-01-01"),
        r(value=None),
        TableReply.model_validate({"kind": "refuse", "reason": None, "other": SECRET}),
    ],
)
def test_problem_text_holds_no_string_of_the_reply(reply: TableReply) -> None:
    p = problem(reply)
    text = p.text()
    assert text and SECRET.casefold() not in text.casefold()
    assert "secret_vymysel_period" not in text
    assert "2026-12-31" not in text and "2026-01-01" not in text
    assert p.code in {
        "unknown_field", "unknown_action", "op_not_allowed", "value_not_normalized",
        "missing_value", "missing_value_to", "bad_range", "unknown_period", "missing_reason",
    }


def test_retry_text_may_name_the_model_string() -> None:
    p = problem(r(field="price"))
    assert p.detail == "price"
    assert "price" in p.retry_text() and p.text() in p.retry_text()
    assert "price" not in p.text()


def test_problem_text_is_russian_and_names_the_field() -> None:
    p = problem(r(field="amount_with_vat", value="много"))
    assert "amount_with_vat" in p.text()
    assert any("а" <= ch <= "я" for ch in p.text().lower())


# --- names and the side (T008, research R-7, clarifications 2026-11-27) -----------
#
# Interface: `match_names(name, table_value) -> bool` (both normalized);
# `Cell(state: CellState, value: str | None, clause_id: str | None, flags: tuple[str, ...])`,
# `DocRow(document_id: str, cells: dict[str, Cell])`;
# `resolve_party(query, rows, include_unreviewed) -> TableQuery | NonQuery`: a non-party
# query unchanged; matched on one side only → the query on that field with
# `side = "customer" | "contractor"`; on both → `NonQuery("clarify", …)` naming both sides;
# on none → the party query unchanged (`execute` gives zero rows).

EFF, UNREV = CellState.EFFECTIVE, CellState.UNREVIEWED


@pytest.mark.parametrize(
    ("name", "table_value"),
    [
        ('ООО "Альфа"', 'ООО "Альфа"'),
        ('ооо "альфа"', 'ООО "Альфа"'),
        ('общество с ограниченной ответственностью "Альфа"', 'ООО "Альфа"'),
        ('ООО "Альфа"', 'общество с ограниченной ответственностью "Альфа"'),
        ('ОАО "АДС"', 'ОАО "Альфа Дельта Строй"'),
        ('ОАО "Альфа Дельта Строй"', 'ОАО "АДС"'),
        ("ООО Альфа", 'ООО "Альфа"'),
        ("Альфа", 'ООО "Альфа"'),
        ("альфа", 'АО "Альфа"'),
        ('"Альфа"', 'ООО "Альфа"'),
        ("АДС", 'ОАО "Альфа Дельта Строй"'),
        ("адс", 'ОАО "Альфа-Дельта-Строй"'),
        ("Альфа", 'акционерное общество "Альфа"'),
        ("Иванов И.И.", "Иванов И.И."),
    ],
)
def test_names_that_match(name: str, table_value: str) -> None:
    assert tq.match_names(name, table_value)


@pytest.mark.parametrize(
    ("name", "table_value"),
    [
        ("Альфа", 'ООО "Альфа-Строй"'),
        ('ООО "Альфа"', 'ООО "Альфа-Строй"'),
        ("Альфа", 'ООО "Бета Альфа"'),
        ("Альфа-Строй", 'ООО "Альфа"'),
        ('АО "Альфа"', 'ООО "Альфа"'),
        ("Бета", 'ООО "Альфа"'),
        ("АД", 'ОАО "Альфа Дельта Строй"'),
    ],
)
def test_names_that_do_not_match(name: str, table_value: str) -> None:
    assert not tq.match_names(name, table_value)


def cell(state: CellState = EFF, value: str | None = None, clause: str | None = None,
         flags: tuple[str, ...] = ()) -> tq.Cell:
    return tq.Cell(state, value, clause, flags)


def row(doc: str, **cells: tq.Cell) -> tq.DocRow:
    base = {
        "contract_number": cell(EFF, f"N-{doc}", f"{doc}/преамбула"),
        "customer_name_short": cell(EFF, 'ООО "Заказ"', f"{doc}/преамбула"),
        "contractor_name_short": cell(EFF, 'ООО "Подряд"', f"{doc}/преамбула"),
        "amount_without_vat": cell(EFF, "1000000.00", f"{doc}/2.1"),
        "amount_with_vat": cell(EFF, "1200000.00", f"{doc}/2.1"),
        "contract_end_date": cell(EFF, "2026-12-31", f"{doc}/5.1"),
    }
    base.update(cells)
    return tq.DocRow(doc, base)


def party(name: str, action: str = "list") -> tq.TableQuery:
    return ok(r(action=action, field="party", op="eq", value=name))


def test_non_party_query_unchanged() -> None:
    q = ok(r())
    assert tq.resolve_party(q, [row("D-0001")], False) is q


def test_party_matched_as_customer_only() -> None:
    rows = [row("D-0001", customer_name_short=cell(EFF, 'ООО "Альфа"')), row("D-0002")]
    got = tq.resolve_party(party("Альфа"), rows, False)
    assert isinstance(got, tq.TableQuery)
    assert (got.field, got.side, got.value, got.op) == ("customer_name_short", "customer",
                                                        "Альфа", "eq")


def test_party_matched_as_contractor_only() -> None:
    rows = [row("D-0001", contractor_name_short=cell(EFF, 'АО "Альфа"')),
            row("D-0002", contractor_name_short=cell(EFF, 'акционерное общество "Альфа"'))]
    got = tq.resolve_party(party("Альфа", "count"), rows, False)
    assert isinstance(got, tq.TableQuery)
    assert (got.field, got.side, got.action) == ("contractor_name_short", "contractor", "count")


def test_party_on_both_sides_asks_to_clarify() -> None:
    rows = [row("D-0001", customer_name_short=cell(EFF, 'ООО "Альфа"')),
            row("D-0002", contractor_name_short=cell(EFF, 'ООО "Альфа"'))]
    got = tq.resolve_party(party("Альфа"), rows, False)
    assert isinstance(got, tq.NonQuery) and got.kind == "clarify"
    assert "заказчик" in got.reason and "подрядчик" in got.reason
    assert "Альфа" not in got.reason


def test_party_on_both_sides_of_one_contract_asks_to_clarify() -> None:
    rows = [row("D-0001", customer_name_short=cell(EFF, 'ООО "Альфа"'),
                contractor_name_short=cell(EFF, 'ООО "Альфа"'))]
    assert isinstance(tq.resolve_party(party("Альфа"), rows, False), tq.NonQuery)


def test_party_on_no_side_stays_a_party_query() -> None:
    q = party("Гамма")
    got = tq.resolve_party(q, [row("D-0001"), row("D-0002")], False)
    assert got == q and isinstance(got, tq.TableQuery) and got.side is None


def test_side_chosen_by_considered_cells_only() -> None:
    rows = [row("D-0001", customer_name_short=cell(EFF, 'ООО "Альфа"')),
            row("D-0002", contractor_name_short=cell(UNREV, 'ООО "Альфа"'))]
    got = tq.resolve_party(party("Альфа"), rows, False)
    assert isinstance(got, tq.TableQuery) and got.side == "customer"
    both = tq.resolve_party(party("Альфа"), rows, True)
    assert isinstance(both, tq.NonQuery) and both.kind == "clarify"


@pytest.mark.parametrize("state", [CellState.NEEDS_REVIEW, CellState.REJECTED,
                                   CellState.NOT_FOUND, CellState.NO_EXTRACTION,
                                   CellState.CHECKS_STALE])
def test_cells_not_considered_never_choose_a_side(state: CellState) -> None:
    rows = [row("D-0001", customer_name_short=cell(EFF, 'ООО "Альфа"')),
            row("D-0002", contractor_name_short=cell(state, 'ООО "Альфа"'))]
    got = tq.resolve_party(party("Альфа"), rows, True)
    assert isinstance(got, tq.TableQuery) and got.side == "customer"


# --- execute (T009, research R-7) --------------------------------------------------
#
# Interface: `execute(query, rows, include_unreviewed) -> Result`;
# `Result(query, rows: tuple[ResultRow, ...], matched_names: tuple[str, ...],
#         excluded: dict[str, tuple[str, ...]], considered: int, total: int,
#         include_unreviewed: bool)`, `.count == len(rows)`;
# `ResultRow(row: DocRow, unreviewed: bool)` — `unreviewed` when the condition cell counted
# is `unreviewed`; `excluded` — state value of the condition cell → document ids, in id
# order; rows and matched names in document id order; matched names distinct.


def amounts(*pairs: tuple[str, CellState, str | None]) -> list[tq.DocRow]:
    return [row(doc, amount_with_vat=cell(state, value, f"{doc}/2.1"))
            for doc, state, value in pairs]


def ids(result: tq.Result) -> list[str]:
    return [item.row.document_id for item in result.rows]


def amount_query(op: str, value: str) -> tq.TableQuery:
    return ok(r(field="amount_with_vat", op=op, value=value))


@pytest.mark.parametrize(
    ("op", "expected"),
    [("gt", ["D-0003"]), ("ge", ["D-0002", "D-0003"]), ("lt", ["D-0001"]),
     ("le", ["D-0001", "D-0002"]), ("eq", ["D-0002"])],
)
def test_amount_comparisons_at_the_bound(op: str, expected: list[str]) -> None:
    rows = amounts(("D-0001", EFF, "999999.99"), ("D-0002", EFF, "1000000.00"),
                   ("D-0003", EFF, "1000000.01"))
    result = tq.execute(amount_query(op, "1 000 000"), rows, False)
    assert ids(result) == expected
    assert result.count == len(expected) and result.considered == 3 and result.total == 3


def test_amounts_compared_as_numbers_not_strings() -> None:
    rows = amounts(("D-0001", EFF, "900000.00"), ("D-0002", EFF, "12000000.00"))
    assert ids(tq.execute(amount_query("gt", "1000000"), rows, False)) == ["D-0002"]


def dates(*pairs: tuple[str, str]) -> list[tq.DocRow]:
    return [row(doc, contract_end_date=cell(EFF, value, f"{doc}/5.1")) for doc, value in pairs]


DATE_ROWS = dates(("D-0001", "2025-12-31"), ("D-0002", "2026-01-01"), ("D-0003", "2026-06-30"),
                  ("D-0004", "2026-12-31"), ("D-0005", "2027-01-01"))


@pytest.mark.parametrize(
    ("op", "value", "value_to", "expected"),
    [
        ("before", "2026-01-01", None, ["D-0001"]),
        ("after", "2026-12-31", None, ["D-0005"]),
        ("eq", "2026-06-30", None, ["D-0003"]),
        ("between", "2026-01-01", "2026-12-31", ["D-0002", "D-0003", "D-0004"]),
        ("eq", "this_year", None, ["D-0002", "D-0003", "D-0004"]),
        ("before", "this_year", None, ["D-0001"]),
        ("after", "this_year", None, ["D-0005"]),
    ],
)
def test_date_comparisons(op: str, value: str, value_to: str | None, expected: list[str]) -> None:
    q = ok(r(field="contract_end_date", op=op, value=value, value_to=value_to))
    assert ids(tq.execute(q, DATE_ROWS, False)) == expected


def test_contract_number_by_normalized_equality() -> None:
    rows = [row("D-0001", contract_number=cell(EFF, "К-21/2026")),
            row("D-0002", contract_number=cell(EFF, "К-21/2026-1")),
            row("D-0003", contract_number=cell(EFF, "к-21/2026"))]
    q = ok(r(field="contract_number", op="eq", value="№ К-21/2026"))
    assert ids(tq.execute(q, rows, False)) == ["D-0001"]


SPELLED_ALPHA = 'общество с ограниченной ответственностью "Альфа"'


def test_names_by_the_name_rule_with_matched_spellings() -> None:
    rows = [
        row("D-0003", contractor_name_short=cell(EFF, SPELLED_ALPHA)),
        row("D-0001", contractor_name_short=cell(EFF, 'ООО "Альфа"')),
        row("D-0002", contractor_name_short=cell(EFF, 'ООО "Альфа-Строй"')),
        row("D-0004", contractor_name_short=cell(EFF, 'ООО "Альфа"')),
    ]
    q = ok(r(field="contractor_name_short", op="eq", value="Альфа"))
    result = tq.execute(q, rows, False)
    assert ids(result) == ["D-0001", "D-0003", "D-0004"]
    assert result.matched_names == ('ООО "Альфа"', SPELLED_ALPHA)


def test_matched_names_empty_for_other_fields() -> None:
    result = tq.execute(amount_query("gt", "0"), amounts(("D-0001", EFF, "5.00")), False)
    assert result.matched_names == ()


ALL_STATES = [
    ("D-0001", CellState.EFFECTIVE, "2000000.00"),
    ("D-0002", CellState.UNREVIEWED, "2000000.00"),
    ("D-0003", CellState.NEEDS_REVIEW, None),
    ("D-0004", CellState.REJECTED, None),
    ("D-0005", CellState.NOT_FOUND, None),
    ("D-0006", CellState.NO_EXTRACTION, None),
    ("D-0007", CellState.CHECKS_STALE, None),
    ("D-0008", CellState.UNREVIEWED, "10.00"),
    ("D-0009", CellState.EFFECTIVE, "10.00"),
]


def test_only_effective_cells_are_considered() -> None:
    result = tq.execute(amount_query("gt", "1000000"), amounts(*ALL_STATES), False)
    assert ids(result) == ["D-0001"]
    assert result.considered == 2 and result.total == 9
    assert result.excluded == {
        "unreviewed": ("D-0002", "D-0008"),
        "needs_review": ("D-0003",),
        "rejected": ("D-0004",),
        "not_found": ("D-0005",),
        "no_extraction": ("D-0006",),
        "checks_stale": ("D-0007",),
    }
    assert not result.include_unreviewed
    assert [item.unreviewed for item in result.rows] == [False]


def test_include_unreviewed_counts_and_marks_unreviewed_cells() -> None:
    result = tq.execute(amount_query("gt", "1000000"), amounts(*ALL_STATES), True)
    assert ids(result) == ["D-0001", "D-0002"]
    assert [item.unreviewed for item in result.rows] == [False, True]
    assert result.considered == 4 and result.include_unreviewed
    assert "unreviewed" not in result.excluded
    assert result.excluded["rejected"] == ("D-0004",)
    assert result.excluded["needs_review"] == ("D-0003",)


def test_only_the_condition_field_decides() -> None:
    rows = [row("D-0001", amount_without_vat=cell(CellState.REJECTED),
                amount_with_vat=cell(EFF, "2000000.00"))]
    result = tq.execute(amount_query("gt", "1"), rows, False)
    assert ids(result) == ["D-0001"] and result.excluded == {}


def test_rows_in_document_id_order_whatever_the_input_order() -> None:
    rows = amounts(("D-0010", EFF, "5.00"), ("D-0002", EFF, "5.00"), ("D-0100", EFF, "5.00"),
                   ("D-0007", CellState.REJECTED, None), ("D-0003", CellState.REJECTED, None))
    result = tq.execute(amount_query("gt", "1"), rows, False)
    assert ids(result) == ["D-0002", "D-0010", "D-0100"]
    assert result.excluded == {"rejected": ("D-0003", "D-0007")}


def test_zero_rows_is_a_result() -> None:
    result = tq.execute(amount_query("gt", "1000000000"), amounts(("D-0001", EFF, "5.00")), False)
    assert result.count == 0 and result.rows == () and result.considered == 1


def test_same_input_gives_the_same_result() -> None:
    rows = amounts(*ALL_STATES)
    q = amount_query("ge", "10")
    assert tq.execute(q, rows, True) == tq.execute(q, list(reversed(rows)), True)


def test_count_and_list_give_the_same_result_but_the_action() -> None:
    rows = amounts(*ALL_STATES)
    a = tq.execute(ok(r(action="count", value="5")), rows, False)
    b = tq.execute(ok(r(action="list", value="5")), rows, False)
    assert (a.rows, a.excluded, a.considered) == (b.rows, b.excluded, b.considered)


def test_party_side_resolved_query_runs_on_its_side() -> None:
    rows = [row("D-0001", customer_name_short=cell(EFF, 'ООО "Альфа"')), row("D-0002")]
    q = tq.resolve_party(party("Альфа"), rows, False)
    assert isinstance(q, tq.TableQuery)
    result = tq.execute(q, rows, False)
    assert ids(result) == ["D-0001"] and result.query.side == "customer"
    assert result.matched_names == ('ООО "Альфа"',)


def test_party_with_no_side_counts_contracts_with_both_names_considered() -> None:
    rows = [
        row("D-0001"),
        row("D-0002", customer_name_short=cell(CellState.UNREVIEWED, 'ООО "Гамма"')),
        row("D-0003", contractor_name_short=cell(CellState.REJECTED)),
        row("D-0004", customer_name_short=cell(CellState.NOT_FOUND),
            contractor_name_short=cell(CellState.REJECTED)),
    ]
    q = party("Гамма")
    assert tq.resolve_party(q, rows, False) == q
    result = tq.execute(q, rows, False)
    assert result.count == 0 and result.considered == 1 and result.total == 4
    assert result.excluded == {"unreviewed": ("D-0002",), "rejected": ("D-0003",),
                               "not_found": ("D-0004",)}


# --- describe (T010, research R-8, contracts/cli.md) -------------------------------


@pytest.mark.parametrize(
    ("reply", "text"),
    [
        (r(field="contractor_name_short", op="eq", value="ООО «Альфа»"),
         'подрядчик — ООО "Альфа"'),
        (r(field="customer_name_short", op="eq", value="Бета"), "заказчик — Бета"),
        (r(field="party", op="eq", value="Гамма"), "заказчик или подрядчик — Гамма"),
        (r(field="contract_number", op="eq", value="№ К-21/2026"), "номер договора — К-21/2026"),
        (r(field="amount_with_vat", op="gt", value="1000000"),
         "цена с НДС больше 1 000 000,00 руб."),
        (r(field="amount_with_vat", op="ge", value="1500000"),
         "цена с НДС не меньше 1 500 000,00 руб."),
        (r(field="amount_without_vat", op="lt", value="999,50"),
         "цена без НДС меньше 999,50 руб."),
        (r(field="amount_without_vat", op="le", value="0"), "цена без НДС не больше 0,00 руб."),
        (r(field="amount_without_vat", op="eq", value="250000"),
         "цена без НДС равна 250 000,00 руб."),
        (r(field="contract_end_date", op="before", value="2026-06-01"),
         "дата окончания раньше 2026-06-01"),
        (r(field="contract_end_date", op="after", value="this_year"),
         "дата окончания позже 2026-12-31"),
        (r(field="contract_end_date", op="eq", value="2026-12-31"),
         "дата окончания — 2026-12-31"),
        (r(field="contract_end_date", op="eq", value="this_year"),
         "дата окончания с 2026-01-01 по 2026-12-31"),
        (r(field="contract_end_date", op="between", value="2026-01-01", value_to="2026-03-31"),
         "дата окончания с 2026-01-01 по 2026-03-31"),
    ],
)
def test_describe(reply: TableReply, text: str) -> None:
    assert tq.describe(ok(reply)) == text


def test_describe_names_the_side_chosen_by_the_table() -> None:
    rows = [row("D-0001", customer_name_short=cell(EFF, 'ООО "Альфа"'))]
    q = tq.resolve_party(party("Альфа"), rows, False)
    assert isinstance(q, tq.TableQuery)
    assert tq.describe(q) == "заказчик — Альфа (сторона выбрана по таблице)"
    rows = [row("D-0001", contractor_name_short=cell(EFF, 'ООО "Альфа"'))]
    q = tq.resolve_party(party("Альфа"), rows, False)
    assert isinstance(q, tq.TableQuery)
    assert tq.describe(q) == "подрядчик — Альфа (сторона выбрана по таблице)"
