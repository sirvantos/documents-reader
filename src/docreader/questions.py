"""Gold questions (feature 02): kinds and origins (research R-11).

The enums equal the CHECK constraints of `0007_evaluation.sql`.
"""

from __future__ import annotations

from enum import StrEnum


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
