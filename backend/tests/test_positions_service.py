from datetime import datetime, timezone
from decimal import Decimal

from app.models import Account, Instrument, OperationType, Position, Transaction
from app.positions.service import rebuild_positions


def setup_account(session) -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    session.add(account)
    session.flush()
    return account


def add_tx(session, account, instrument, op_type, day, qty, price, amount):
    session.add(Transaction(
        account_id=account.id,
        instrument_id=instrument.id if instrument else None,
        op_type=op_type,
        executed_at=datetime(2026, 3, day, tzinfo=timezone.utc),
        quantity=Decimal(qty), price=Decimal(price), amount=Decimal(amount),
        currency="RUB", fee=Decimal("0"), external_id=f"tx-{day}-{op_type}",
        source="tbank", payload={}, dedup_key=f"key-{day}-{op_type}",
    ))
    session.flush()


def add_instrument(session) -> Instrument:
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def test_creates_position_from_journal(session):
    account = setup_account(session)
    instrument = add_instrument(session)
    add_tx(session, account, instrument, OperationType.BUY, 1, "10", "100", "-1000")

    assert rebuild_positions(session, account) == 1

    position = session.query(Position).one()
    assert position.quantity == Decimal("10.00000000")
    assert position.average_price == Decimal("100.0000")


def test_full_redemption_read_from_db_closes_the_position(session):
    """Через настоящую БД, а не только на движке: op_type хранится строкой
    (String(24)), и после чтения это `str`, а не OperationType. Сравнение типа
    через `is` тут молча ложно — погашение переставало закрывать позицию, и
    погашенные облигации оставались в портфеле."""
    account = setup_account(session)
    instrument = add_instrument(session)
    add_tx(session, account, instrument, OperationType.BUY, 1, "124", "1000", "-124000")
    add_tx(session, account, instrument, OperationType.REDEMPTION, 9, "0", "0", "124000")

    assert rebuild_positions(session, account) == 0
    assert session.query(Position).count() == 0


def test_rebuild_is_idempotent(session):
    account = setup_account(session)
    instrument = add_instrument(session)
    add_tx(session, account, instrument, OperationType.BUY, 1, "10", "100", "-1000")

    rebuild_positions(session, account)
    rebuild_positions(session, account)

    assert session.query(Position).count() == 1


def test_closed_position_is_removed(session):
    account = setup_account(session)
    instrument = add_instrument(session)
    add_tx(session, account, instrument, OperationType.BUY, 1, "10", "100", "-1000")
    rebuild_positions(session, account)

    add_tx(session, account, instrument, OperationType.SELL, 2, "10", "120", "1200")
    assert rebuild_positions(session, account) == 0
    assert session.query(Position).count() == 0


def test_cash_operations_do_not_create_positions(session):
    account = setup_account(session)
    add_tx(session, account, None, OperationType.DEPOSIT, 1, "0", "0", "50000")

    assert rebuild_positions(session, account) == 0


def test_rebuild_does_not_touch_other_accounts_positions(session):
    account1 = setup_account(session)
    account2 = Account(broker="tbank", kind="brokerage", external_id="acc-2",
                       name="ИИС", currency="RUB")
    session.add(account2)
    session.flush()
    instrument = add_instrument(session)

    add_tx(session, account2, instrument, OperationType.BUY, 1, "5", "200", "-1000")
    assert rebuild_positions(session, account2) == 1

    add_tx(session, account1, instrument, OperationType.BUY, 2, "10", "100", "-1000")
    assert rebuild_positions(session, account1) == 1

    positions = {p.account_id: p for p in session.query(Position).all()}
    assert set(positions) == {account1.id, account2.id}
    assert positions[account1.id].quantity == Decimal("10.00000000")
    assert positions[account2.id].quantity == Decimal("5.00000000")
    assert positions[account2.id].average_price == Decimal("200.0000")
