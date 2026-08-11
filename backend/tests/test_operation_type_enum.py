"""Тип операции, прочитанный из базы, — это OperationType, а не строка.

Тест на объекте, собранном в памяти, ничего не доказывал бы: там тип и так
тот, что положили. Значение обязано пройти через настоящий PostgreSQL —
именно на этом пути `is` молча возвращал ложь, пока колонка была String(24),
и погашение облигаций переставало закрывать позицию.
"""

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import Account, OperationType, Transaction


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Тест", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_op_type_read_from_db_is_enum_not_string(session):
    account = _account(session)
    session.add(Transaction(
        account_id=account.id, op_type=OperationType.REDEMPTION,
        executed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("1000"),
        currency="RUB", fee=Decimal("0"), source="tbank", dedup_key="k-1",
    ))
    session.flush()
    session.expire_all()

    loaded = session.execute(select(Transaction)).scalar_one()

    assert loaded.op_type is OperationType.REDEMPTION


def test_all_new_operation_types_survive_a_round_trip(session):
    account = _account(session)
    new_types = [
        OperationType.TRANSFER_IN, OperationType.TRANSFER_OUT,
        OperationType.CONVERSION_OUT, OperationType.CONVERSION_IN,
        OperationType.ADJUSTMENT,
    ]
    for index, op_type in enumerate(new_types):
        session.add(Transaction(
            account_id=account.id, op_type=op_type,
            executed_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            quantity=Decimal("1"), price=Decimal("0"), amount=Decimal("0"),
            currency="RUB", fee=Decimal("0"), source="manual",
            dedup_key=f"k-new-{index}",
        ))
    session.flush()
    session.expire_all()

    loaded = session.execute(
        select(Transaction).where(Transaction.source == "manual")
        .order_by(Transaction.dedup_key)
    ).scalars().all()

    assert [tx.op_type for tx in loaded] == new_types
