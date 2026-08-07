from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.models import Account, Instrument, OperationType, Transaction


def test_transaction_persists_decimal_precision(session):
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB", issuer="Сбербанк")
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    session.add_all([instrument, account])
    session.flush()

    tx = Transaction(
        account_id=account.id,
        instrument_id=instrument.id,
        op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
        quantity=Decimal("35.00000000"),
        price=Decimal("142.5000"),
        amount=Decimal("-4987.5000"),
        currency="RUB",
        fee=Decimal("1.4963"),
        external_id="op-777",
        source="tbank",
        payload={"raw": "value"},
    )
    session.add(tx)
    session.commit()

    stored = session.get(Transaction, tx.id)
    assert stored.price == Decimal("142.5000")
    assert stored.fee == Decimal("1.4963")
    assert stored.payload == {"raw": "value"}


def test_external_id_unique_per_source(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-2",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()

    def make(external_id: str) -> Transaction:
        return Transaction(
            account_id=account.id, instrument_id=None, op_type=OperationType.DEPOSIT,
            executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("1000.0000"),
            currency="RUB", fee=Decimal("0"), external_id=external_id,
            source="tbank", payload={},
        )

    session.add(make("dup-1"))
    session.commit()

    session.add(make("dup-1"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def _make_transaction(account_id: int, external_id: str) -> Transaction:
    return Transaction(
        account_id=account_id, instrument_id=None, op_type=OperationType.DEPOSIT,
        executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("1000.0000"),
        currency="RUB", fee=Decimal("0"), external_id=external_id,
        source="tbank", payload={},
    )


def test_transaction_update_is_rejected(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-3",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()

    tx = _make_transaction(account.id, "op-update-1")
    session.add(tx)
    session.commit()

    with pytest.raises(DBAPIError):
        session.execute(
            text('UPDATE "transaction" SET amount = :amount WHERE id = :id'),
            {"amount": Decimal("2000.0000"), "id": tx.id},
        )
        session.commit()
    session.rollback()


def test_transaction_delete_is_rejected(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-4",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()

    tx = _make_transaction(account.id, "op-delete-1")
    session.add(tx)
    session.commit()

    with pytest.raises(DBAPIError):
        session.execute(text('DELETE FROM "transaction" WHERE id = :id'), {"id": tx.id})
        session.commit()
    session.rollback()
