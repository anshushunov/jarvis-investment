"""Операция, изменённая брокером задним числом, даёт корректирующую запись.

До этой правки конфликт по (account_id, source, external_id) считался дублем и
молча пропускался — верно, когда содержание совпало, и неверно, когда брокер
переписал операцию. Журнал append-only, поэтому ответ — новая запись на
разницу, а не правка старой.

Частый случай доисполняющейся заявки закрыт отдельно, окном
STILL_FILLING_WINDOW в коннекторе, так что этот путь должен срабатывать редко.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.ledger.schemas import RawOperation
from app.ledger.service import append_operations
from app.models import Account, OperationType, Transaction


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def _operation(quantity: str, amount: str, price: str = "100") -> RawOperation:
    return RawOperation(
        external_id="op-1", op_type="BUY",
        executed_at=datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc),
        isin="RU0009029540", ticker="SBER", quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal(amount), currency="RUB",
        fee=Decimal("0"), payload={},
    )


def test_identical_repeat_is_still_skipped_silently(session):
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200")])

    result = append_operations(session, account, "tbank", [_operation("12", "-1200")])

    assert result.inserted == 0
    assert result.skipped == 1
    assert result.corrected == 0
    assert len(session.execute(select(Transaction)).scalars().all()) == 1


def test_changed_quantity_produces_a_correcting_entry(session):
    """Живой класс случая: заявка на 100 прочиталась как 12 и доисполнилась."""
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200")])

    result = append_operations(session, account, "tbank", [_operation("100", "-10000")])

    assert result.corrected == 1
    correction = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalar_one()
    assert correction.quantity == Decimal("88")
    assert correction.amount == Decimal("-8800")
    assert correction.source == "tbank"

    original = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.BUY)
    ).scalar_one()
    assert correction.payload["corrects_transaction_id"] == original.id
    # Исходная запись не тронута: журнал append-only.
    assert original.quantity == Decimal("12")


def test_correcting_entry_is_written_once_not_on_every_sync(session):
    account = _account(session)
    append_operations(session, account, "tbank", [_operation("12", "-1200")])
    append_operations(session, account, "tbank", [_operation("100", "-10000")])

    result = append_operations(session, account, "tbank", [_operation("100", "-10000")])

    assert result.corrected == 0
    corrections = session.execute(
        select(Transaction).where(Transaction.op_type == OperationType.ADJUSTMENT)
    ).scalars().all()
    assert len(corrections) == 1
