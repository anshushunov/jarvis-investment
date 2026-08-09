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


def test_partial_bond_repayment_maps_to_amortization():
    """Частичное погашение — это выплата части номинала, количество бумаг при
    нём не меняется. Живой пример: 45 облигаций РЕСО-Лизинг, выплата 11250 ₽
    (по 250 на бумагу), после чего цена упала с ~750 до ~500 — бумаг осталось
    столько же. Считать это уменьшением позиции нельзя."""
    result = map_operation(
        op(type="OPERATION_TYPE_BOND_REPAYMENT", quantity="0",
           price={"currency": "rub", "units": "0", "nano": 0},
           payment={"currency": "rub", "units": "11250", "nano": 0}),
        OFZ,
    )
    assert result.op_type == OperationType.AMORTIZATION


def test_full_bond_repayment_maps_to_redemption():
    result = map_operation(
        op(type="OPERATION_TYPE_BOND_REPAYMENT_FULL", quantity="0",
           price={"currency": "rub", "units": "0", "nano": 0},
           payment={"currency": "rub", "units": "124000", "nano": 0}),
        OFZ,
    )
    assert result.op_type == OperationType.REDEMPTION
    # Количество брокер по погашению не присылает вовсе — позицию закрывает движок.
    assert result.quantity == Decimal("0")


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


def test_partially_filled_order_takes_executed_quantity():
    """Заявка, исполнившаяся частично и снятая, приходит со state=EXECUTED, но с
    quantity заявки, а не сделки. В журнал обязано попасть исполненное количество:
    иначе продажи оказываются больше реальных, движок позиций отбрасывает излишек
    и на счёте остаётся фантомный остаток бумаги, которой давно нет.

    Числа — из живого ответа брокера по продаже ELMT 30.05.2024 (операция
    610632231510): заявка на 249000, исполнено 3000, остальное снято по запросу
    клиента; payment 670.86 ₽ при цене 0.2236 ₽ подтверждает именно 3000."""
    result = map_operation(
        op(
            type="OPERATION_TYPE_SELL",
            quantity="249000",
            quantityRest="246000",
            quantityDone="3000",
            cancelDateTime="2024-05-30T13:11:03Z",
            cancelReason="По запросу клиента",
            price={"currency": "rub", "units": "0", "nano": 223620000},
            payment={"currency": "rub", "units": "670", "nano": 860000000},
        ),
        SBER,
    )
    assert result.quantity == Decimal("3000")


def test_fully_filled_order_keeps_its_quantity():
    result = map_operation(op(quantity="35", quantityRest="0", quantityDone="35"), SBER)
    assert result.quantity == Decimal("35")


def test_order_still_being_filled_is_skipped():
    """Заявку, у которой остался неисполненный остаток и нет отметки об отмене,
    брокер отдаёт со state=EXECUTED, но она ещё исполняется: quantityDone
    вырастет. Записать её сейчас значит записать промежуточное значение
    навсегда — журнал append-only, а дедупликация по внешнему идентификатору
    больше эту операцию не тронет.

    Живой случай 09.08.2026: покупка TMOS прочиталась как 12 из 100, доисполнилась
    до 100, и в журнале навсегда осталось 12 — расхождение со сверкой на 88 штук.
    Окно повторной синхронизации (SYNC_OVERLAP_DAYS) перечитает её уже полной."""
    just_now = datetime(2026, 3, 12, 10, 35, tzinfo=timezone.utc)
    assert map_operation(
        op(quantity="100", quantityRest="88", quantityDone="12"), SBER, now=just_now
    ) is None


def test_old_order_with_unfilled_rest_is_recorded_not_skipped():
    """У старых операций брокер отметку об отмене не заполняет: продажа Яндекса
    25.11.2020 (операция 21944210316) пришла с остатком 36 из 39 и пустым
    cancelReason, хотя исполнилась она шестью годами раньше и вырасти уже не
    может. Отбросить такую — потерять сделку навсегда: повторная синхронизация
    до 2020 года не дотянется. Признак «ещё исполняется» — свежесть операции,
    и только она."""
    long_after = datetime(2026, 3, 12, tzinfo=timezone.utc)
    result = map_operation(
        op(
            type="OPERATION_TYPE_SELL",
            date="2020-11-25T13:41:10.198Z",
            quantity="39",
            quantityRest="36",
            quantityDone="3",
            payment={"currency": "rub", "units": "12000", "nano": 0},
        ),
        SBER,
        now=long_after,
    )
    assert result is not None
    assert result.quantity == Decimal("3")


def test_partially_filled_but_cancelled_order_is_recorded():
    """Отменённая заявка окончательна: остаток уже не исполнится. Такую надо
    записать — но исполненной частью. Проверка на живых данных: за полтора года
    по двум счетам все 45 операций с неисполненным остатком несли отметку об
    отмене, «висящих» без неё не нашлось."""
    result = map_operation(
        op(quantity="5", quantityRest="4", quantityDone="1", cancelDateTime="2026-07-15T18:03:16.734Z"),
        SBER,
    )
    assert result is not None
    assert result.quantity == Decimal("1")


def test_quantity_falls_back_when_broker_omits_executed_field():
    """Ответ без quantityDone (устаревший GetOperations, чужая реализация шлюза)
    не должен превращать количество в ноль — тогда сделка тихо перестанет двигать
    позицию. Без поля опереться можно только на quantity."""
    result = map_operation(op(quantity="35"), SBER)
    assert result.quantity == Decimal("35")


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


def test_payload_carries_availability_flags():
    instrument = BrokerInstrument(isin="HK0000009866", ticker="9866", kind="share",
                                  name="Nio", currency="HKD",
                                  buy_available=False, sell_available=False)

    result = map_operation(op(), instrument)

    assert result.payload["instrument_buy_available"] is False
    assert result.payload["instrument_sell_available"] is False
