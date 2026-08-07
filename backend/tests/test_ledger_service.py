from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.instruments.service import _insert_instrument
from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.ledger.service import _insert_one, append_operations
from app.models import Account, Instrument, OperationType, Transaction


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


def test_dedup_conflict_at_insert_is_skipped_not_raised(session):
    """Гонка между двумя параллельными вызовами append_operations по одному счёту
    (например, плановая синхронизация и ручной POST /api/sync/tbank почти одновременно):
    оба видят один и тот же dedup_key ещё не занятым на этапе предварительного SELECT,
    и только на INSERT срабатывает uq_transaction_dedup_key. В одном потоке эту гонку
    через append_operations не воспроизвести — SELECT в начале второго вызова уже увидит
    строку первого. Поэтому обходим предварительную проверку и вызываем внутреннюю
    функцию вставки _insert_one дважды подряд с одним и тем же dedup_key — уникальный
    индекс срабатывает по-настоящему, а ветка обработки конфликта оказывается покрыта."""
    account = make_account(session)
    # external_id=None: конфликт должен проверяться именно по dedup_key, а не попутно
    # словить uq_transaction_source_external из-за одинакового external_id.
    op = buy_op(external_id=None)
    key = natural_key("tbank", account.external_id, op)

    assert _insert_one(session, account, "tbank", op, key) is True
    assert _insert_one(session, account, "tbank", op, key) is False
    assert count_tx(session) == 1


def test_instrument_isin_conflict_at_insert_reuses_existing(session):
    """Аналогичная гонка на уровне резолюции инструмента: два вызова append_operations
    впервые видят один и тот же новый ISIN одновременно. resolve_instrument сам её не
    воспроизведёт (предварительный select найдёт уже вставленную строку) — вызываем
    внутреннюю _insert_instrument дважды подряд, минуя select, чтобы сработал реальный
    уникальный индекс ix_instrument_isin."""
    op = buy_op()

    first = _insert_instrument(session, op)
    second = _insert_instrument(session, op)

    assert first.id == second.id
    count = session.execute(select(func.count()).select_from(Instrument)).scalar_one()
    assert count == 1
