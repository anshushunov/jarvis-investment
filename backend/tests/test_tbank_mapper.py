from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.base import BrokerInstrument
from app.connectors.tbank.mapper import map_operation
from app.models import OperationType


def op(**overrides) -> dict:
    """Строит операцию в форме, которую реально отдаёт REST-шлюз T-Invest API
    (OperationsService/GetOperationsByCursor): суммы — объекты {currency, units, nano}
    с units-строкой, quantity — строка, перечисления — строки, тип операции — в
    поле "type" (не "operationType" — так было только у устаревшего
    одностраничного GetOperations)."""
    defaults = {
        "id": "op-1",
        "type": "OPERATION_TYPE_BUY",
        "date": "2026-03-12T10:30:00Z",
        "figi": "BBG004730N88",
        "quantity": "35",
        "price": {"currency": "rub", "units": "142", "nano": 500000000},
        "payment": {"currency": "rub", "units": "-4987", "nano": -500000000},
        "currency": "rub",
        "state": "OPERATION_STATE_EXECUTED",
    }
    defaults.update(overrides)
    return defaults


SBER = BrokerInstrument(isin="RU0009029540", ticker="SBER", kind="share", name="Сбер Банк")
OFZ = BrokerInstrument(isin="RU000A101234", ticker="OFZ", kind="bond", name="ОФЗ 26238")


def test_buy_maps_to_buy_with_positive_quantity():
    result = map_operation(op(), SBER)
    assert result.op_type == OperationType.BUY
    assert result.quantity == Decimal("35")
    assert result.price == Decimal("142.5000")
    assert result.amount == Decimal("-4987.5000")
    assert result.external_id == "op-1"
    assert result.executed_at == datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc)


def test_sell_maps_to_sell():
    result = map_operation(
        op(type="OPERATION_TYPE_SELL", payment={"currency": "rub", "units": "4987", "nano": 500000000}),
        SBER,
    )
    assert result.op_type == OperationType.SELL
    assert result.amount == Decimal("4987.5000")


def test_dividend_has_no_quantity():
    result = map_operation(
        op(
            type="OPERATION_TYPE_DIVIDEND",
            quantity="0",
            price={"currency": "rub", "units": "0", "nano": 0},
            payment={"currency": "rub", "units": "340", "nano": 500000000},
        ),
        SBER,
    )
    assert result.op_type == OperationType.DIVIDEND
    assert result.quantity == Decimal("0")
    assert result.amount == Decimal("340.5000")


def test_coupon_maps_to_coupon():
    result = map_operation(
        op(type="OPERATION_TYPE_COUPON", payment={"currency": "rub", "units": "41", "nano": 320000000}),
        OFZ,
    )
    assert result.op_type == OperationType.COUPON


def test_broker_fee_maps_to_fee():
    result = map_operation(
        op(type="OPERATION_TYPE_BROKER_FEE", payment={"currency": "rub", "units": "-1", "nano": -496300000}),
        None,
    )
    assert result.op_type == OperationType.FEE
    assert result.isin is None


def test_input_maps_to_deposit():
    result = map_operation(
        op(
            type="OPERATION_TYPE_INPUT",
            payment={"currency": "rub", "units": "100000", "nano": 0},
            figi="",
        ),
        None,
    )
    assert result.op_type == OperationType.DEPOSIT


def test_unknown_type_maps_to_other_and_keeps_payload():
    result = map_operation(op(type="OPERATION_TYPE_SOMETHING_NEW"), None)
    assert result.op_type == OperationType.OTHER
    assert result.payload["operation_type"] == "OPERATION_TYPE_SOMETHING_NEW"


def test_unexecuted_operation_is_skipped():
    assert map_operation(op(state="OPERATION_STATE_CANCELED"), None) is None


def test_payload_carries_instrument_kind_and_name():
    """Вид и название — единственный канал от коннектора к доменному резолверу
    инструментов: он видит на входе только RawOperation."""
    result = map_operation(op(), OFZ)
    assert result.payload["instrument_kind"] == "bond"
    assert result.payload["instrument_name"] == "ОФЗ 26238"


def test_payload_has_no_instrument_keys_for_cash_operation():
    """Денежная операция без инструмента не должна класть в payload пустые
    ключи — резолвер по ней всё равно ничего не создаст (isin=None)."""
    result = map_operation(op(type="OPERATION_TYPE_INPUT", figi=""), None)
    assert "instrument_kind" not in result.payload
    assert "instrument_name" not in result.payload
