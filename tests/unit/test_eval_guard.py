"""The output guard helper itself (feature 02, T013)."""

from __future__ import annotations

import pytest

from tests.eval_guard import assert_no_values


def test_clean_output_passes() -> None:
    out = "Сравнение полей: запись 3\n  D-0001 amount_with_vat неверно\n  пар 12: верно 10"
    assert_no_values(out, ["1 440 000 рублей 00 копеек", "ООО «Альфа»"])


def test_value_in_output_fails() -> None:
    with pytest.raises(AssertionError, match="contract content"):
        assert_no_values("значение: ООО «Альфа»", ["ООО «Альфа»"])


@pytest.mark.parametrize(
    "shown", ['ООО "Альфа"', "ооо «альфа»", "ООО  «Альфа»"]
)
def test_comparison_form_is_caught(shown: str) -> None:
    with pytest.raises(AssertionError):
        assert_no_values(f"x {shown} y", ["ООО «Альфа»"])


def test_yo_is_folded() -> None:
    with pytest.raises(AssertionError):
        assert_no_values("Какой счет оплаты?", ["Какой счёт оплаты?"])


def test_normalized_amount_is_a_secret() -> None:
    with pytest.raises(AssertionError):
        assert_no_values("x 1200000.00 y", ["1200000.00"])


@pytest.mark.parametrize("secret", ["2027", "RUB", "да", "D-0001", "D-0001/2.1",
                                    "contract_number"])
def test_ids_names_and_numbers_are_not_secrets(secret: str) -> None:
    assert_no_values(f"line with {secret} in it", [secret])
