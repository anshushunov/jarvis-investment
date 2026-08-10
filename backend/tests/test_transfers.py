"""Ввод и вывод бумаг: количество двигают, себестоимости не несут.

Живой случай, ради которого это делается: 19.12.2024 на счёт «Инвестиционный»
пришли 351 бумага РусАгро операцией OPERATION_TYPE_INPUT_SECURITIES. Она
попадала в OperationType.OTHER, движок её не считал движением количества, и
сверка показывала 209 против 560 у брокера.
"""

from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.tbank.mapper import map_operation
from app.models import OperationType
from app.positions.engine import LedgerEntry, fold


def _entry(op_type: OperationType, quantity: str, price: str = "0",
           day: int = 1) -> LedgerEntry:
    return LedgerEntry(
        op_type=op_type,
        executed_at=datetime(2026, 1, day, tzinfo=timezone.utc),
        instrument_id=1,
        quantity=Decimal(quantity),
        price=Decimal(price),
        amount=Decimal("0"),
        fee=Decimal("0"),
    )


def test_input_securities_maps_to_transfer_in():
    operation = {
        "id": "1", "state": "OPERATION_STATE_EXECUTED",
        "type": "OPERATION_TYPE_INPUT_SECURITIES",
        "date": "2024-12-19T10:00:00Z", "quantityDone": "351",
        "payment": {"currency": "rub", "units": "0", "nano": 0},
    }

    result = map_operation(operation, None)

    assert result.op_type is OperationType.TRANSFER_IN
    assert result.quantity == Decimal("351")


def test_transfer_in_increases_quantity_with_unknown_cost():
    result = fold([_entry(OperationType.TRANSFER_IN, "351")])

    position = result.positions[1]
    assert position.quantity == Decimal("351")
    assert position.cost_basis_known is False


def test_transfer_in_alongside_purchase_marks_whole_position_unknown():
    result = fold([
        _entry(OperationType.BUY, "209", price="100", day=1),
        _entry(OperationType.TRANSFER_IN, "351", day=2),
    ])

    position = result.positions[1]
    assert position.quantity == Decimal("560")
    assert position.cost_basis_known is False


def test_transfer_out_reduces_quantity_without_realized_sale():
    result = fold([
        _entry(OperationType.BUY, "100", price="50", day=1),
        _entry(OperationType.TRANSFER_OUT, "40", day=2),
    ])

    assert result.positions[1].quantity == Decimal("60")
    assert result.realized == []
    # Себестоимость оставшихся не поехала: вывод не трогает цену партии.
    assert result.positions[1].average_price == Decimal("50")


def test_purchase_only_position_keeps_cost_known():
    result = fold([_entry(OperationType.BUY, "10", price="7")])

    assert result.positions[1].cost_basis_known is True


def test_transfer_in_closing_a_short_position_does_not_realize_fabricated_profit():
    """Продажа без остатка открывает короткую позицию (см. test_positions_engine.py:
    test_selling_more_than_owned_opens_a_short_for_the_excess); закрывающий её
    TRANSFER_IN идёт без цены, и если считать его как обычную покупку, движок
    записал бы в realized выручку от продажи против нулевой себестоимости —
    сфабрикованную прибыль из воздуха, которая испортила бы налоговую базу.
    Ввод бумаг так же не несёт финансового результата, как и вывод."""
    result = fold([
        _entry(OperationType.SELL, "100", price="50", day=1),
        _entry(OperationType.TRANSFER_IN, "100", day=2),
    ])

    assert result.realized == []
    assert result.positions[1].quantity == Decimal("0")
