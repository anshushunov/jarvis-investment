from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.ledger.schemas import RawOperation
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
        dedup_key="dedup-op-777",
    )
    session.add(tx)
    session.commit()

    stored = session.get(Transaction, tx.id)
    assert stored.price == Decimal("142.5000")
    assert stored.fee == Decimal("1.4963")
    assert stored.payload == {"raw": "value"}


def test_raw_operation_payload_is_frozen():
    """frozen=True обязан замораживать и вложенный payload.

    Иначе обещание неизменности ложное: поля защищены, а словарь внутри —
    нет, и операция меняется у всех держателей ссылки разом.
    """
    operation = RawOperation(
        external_id="1", op_type=OperationType.BUY,
        executed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        isin="RU000A0JQUZ6", ticker="AGRO",
        quantity=Decimal("1"), price=Decimal("100"), amount=Decimal("-100"),
        currency="RUB", fee=Decimal("0"), payload={"figi": "BBG000000001"},
    )

    with pytest.raises(TypeError):
        operation.payload["figi"] = "подменено"


def test_external_id_unique_per_source(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-2",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()

    def make(external_id: str, dedup_key: str) -> Transaction:
        return Transaction(
            account_id=account.id, instrument_id=None, op_type=OperationType.DEPOSIT,
            executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("1000.0000"),
            currency="RUB", fee=Decimal("0"), external_id=external_id,
            source="tbank", payload={}, dedup_key=dedup_key,
        )

    session.add(make("dup-1", "dedup-dup-1"))
    session.commit()

    session.add(make("dup-1", "dedup-dup-1-b"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_external_id_can_repeat_across_different_accounts(session):
    """T-Invest переиспользует один и тот же external id для двух разных записей на
    разных счетах одного владельца — например, обе стороны перевода между своими
    счетами делят общий идентификатор (живое подтверждение и разбор данных —
    docs/decisions/2026-08-08-ledger-external-id-per-account.md). uq_transaction_source_external должен быть
    ограничен рамками счёта (account_id, source, external_id), а не source целиком,
    иначе такая пара ложно считается дублем."""
    account_a = Account(broker="tbank", kind="brokerage", external_id="acc-a",
                        name="Первый", currency="RUB")
    account_b = Account(broker="tbank", kind="brokerage", external_id="acc-b",
                        name="Второй", currency="RUB")
    session.add_all([account_a, account_b])
    session.flush()

    shared_external_id = "8b344af2-3735-4bca-bb13-9c9901fc8047"

    def make(account_id: int, dedup_key: str) -> Transaction:
        return Transaction(
            account_id=account_id, instrument_id=None, op_type=OperationType.OTHER,
            executed_at=datetime(2026, 4, 13, tzinfo=timezone.utc),
            quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("40000.0000"),
            currency="RUB", fee=Decimal("0"), external_id=shared_external_id,
            source="tbank", payload={"operation_type": "OPERATION_TYPE_INP_MULTI"},
            dedup_key=dedup_key,
        )

    session.add(make(account_a.id, "dedup-shared-a"))
    session.add(make(account_b.id, "dedup-shared-b"))
    session.commit()

    count = session.execute(
        select(func.count()).select_from(Transaction).where(Transaction.external_id == shared_external_id)
    ).scalar_one()
    assert count == 2


def _make_transaction(account_id: int, external_id: str) -> Transaction:
    return Transaction(
        account_id=account_id, instrument_id=None, op_type=OperationType.DEPOSIT,
        executed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        quantity=Decimal("0"), price=Decimal("0"), amount=Decimal("1000.0000"),
        currency="RUB", fee=Decimal("0"), external_id=external_id,
        source="tbank", payload={}, dedup_key=f"dedup-{external_id}",
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


def test_dedup_key_has_exactly_one_index(session):
    """На dedup_key стояли сразу два индекса: отдельный ix_transaction_dedup_key
    и тот, что PostgreSQL создаёт под уникальное ограничение
    uq_transaction_dedup_key. Возможности поиска у них одинаковые, а платится
    за оба записью на каждой вставке в журнал."""
    indexes = session.execute(text(
        """
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'transaction' AND indexdef LIKE '%(dedup_key)%'
        """
    )).scalars().all()

    assert indexes == ["uq_transaction_dedup_key"]
