"""The replacement rule and the version of the gold set (feature 02, T012, research R-5, R-6)."""

from __future__ import annotations

from docreader.gold import (
    CellValue,
    GoldPath,
    GoldState,
    LoadKind,
    ParsedGold,
    StoredGold,
    diff,
    gold_sha256,
)

A = ("D-0001", "contract_number")
B = ("D-0001", "amount_with_vat")
C = ("D-0002", "contract_number")
OUTSIDE = ("D-0003", "contract_number")


def value(v: str, path: GoldPath = GoldPath.TEMPLATE) -> CellValue:
    return CellValue(GoldState.VALUE, (v,), (v,), path)


def stored(v: str, kind: LoadKind = LoadKind.TEMPLATE) -> StoredGold:
    path = GoldPath.TEMPLATE if kind is LoadKind.TEMPLATE else GoldPath.AGREE
    return StoredGold(value(v, path), kind)


def parsed(values: dict, coverage: set, kind: LoadKind = LoadKind.TEMPLATE) -> ParsedGold:  # type: ignore[type-arg]
    return ParsedGold(kind, frozenset(coverage), values, [], [])


def test_added_changed_removed_same() -> None:
    current = {A: stored("1"), B: stored("2"), C: stored("3"), OUTSIDE: stored("9")}
    new = parsed({A: value("1"), B: value("22"), ("D-0002", "amount_with_vat"): value("4")},
                 {A, B, C, ("D-0002", "amount_with_vat")})
    d = diff(current, new)
    assert d.same == [A]
    assert d.changed == [B]
    assert d.removed == [C]
    assert d.added == [("D-0002", "amount_with_vat")]
    assert OUTSIDE not in d.same + d.changed + d.removed + d.added


def test_outside_coverage_is_never_touched() -> None:
    d = diff({OUTSIDE: stored("9")}, parsed({}, {A}))
    assert (d.added, d.changed, d.removed, d.same) == ([], [], [], [])


def test_absent_versus_value_is_a_change() -> None:
    absent = CellValue(GoldState.ABSENT, (), (), GoldPath.TEMPLATE)
    d = diff({A: stored("1")}, parsed({A: absent}, {A}))
    assert d.changed == [A]


def test_type_error_that_clears_a_value_is_removed() -> None:
    # the cell had a value; now it holds a value of the wrong kind → unlabeled → removed
    d = diff({A: stored("1")}, parsed({}, {A}))
    assert d.removed == [A]
    assert d.needs_confirmation


def test_no_removal_needs_no_confirmation() -> None:
    assert not diff({}, parsed({A: value("1")}, {A})).needs_confirmation


def test_pairs_from_the_other_file_kind_are_counted() -> None:
    current = {A: stored("1", LoadKind.REVIEW), B: stored("2")}
    d = diff(current, parsed({A: value("1"), B: value("2")}, {A, B}))
    assert d.other_kind == [A]


def test_same_value_with_another_path_is_same() -> None:
    d = diff({A: stored("1", LoadKind.REVIEW)},
             parsed({A: value("1", GoldPath.CONFIRMED)}, {A}, LoadKind.REVIEW))
    assert d.same == [A]


def test_version_is_stable_to_row_order() -> None:
    r1 = ("D-0001", "contract_number", "value", ("1",))
    r2 = ("D-0002", "contract_number", "absent", ())
    assert gold_sha256([r1, r2]) == gold_sha256([r2, r1])
    assert len(gold_sha256([r1])) == 64


def test_version_changes_with_content() -> None:
    r1 = ("D-0001", "contract_number", "value", ("1",))
    assert gold_sha256([r1]) != gold_sha256([("D-0001", "contract_number", "value", ("2",))])
    assert gold_sha256([r1]) != gold_sha256([])


def test_version_does_not_depend_on_variant_text_split() -> None:
    # («a», «b») must not equal («a b»,) or («ab»,)
    assert gold_sha256([("D-0001", "f", "value", ("a", "b"))]) != gold_sha256(
        [("D-0001", "f", "value", ("a b",))]
    )
