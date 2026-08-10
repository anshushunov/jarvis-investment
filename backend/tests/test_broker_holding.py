from decimal import Decimal

from app.connectors.base import BrokerPosition
from app.models import Account, BrokerHolding, Instrument
from app.sync.holdings import blocked_by_instrument, store_holdings


def add_account(session) -> Account:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Счёт", currency="RUB")
    session.add(account)
    session.flush()
    return account


def add_instrument(session, isin: str) -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin, secid=isin, kind="etf", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def test_stores_snapshot_with_blocked_part(session):
    account = add_account(session)
    instrument = add_instrument(session, "HK0000123577")

    written = store_holdings(session, account, [
        BrokerPosition(isin="HK0000123577", ticker="HK0000123577",
                       quantity=Decimal("92"), blocked=Decimal("92")),
    ])

    assert written == 1
    holding = session.query(BrokerHolding).one()
    assert (holding.quantity, holding.blocked, holding.instrument_id) == (
        Decimal("92.00000000"), Decimal("92.00000000"), instrument.id
    )


def test_holding_of_unknown_instrument_is_kept_without_link(session):
    """Заблокированный фонд под новым ISIN в справочнике может отсутствовать —
    он появился у брокера в результате конвертации, а в журнале его нет. Сумму
    и факт блокировки терять нельзя: именно они объясняют расхождение."""
    account = add_account(session)

    store_holdings(session, account, [
        BrokerPosition(isin="HK0000051877", ticker="HK0000051877",
                       quantity=Decimal("79"), blocked=Decimal("79")),
    ])

    holding = session.query(BrokerHolding).one()
    assert holding.instrument_id is None
    assert holding.isin == "HK0000051877"


def test_snapshot_replaces_previous_one(session):
    account = add_account(session)
    add_instrument(session, "RU0009029540")
    store_holdings(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10"),
                       blocked=Decimal("0")),
    ])

    store_holdings(session, account, [])

    assert session.query(BrokerHolding).count() == 0


def test_two_positions_with_same_isin_are_merged_not_duplicated(session):
    """Разные FIGI брокера иногда разрешаются в один ISIN — та же бумага на
    другой площадке или в другом режиме торгов. Живой случай: прогон падал на
    UniqueViolation по (account_id, isin), потому что store_holdings пытался
    вставить обе позиции отдельными строками. Проверка идёт через
    store_holdings с настоящей сессией — падало именно на вставке, а не на
    промежуточном списке позиций."""
    account = add_account(session)
    instrument = add_instrument(session, "RU0009029540")

    written = store_holdings(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10"),
                       blocked=Decimal("2")),
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("5"),
                       blocked=Decimal("0")),
    ])

    assert written == 1
    holding = session.query(BrokerHolding).one()
    assert (holding.quantity, holding.blocked, holding.instrument_id) == (
        Decimal("15.00000000"), Decimal("2.00000000"), instrument.id
    )


def test_blocked_by_instrument_skips_unlinked_and_zero(session):
    account = add_account(session)
    linked = add_instrument(session, "HK0000123577")
    add_instrument(session, "RU0009029540")
    store_holdings(session, account, [
        BrokerPosition(isin="HK0000123577", ticker="x", quantity=Decimal("92"),
                       blocked=Decimal("92")),
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10"),
                       blocked=Decimal("0")),
        BrokerPosition(isin="HK0000051877", ticker="y", quantity=Decimal("79"),
                       blocked=Decimal("79")),
    ])

    assert blocked_by_instrument(session) == {(account.id, linked.id): Decimal("92.00000000")}
