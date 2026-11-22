"""The prototype fields of field extraction and their kinds and results (feature 05).

Research R-6 and R-15 of specs/005-field-extraction: the six fields of the end-to-end
prototype, in catalog order. `Result` must equal the CHECK on `field_value.result` in
`0005_extraction.sql` (tests/unit/test_fields.py checks it); the field names must equal
the CHECK on `field_value.field`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    """How a field's value is recognised and normalised."""

    IDENTIFIER = "identifier"
    NAME = "name"
    AMOUNT = "amount"
    DATE = "date"


class Result(StrEnum):
    """Outcome of extracting one field of one document."""

    FOUND = "found"
    NOT_FOUND = "not_found"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass(frozen=True)
class FieldSpec:
    """One field: its name in the schema, its label in Russian and its kind."""

    name: str
    label: str
    kind: Kind


PROTOTYPE_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("contract_number", "номер договора", Kind.IDENTIFIER),
    FieldSpec("customer_name_short", "заказчик", Kind.NAME),
    FieldSpec("contractor_name_short", "подрядчик", Kind.NAME),
    FieldSpec("amount_without_vat", "цена без НДС", Kind.AMOUNT),
    FieldSpec("amount_with_vat", "цена с НДС", Kind.AMOUNT),
    FieldSpec("contract_end_date", "дата окончания", Kind.DATE),
)

FIELD_NAMES: tuple[str, ...] = tuple(field.name for field in PROTOTYPE_FIELDS)

_BY_NAME: dict[str, FieldSpec] = {field.name: field for field in PROTOTYPE_FIELDS}


def spec(name: str) -> FieldSpec:
    """The prototype field with this name; KeyError for an unknown name."""
    try:
        return _BY_NAME[name]
    except KeyError:
        raise KeyError(f"unknown field: {name}") from None
