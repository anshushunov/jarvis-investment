from datetime import datetime
from decimal import Decimal

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
    "OPERATION_TYPE_BOND_REPAYMENT": OperationType.REDEMPTION,
    "OPERATION_TYPE_BOND_REPAYMENT_FULL": OperationType.REDEMPTION,
    "OPERATION_TYPE_BOND_AMORTIZATION": OperationType.AMORTIZATION,
}

EXECUTED = "OPERATION_STATE_EXECUTED"


def map_operation(operation: dict, isin: str | None, ticker: str | None) -> RawOperation | None:
    """Переводит операцию OperationsService/GetOperationsByCursor (REST-шлюз
    T-Invest API, JSON-словарь) в RawOperation. Неисполненные операции
    (state != EXECUTED) пропускаются — они не должны попадать в журнал."""
    if operation.get("state") != EXECUTED:
        return None

    raw_type = operation["type"]
    op_type = TYPE_MAP.get(raw_type, OperationType.OTHER)

    payment = operation.get("payment")
    currency = (payment or {}).get("currency") or operation.get("currency") or "rub"

    return RawOperation(
        external_id=str(operation["id"]),
        op_type=op_type,
        executed_at=datetime.fromisoformat(operation["date"]),
        isin=isin,
        ticker=ticker,
        quantity=quantity(Decimal(operation.get("quantity") or "0")),
        price=to_money(operation.get("price")),
        amount=to_money(payment),
        currency=currency.upper(),
        # Комиссия не вычитается из fee сделки: T-Invest API отдаёт брокерскую
        # комиссию отдельной операцией OPERATION_TYPE_BROKER_FEE, и учитывать
        # её дважды нельзя.
        fee=money("0"),
        payload={"operation_type": raw_type, "figi": operation.get("figi") or None},
    )
