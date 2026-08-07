from datetime import datetime, timezone
from decimal import Decimal

from app.positions.engine import LedgerEntry, fold
from app.models import OperationType

D = Decimal


def at(day: int) -> datetime:
    return datetime(2026, 3, day, 10, 0, tzinfo=timezone.utc)


def entry(op_type, day, qty="0", price="0", amount="0", fee="0", instrument_id=1):
    return LedgerEntry(
        op_type=op_type, executed_at=at(day), instrument_id=instrument_id,
        quantity=D(qty), price=D(price), amount=D(amount), fee=D(fee),
    )


def test_single_buy_creates_position():
    result = fold([entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000")])
    position = result.positions[1]
    assert position.quantity == D("10")
    assert position.average_price == D("100.0000")


def test_average_price_is_weighted():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="30", price="200", amount="-6000"),
    ])
    assert result.positions[1].average_price == D("175.0000")


def test_partial_sale_consumes_oldest_lot_first():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="10", price="200", amount="-2000"),
        entry(OperationType.SELL, 3, qty="10", price="300", amount="3000"),
    ])
    position = result.positions[1]
    assert position.quantity == D("10")
    assert position.average_price == D("200.0000")

    sale = result.realized[0]
    assert sale.cost == D("1000.0000")
    assert sale.proceeds == D("3000.0000")
    assert sale.opened_at == at(1)


def test_sale_splitting_a_lot_leaves_remainder():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.SELL, 2, qty="4", price="150", amount="600"),
    ])
    position = result.positions[1]
    assert position.quantity == D("6")
    assert position.lots[0].quantity_left == D("6")
    assert result.realized[0].cost == D("400.0000")


def test_full_exit_leaves_zero_position():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.SELL, 2, qty="10", price="120", amount="1200"),
    ])
    assert result.positions[1].quantity == D("0")
    assert result.positions[1].lots == []


def test_dividend_does_not_change_quantity_but_changes_cash():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.DIVIDEND, 5, amount="340.50"),
    ])
    assert result.positions[1].quantity == D("10")
    assert result.cash["RUB"] == D("-659.5000")


def test_redemption_closes_bond_position():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="1000", amount="-10000"),
        entry(OperationType.REDEMPTION, 9, qty="10", price="1000", amount="10000"),
    ])
    assert result.positions[1].quantity == D("0")


def test_deposit_only_affects_cash():
    result = fold([entry(OperationType.DEPOSIT, 1, amount="50000", instrument_id=None)])
    assert result.positions == {}
    assert result.cash["RUB"] == D("50000.0000")


def test_fee_reduces_cash():
    result = fold([entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000", fee="5")])
    assert result.cash["RUB"] == D("-1005.0000")


def test_selling_more_than_owned_does_not_go_negative():
    result = fold([
        entry(OperationType.BUY, 1, qty="5", price="100", amount="-500"),
        entry(OperationType.SELL, 2, qty="8", price="150", amount="1200"),
    ])
    assert result.positions[1].quantity == D("0")
    assert result.realized[0].quantity == D("5")


def test_operations_are_sorted_by_time_regardless_of_input_order():
    unsorted_entries = [
        entry(OperationType.SELL, 3, qty="10", price="300", amount="3000"),
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="10", price="200", amount="-2000"),
    ]
    result = fold(unsorted_entries)
    assert result.realized[0].cost == D("1000.0000")
