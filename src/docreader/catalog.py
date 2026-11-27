"""The field catalog in code (feature 02, research R-3).

One `CatalogField` per field of `docs/field-catalog.md` («Основные поля»), 68 in all,
in the order of the catalog tables; `*_` rows are expanded to `customer_...` then
`contractor_...` right where the row stands. The document is the single source of
truth: `tests/unit/test_catalog.py` keeps this table equal to it (names, kinds, queues,
requisite lengths, choice variants), so a drift between the two fails a test.

`price_by_year` (kind `records`) is not compared automatically until its own
iteration (plan deviation 7); `free_text` and `list` fields are assessed by hand.

The four kinds shared with feature 05 (`identifier`, `name`, `amount`, `date`) have the
same string values as `docreader.fields.Kind`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from docreader.fields import PROTOTYPE_FIELDS


class CatalogKind(StrEnum):
    """Kind of a catalog field; the first four match `docreader.fields.Kind`."""

    IDENTIFIER = "identifier"
    REQUISITE = "requisite"
    DATE = "date"
    AMOUNT = "amount"
    PERCENT = "percent"
    NUMBER = "number"
    NAME = "name"
    CHOICE = "choice"
    RECORDS = "records"
    FREE_TEXT = "free_text"
    LIST = "list"


@dataclass(frozen=True)
class CatalogField:
    """One field of the catalog."""

    name: str
    label: str
    kind: CatalogKind
    queue: int
    group: str
    choices: tuple[str, ...] = ()
    requisite_length: int | None = None


def _f(
    name: str,
    label: str,
    kind: CatalogKind,
    queue: int,
    group: str,
    *,
    choices: tuple[str, ...] = (),
    requisite_length: int | None = None,
) -> CatalogField:
    return CatalogField(name, label, kind, queue, group, choices, requisite_length)


CATALOG: tuple[CatalogField, ...] = (
    _f("contract_number", "номер договора", CatalogKind.IDENTIFIER, 1, "Реквизиты договора"),
    _f("contract_title", "заголовок договора", CatalogKind.FREE_TEXT, 2, "Реквизиты договора"),
    _f(
        "contract_type",
        "вид договора",
        CatalogKind.CHOICE,
        1,
        "Реквизиты договора",
        choices=(
            "СМР",
            "ПИР",
            "иное",
        ),
    ),
    _f("signing_date", "дата подписания", CatalogKind.DATE, 1, "Реквизиты договора"),
    _f(
        "signing_date_source",
        "источник даты подписания",
        CatalogKind.CHOICE,
        1,
        "Реквизиты договора",
        choices=(
            "текст договора",
            "лист электронной подписи",
        ),
    ),
    _f("signing_place", "место подписания", CatalogKind.NAME, 2, "Реквизиты договора"),
    _f(
        "basis_document_kind",
        "вид основания заключения",
        CatalogKind.CHOICE,
        1,
        "Реквизиты договора",
        choices=(
            "протокол закупки",
            "генеральный договор",
            "иное",
        ),
    ),
    _f(
        "basis_document_number",
        "номер основания заключения",
        CatalogKind.IDENTIFIER,
        2,
        "Реквизиты договора",
    ),
    _f(
        "basis_document_date",
        "дата основания заключения",
        CatalogKind.DATE,
        2,
        "Реквизиты договора",
    ),
    _f("customer_name_full", "полное наименование заказчика", CatalogKind.NAME, 1, "Стороны"),
    _f("contractor_name_full", "полное наименование подрядчика", CatalogKind.NAME, 1, "Стороны"),
    _f("customer_name_short", "заказчик", CatalogKind.NAME, 1, "Стороны"),
    _f("contractor_name_short", "подрядчик", CatalogKind.NAME, 1, "Стороны"),
    _f("customer_branch", "филиал заказчика", CatalogKind.NAME, 2, "Стороны"),
    _f("contractor_branch", "филиал подрядчика", CatalogKind.NAME, 2, "Стороны"),
    _f("customer_inn", "ИНН заказчика", CatalogKind.REQUISITE, 1, "Стороны", requisite_length=10),
    _f(
        "contractor_inn", "ИНН подрядчика", CatalogKind.REQUISITE, 1, "Стороны", requisite_length=10
    ),
    _f("customer_kpp", "КПП заказчика", CatalogKind.REQUISITE, 2, "Стороны", requisite_length=9),
    _f("contractor_kpp", "КПП подрядчика", CatalogKind.REQUISITE, 2, "Стороны", requisite_length=9),
    _f("customer_signatory_name", "подписант заказчика", CatalogKind.NAME, 1, "Стороны"),
    _f("contractor_signatory_name", "подписант подрядчика", CatalogKind.NAME, 1, "Стороны"),
    _f(
        "customer_signatory_position",
        "должность подписанта заказчика",
        CatalogKind.NAME,
        2,
        "Стороны",
    ),
    _f(
        "contractor_signatory_position",
        "должность подписанта подрядчика",
        CatalogKind.NAME,
        2,
        "Стороны",
    ),
    _f(
        "customer_authority_kind",
        "основание полномочий заказчика",
        CatalogKind.CHOICE,
        1,
        "Стороны",
        choices=(
            "устав",
            "доверенность",
            "машиночитаемая доверенность",
            "иное",
        ),
    ),
    _f(
        "contractor_authority_kind",
        "основание полномочий подрядчика",
        CatalogKind.CHOICE,
        1,
        "Стороны",
        choices=(
            "устав",
            "доверенность",
            "машиночитаемая доверенность",
            "иное",
        ),
    ),
    _f(
        "customer_authority_number",
        "номер доверенности заказчика",
        CatalogKind.IDENTIFIER,
        2,
        "Стороны",
    ),
    _f(
        "contractor_authority_number",
        "номер доверенности подрядчика",
        CatalogKind.IDENTIFIER,
        2,
        "Стороны",
    ),
    _f("customer_authority_date", "дата доверенности заказчика", CatalogKind.DATE, 2, "Стороны"),
    _f("contractor_authority_date", "дата доверенности подрядчика", CatalogKind.DATE, 2, "Стороны"),
    _f("subject_summary", "предмет договора", CatalogKind.FREE_TEXT, 1, "Предмет"),
    _f("work_object", "объект работ", CatalogKind.FREE_TEXT, 1, "Предмет"),
    _f("business_code", "бизнес-код объекта", CatalogKind.IDENTIFIER, 1, "Предмет"),
    _f("investment_project", "инвестиционный проект", CatalogKind.FREE_TEXT, 2, "Предмет"),
    _f("appendices", "перечень приложений", CatalogKind.LIST, 2, "Предмет"),
    _f(
        "subcontracting_terms",
        "привлечение третьих лиц",
        CatalogKind.CHOICE,
        2,
        "Предмет",
        choices=(
            "запрещено",
            "с согласия заказчика",
            "разрешено",
            "не указано",
        ),
    ),
    _f(
        "price_type",
        "вид цены",
        CatalogKind.CHOICE,
        2,
        "Цена",
        choices=(
            "твёрдая",
            "приблизительная",
            "предельная",
            "не указано",
        ),
    ),
    _f("amount_without_vat", "цена без НДС", CatalogKind.AMOUNT, 1, "Цена"),
    _f("vat_rate", "ставка НДС", CatalogKind.PERCENT, 1, "Цена"),
    _f("vat_amount", "сумма НДС", CatalogKind.AMOUNT, 1, "Цена"),
    _f("amount_with_vat", "цена с НДС", CatalogKind.AMOUNT, 1, "Цена"),
    _f(
        "currency",
        "валюта",
        CatalogKind.CHOICE,
        1,
        "Цена",
        choices=(
            "RUB",
            "иное",
        ),
    ),
    _f("price_by_year", "цена по годам", CatalogKind.RECORDS, 2, "Цена"),
    _f("payment_terms", "порядок оплаты", CatalogKind.FREE_TEXT, 1, "Оплата"),
    _f("payment_share", "доля оплаты работ", CatalogKind.PERCENT, 2, "Оплата"),
    _f("payment_days", "срок оплаты, дней", CatalogKind.NUMBER, 1, "Оплата"),
    _f(
        "payment_day_kind",
        "вид дней оплаты",
        CatalogKind.CHOICE,
        1,
        "Оплата",
        choices=(
            "рабочих",
            "календарных",
        ),
    ),
    _f("advance_share", "доля аванса", CatalogKind.PERCENT, 1, "Оплата"),
    _f("retention_share", "гарантийное удержание", CatalogKind.PERCENT, 1, "Оплата"),
    _f(
        "retention_conditional",
        "удержание по условию",
        CatalogKind.CHOICE,
        2,
        "Оплата",
        choices=(
            "да",
            "нет",
        ),
    ),
    _f("retention_payout_days", "срок выплаты удержания", CatalogKind.NUMBER, 2, "Оплата"),
    _f("contract_term_terms", "срок действия договора", CatalogKind.FREE_TEXT, 2, "Сроки"),
    _f("contract_end_date", "дата окончания", CatalogKind.DATE, 1, "Сроки"),
    _f("work_period_terms", "период выполнения работ", CatalogKind.FREE_TEXT, 2, "Сроки"),
    _f("work_end_date", "срок окончания работ", CatalogKind.DATE, 1, "Сроки"),
    _f("warranty_terms", "гарантийные сроки", CatalogKind.FREE_TEXT, 2, "Гарантия и обеспечение"),
    _f(
        "warranty_works_months",
        "гарантия на работы, месяцев",
        CatalogKind.NUMBER,
        1,
        "Гарантия и обеспечение",
    ),
    _f(
        "warranty_equipment_months",
        "гарантия на оборудование, месяцев",
        CatalogKind.NUMBER,
        2,
        "Гарантия и обеспечение",
    ),
    _f(
        "performance_security_kind",
        "вид обеспечения исполнения",
        CatalogKind.CHOICE,
        2,
        "Гарантия и обеспечение",
        choices=(
            "независимая гарантия",
            "денежные средства",
            "не предусмотрено",
            "иное",
        ),
    ),
    _f(
        "performance_security_amount",
        "размер обеспечения исполнения",
        CatalogKind.AMOUNT,
        1,
        "Гарантия и обеспечение",
    ),
    _f(
        "delay_penalty_terms",
        "ответственность за просрочку",
        CatalogKind.FREE_TEXT,
        1,
        "Ответственность",
    ),
    _f("delay_penalty_rate", "пеня подрядчика", CatalogKind.PERCENT, 1, "Ответственность"),
    _f("delay_penalty_cap", "предел пени", CatalogKind.PERCENT, 2, "Ответственность"),
    _f(
        "final_deadline_fine_share",
        "штраф за конечный срок",
        CatalogKind.PERCENT,
        2,
        "Ответственность",
    ),
    _f(
        "customer_late_payment_rate",
        "пеня заказчика за просрочку оплаты",
        CatalogKind.PERCENT,
        2,
        "Ответственность",
    ),
    _f("governing_law", "применимое право", CatalogKind.NAME, 2, "Право и споры"),
    _f("dispute_venue", "суд для споров", CatalogKind.NAME, 1, "Право и споры"),
    _f("claim_response_days", "срок ответа на претензию", CatalogKind.NUMBER, 2, "Право и споры"),
    _f("termination_terms", "основания расторжения", CatalogKind.FREE_TEXT, 2, "Право и споры"),
)

ALL: tuple[CatalogField, ...] = CATALOG

_BY_NAME: dict[str, CatalogField] = {f.name: f for f in CATALOG}

PROTOTYPE: tuple[CatalogField, ...] = tuple(_BY_NAME[s.name] for s in PROTOTYPE_FIELDS)

QUEUE1: tuple[CatalogField, ...] = PROTOTYPE + tuple(
    f for f in CATALOG if f.queue == 1 and f not in PROTOTYPE
)

_NOT_AUTO_COMPARED = frozenset({CatalogKind.FREE_TEXT, CatalogKind.LIST, CatalogKind.RECORDS})


def field(name: str) -> CatalogField:
    """The catalog field with this name; KeyError for an unknown name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"unknown field: {name}") from None


def auto_compared(field: CatalogField) -> bool:
    """Whether the program compares the value itself (not by hand)."""
    return field.kind not in _NOT_AUTO_COMPARED
