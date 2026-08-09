from decimal import Decimal

from app.connectors.tbank.quotation import to_money, to_quantity


def test_to_money_converts_units_and_nano():
    assert to_money({"currency": "rub", "units": "142", "nano": 500000000}) == Decimal("142.5000")


def test_to_money_defaults_to_zero_when_missing():
    assert to_money(None) == Decimal("0.0000")
    assert to_money({}) == Decimal("0.0000")


def test_to_money_defaults_to_zero_when_malformed():
    assert to_money({"currency": "rub"}) == Decimal("0.0000")
    assert to_money({"units": "not-a-number", "nano": 0}) == Decimal("0.0000")


def test_to_quantity_keeps_full_precision():
    assert to_quantity({"units": "10", "nano": 123456789}) == Decimal("10.12345679")


def test_to_quantity_returns_none_when_missing():
    assert to_quantity(None) is None
    assert to_quantity({}) is None


def test_to_quantity_returns_none_when_malformed():
    assert to_quantity({"units": "10"}) is None
    assert to_quantity({"units": "ten", "nano": 0}) is None
