from decimal import Decimal

import pytest

from app.money import money, quantity, quotation_to_decimal, quotation_to_quantity


def test_money_rounds_to_four_places():
    assert money("123.456789") == Decimal("123.4568")


def test_money_accepts_int():
    assert money(100) == Decimal("100.0000")


def test_money_rejects_float():
    with pytest.raises(TypeError):
        money(1.5)  # type: ignore[arg-type]


def test_quantity_keeps_eight_places():
    assert quantity("0.00000001") == Decimal("0.00000001")


def test_quotation_combines_units_and_nano():
    assert quotation_to_decimal(142, 500000000) == Decimal("142.5000")


def test_quotation_handles_negative_variation_margin():
    assert quotation_to_decimal(-3, -250000000) == Decimal("-3.2500")


def test_quotation_zero():
    assert quotation_to_decimal(0, 0) == Decimal("0.0000")


def test_money_rejects_bool():
    with pytest.raises(TypeError):
        money(True)  # type: ignore[arg-type]


def test_money_rejects_nan():
    with pytest.raises(ValueError):
        money("nan")


def test_money_rejects_inf():
    with pytest.raises(ValueError):
        money("inf")


def test_money_rejects_negative_inf():
    with pytest.raises(ValueError):
        money("-inf")


def test_quantity_rejects_nan():
    with pytest.raises(ValueError):
        quantity("nan")


def test_quotation_to_quantity_keeps_precision_finer_than_money():
    # money()+quantity() округлило бы это до 10.1235 ещё на денежном шаге;
    # quotation_to_quantity обязана сохранить все 8 знаков количества.
    assert quotation_to_quantity(10, 123456789) == Decimal("10.12345679")


def test_quotation_to_quantity_handles_negative_values():
    assert quotation_to_quantity(-3, -12345678) == Decimal("-3.01234568")


def test_quotation_to_quantity_zero():
    assert quotation_to_quantity(0, 0) == Decimal("0.00000000")
