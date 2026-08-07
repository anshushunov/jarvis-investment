from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.ledger.schemas import RawOperation
from app.ledger.service import append_operations
from app.models import Account, OperationType, Transaction


def make_account(session) -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()
    return account


def buy_op(external_id: str | None = "op-1") -> RawOperation:
    return RawOperation(
        external_id=external_id, op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
        isin="RU0009029540", ticker="SBER", quantity=Decimal("35"),
        price=Decimal("142.5"), amount=Decimal("-4987.5"), currency="RUB",
        fee=Decimal("1.4963"), payload={},
    )


def count_tx(session) -> int:
    return session.execute(select(func.count()).select_from(Transaction)).scalar_one()


def test_inserts_new_operation(session):
    account = make_account(session)
    result = append_operations(session, account, "tbank", [buy_op()])
    assert result.inserted == 1
    assert count_tx(session) == 1


def test_repeated_call_inserts_nothing(session):
    account = make_account(session)
    append_operations(session, account, "tbank", [buy_op()])
    result = append_operations(session, account, "tbank", [buy_op()])
    assert result.inserted == 0
    assert result.skipped == 1
    assert count_tx(session) == 1


def test_deduplicates_without_external_id(session):
    account = make_account(session)
    append_operations(session, account, "sber", [buy_op(external_id=None)])
    result = append_operations(session, account, "sber", [buy_op(external_id=None)])
    assert result.skipped == 1
    assert count_tx(session) == 1


def test_creates_instrument_on_first_sight(session):
    account = make_account(session)
    append_operations(session, account, "tbank", [buy_op()])
    tx = session.execute(select(Transaction)).scalar_one()
    assert tx.instrument is not None
    assert tx.instrument.isin == "RU0009029540"


def test_cash_operation_has_no_instrument(session):
    account = make_account(session)
    deposit = RawOperation(
        external_id="dep-1", op_type=OperationType.DEPOSIT,
        executed_at=datetime(2026, 1, 9, tzinfo=timezone.utc),
        isin=None, ticker=None, quantity=Decimal("0"), price=Decimal("0"),
        amount=Decimal("100000"), currency="RUB", fee=Decimal("0"), payload={},
    )
    append_operations(session, account, "tbank", [deposit])
    tx = session.execute(select(Transaction)).scalar_one()
    assert tx.instrument_id is None
