"""The field catalog in code equals docs/field-catalog.md (feature 02, T004, research R-3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from docreader import catalog
from docreader.catalog import CatalogKind
from docreader.fields import PROTOTYPE_FIELDS

DOC = Path(__file__).resolve().parents[2] / "docs" / "field-catalog.md"

KIND_WORDS = {
    "идентификатор": CatalogKind.IDENTIFIER,
    "ИНН": CatalogKind.REQUISITE,
    "КПП": CatalogKind.REQUISITE,
    "ОГРН": CatalogKind.REQUISITE,
    "БИК": CatalogKind.REQUISITE,
    "счёт": CatalogKind.REQUISITE,
    "дата": CatalogKind.DATE,
    "сумма": CatalogKind.AMOUNT,
    "процент": CatalogKind.PERCENT,
    "число": CatalogKind.NUMBER,
    "наименование": CatalogKind.NAME,
    "выбор из списка": CatalogKind.CHOICE,
    "список записей": CatalogKind.RECORDS,
    "свободный текст": CatalogKind.FREE_TEXT,
    "список": CatalogKind.LIST,
}
# «Валюта (`RUB`, иное)»: «иное» is written without backticks in the catalog
EXTRA_CHOICES = {"currency": ("иное",)}
REQUISITE_LENGTH = {"ИНН": 10, "КПП": 9, "ОГРН": 13, "БИК": 9, "счёт": 20}


def _main_fields_section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("## Основные поля")
    end = text.index("### Итог", start)
    return text[start:end]


def doc_rows() -> list[tuple[str, str, str, str]]:
    """(name, description, kind word, queue) of every table row, `*_` expanded."""
    rows = []
    for line in _main_fields_section().splitlines():
        m = re.match(r"^\| `([^`]+)` \| ([^|]+) \| ([^|]+) \| ([12]) \|", line)
        if not m:
            continue
        name, what, kind, queue = (g.strip() for g in m.groups())
        if name.startswith("*_"):
            rows.append((f"customer_{name[2:]}", what, kind, queue))
            rows.append((f"contractor_{name[2:]}", what, kind, queue))
        else:
            rows.append((name, what, kind, queue))
    return rows


def test_counts_match_catalog_summary() -> None:
    assert len(catalog.CATALOG) == 68
    assert len(catalog.QUEUE1) == 35
    assert len(catalog.ALL) == 68
    manual = [f for f in catalog.CATALOG if f.kind in (CatalogKind.FREE_TEXT, CatalogKind.LIST)]
    assert len(manual) == 11


def test_every_field_equals_the_document() -> None:
    rows = doc_rows()
    assert len(rows) == 68
    assert [f.name for f in catalog.CATALOG] == [r[0] for r in rows]
    for (name, _what, kind, queue), f in zip(rows, catalog.CATALOG, strict=True):
        assert f.kind is KIND_WORDS[kind], name
        assert f.queue == int(queue), name
        if kind in REQUISITE_LENGTH:
            assert f.requisite_length == REQUISITE_LENGTH[kind], name
        else:
            assert f.requisite_length is None, name


def _choice_names() -> list[str]:
    return [r[0] for r in doc_rows() if r[2] == "выбор из списка"]


@pytest.mark.parametrize("name", _choice_names())
def test_choice_variants_equal_the_document(name: str) -> None:
    described = next(r[1] for r in doc_rows() if r[0] == name)
    variants = tuple(re.findall(r"`([^`]+)`", described)) + EXTRA_CHOICES.get(name, ())
    f = catalog.field(name)
    assert f.kind is CatalogKind.CHOICE
    assert f.choices == variants
    assert f.choices, name


def test_prototype_equals_extraction_fields() -> None:
    assert [(f.name, f.label) for f in catalog.PROTOTYPE] == [
        (f.name, f.label) for f in PROTOTYPE_FIELDS
    ]
    kinds = {f.name: f.kind.value for f in PROTOTYPE_FIELDS}
    for f in catalog.PROTOTYPE:
        assert f.kind.value == kinds[f.name]


def test_queue1_starts_with_prototype_and_has_queue1_fields_only() -> None:
    names = [f.name for f in catalog.QUEUE1]
    assert names[:6] == [f.name for f in PROTOTYPE_FIELDS]
    assert all(f.queue == 1 for f in catalog.QUEUE1)
    assert sorted(names) == sorted(f.name for f in catalog.CATALOG if f.queue == 1)


def test_auto_compared() -> None:
    auto = [f for f in catalog.CATALOG if catalog.auto_compared(f)]
    # 57 by the catalog summary; `price_by_year` (records) is manual until its iteration
    assert len(auto) == 56
    assert not catalog.auto_compared(catalog.field("price_by_year"))
    assert catalog.auto_compared(catalog.field("contract_number"))


def test_labels_are_russian_and_unique() -> None:
    labels = [f.label for f in catalog.CATALOG]
    assert all(label and re.search("[а-яё]", label) for label in labels)
    assert len(set(labels)) == len(labels)


def test_unknown_field() -> None:
    with pytest.raises(KeyError):
        catalog.field("x")
