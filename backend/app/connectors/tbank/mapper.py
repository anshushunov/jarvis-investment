from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.connectors.base import BrokerInstrument
from app.connectors.tbank.quotation import to_money
from app.ledger.schemas import RawOperation
from app.models import OperationType
from app.money import money, quantity

# T-Invest API добавляет типы операций со временем; незнакомый тип уходит в
# OperationType.OTHER (см. test_unknown_type_maps_to_other_and_keeps_payload),
# а не роняет синхронизацию.
TYPE_MAP = {
    "OPERATION_TYPE_BUY": OperationType.BUY,
    "OPERATION_TYPE_BUY_CARD": OperationType.BUY,
    "OPERATION_TYPE_SELL": OperationType.SELL,
    "OPERATION_TYPE_DIVIDEND": OperationType.DIVIDEND,
    "OPERATION_TYPE_COUPON": OperationType.COUPON,
    "OPERATION_TYPE_BROKER_FEE": OperationType.FEE,
    "OPERATION_TYPE_SERVICE_FEE": OperationType.FEE,
    "OPERATION_TYPE_MARGIN_FEE": OperationType.FEE,
    "OPERATION_TYPE_TAX": OperationType.TAX,
    "OPERATION_TYPE_DIVIDEND_TAX": OperationType.TAX,
    "OPERATION_TYPE_INPUT": OperationType.DEPOSIT,
    "OPERATION_TYPE_OUTPUT": OperationType.WITHDRAWAL,
    # Полное погашение закрывает выпуск целиком; частичное — это выплата части
    # номинала, количество бумаг при ней не меняется, поэтому оно идёт в
    # AMORTIZATION, а не в REDEMPTION. Живое подтверждение: 45 облигаций
    # РЕСО-Лизинг, выплата 11250 ₽ (по 250 на бумагу), после неё цена упала с
    # ~750 до ~500 — бумаг осталось те же 45, и позже все 50 были проданы.
    "OPERATION_TYPE_BOND_REPAYMENT_FULL": OperationType.REDEMPTION,
    "OPERATION_TYPE_BOND_REPAYMENT": OperationType.AMORTIZATION,
    "OPERATION_TYPE_BOND_AMORTIZATION": OperationType.AMORTIZATION,
    # Перевод бумаг: приходят и уходят количеством, себестоимости брокер при
    # этом не сообщает. Живой случай — 351 бумага РусАгро 19.12.2024, которая
    # уходила в OTHER и не двигала позицию: сверка показывала 209 против 560.
    # Написание подтверждено на живом ответе GetOperationsByCursor владельца
    # (все счета, с 2020-01-01): OPERATION_TYPE_INPUT_SECURITIES встречается,
    # OPERATION_TYPE_OUTPUT_SECURITIES — ни разу, добавлен по документации
    # T-Invest API.
    "OPERATION_TYPE_INPUT_SECURITIES": OperationType.TRANSFER_IN,
    "OPERATION_TYPE_OUTPUT_SECURITIES": OperationType.TRANSFER_OUT,
}

EXECUTED = "OPERATION_STATE_EXECUTED"

# Насколько свежей должна быть операция, чтобы считать её ещё исполняющейся.
# Обязано быть меньше SYNC_OVERLAP_DAYS (app/sync/service.py) — см.
# _is_still_being_filled.
STILL_FILLING_WINDOW = timedelta(days=1)


def _is_still_being_filled(operation: dict, executed_at: datetime, now: datetime) -> bool:
    """Заявка с неисполненным остатком, который ещё может исполниться.

    T-Invest API отдаёт такую заявку со state=EXECUTED уже по первой сделке, и
    quantityDone у неё продолжает расти. Записать её сейчас — значит записать
    промежуточное значение навсегда: журнал append-only, а дедупликация по
    (счёт, источник, внешний идентификатор) больше эту операцию не тронет.
    Живой случай 09.08.2026 — покупка TMOS прочиталась как 12 из 100,
    доисполнилась до 100, и сверка показала расхождение ровно на 88 штук.

    Отметка об отмене означает, что остаток уже не исполнится, — но её
    отсутствие ничего не доказывает: у старых операций брокер её просто не
    заполняет (продажа Яндекса 25.11.2020, операция 21944210316: остаток 36 из
    39, cancelDateTime нет, а исполнилась она шесть лет назад). Поэтому
    единственный надёжный признак «ещё исполняется» — свежесть самой операции.

    Порог заведомо меньше окна перекрытия повторной синхронизации
    (SYNC_OVERLAP_DAYS в app/sync/service.py): пропуск безопасен ровно потому,
    что следующий прогон перечитает эту операцию уже окончательной. Заявка,
    висящая дольше суток, будет записана исполненной частью — лучше так, чем
    потерять сделку, до которой синхронизация больше не дотянется."""
    if operation.get("cancelDateTime"):
        return False
    if Decimal(operation.get("quantityRest") or "0") <= 0:
        return False
    return now - executed_at < STILL_FILLING_WINDOW


def _executed_quantity(operation: dict) -> Decimal:
    """Сколько бумаг реально прошло по операции.

    T-Invest API отдаёт три поля: `quantity` — сколько было в заявке,
    `quantityRest` — неисполненный остаток, `quantityDone` — исполненное.
    Заявка, исполнившаяся частично и снятая, приходит со state=EXECUTED и
    сохраняет в `quantity` полный объём заявки; в журнал же обязано попасть
    только исполненное, иначе продажи оказываются больше реальных, движок
    позиций отбрасывает излишек (уйти в минус он не даёт) и на счёте навсегда
    остаётся фантомный остаток бумаги, которой давно нет. Живой пример —
    продажа ELMT 30.05.2024: заявка 249000, исполнено 3000, остальное снято.

    `quantityDone` — первично: у неторговых операций (дивиденд, купон, комиссия)
    все три поля нулевые, так что отдельной ветки по типу операции не нужно.
    Запасной путь на `quantity` — на случай ответа без этого поля (устаревший
    GetOperations); подставлять там ноль нельзя, сделка тихо перестала бы
    двигать позицию."""
    done = operation.get("quantityDone")
    raw = done if done not in (None, "") else operation.get("quantity")
    return Decimal(raw or "0")


def map_operation(
    operation: dict, instrument: BrokerInstrument | None, now: datetime | None = None
) -> RawOperation | None:
    """Переводит операцию OperationsService/GetOperationsByCursor (REST-шлюз
    T-Invest API, JSON-словарь) в RawOperation. Неисполненные операции
    (state != EXECUTED) пропускаются — они не должны попадать в журнал, как и
    заявки, которые ещё исполняются (см. _is_still_being_filled).

    `instrument` — то, что коннектор разрешил по FIGI операции (None для
    денежных операций без инструмента). Кроме ISIN и тикера оттуда берутся вид
    и название: домену больше неоткуда их узнать, а без вида инструмент
    записывается акцией и ищется не на том рынке MOEX.

    `now` — точка отсчёта свежести операции; вынесена в параметр, чтобы тесты
    не зависели от настоящих часов."""
    if operation.get("state") != EXECUTED:
        return None

    executed_at = datetime.fromisoformat(operation["date"])
    if _is_still_being_filled(operation, executed_at, now or datetime.now(tz=timezone.utc)):
        return None

    raw_type = operation["type"]
    op_type = TYPE_MAP.get(raw_type, OperationType.OTHER)

    payment = operation.get("payment")
    currency = (payment or {}).get("currency") or operation.get("currency") or "rub"

    return RawOperation(
        external_id=str(operation["id"]),
        op_type=op_type,
        executed_at=executed_at,
        isin=instrument.isin if instrument else None,
        ticker=instrument.ticker if instrument else None,
        quantity=quantity(_executed_quantity(operation)),
        price=to_money(operation.get("price")),
        amount=to_money(payment),
        currency=currency.upper(),
        # Комиссия не вычитается из fee сделки: T-Invest API отдаёт брокерскую
        # комиссию отдельной операцией OPERATION_TYPE_BROKER_FEE, и учитывать
        # её дважды нельзя.
        fee=money("0"),
        payload={
            "operation_type": raw_type,
            "figi": operation.get("figi") or None,
            # Справочные сведения об инструменте едут в payload — это
            # единственный канал от коннектора к доменному резолверу
            # инструментов (app/instruments/service.py), который на входе видит
            # только RawOperation. Ключей нет вовсе, если инструмент не
            # разрешён: резолвер тогда и не создаёт запись (isin=None).
            **_instrument_payload(instrument),
        },
    )


def _instrument_payload(instrument: BrokerInstrument | None) -> dict:
    if instrument is None:
        return {}
    return {
        "instrument_kind": instrument.kind,
        "instrument_name": instrument.name,
        # Валюта инструмента из справочника — не то же самое, что currency
        # самой операции выше: та относится к платежу (комиссия по валютной
        # бумаге приходит в рублях), эта — к бумаге.
        "instrument_currency": instrument.currency,
        # Доступность операций: по ней домен решает, ограничена ли бумага в
        # обороте. Едут двумя полями, а не готовым признаком, — вывод доменный.
        "instrument_buy_available": instrument.buy_available,
        "instrument_sell_available": instrument.sell_available,
    }
