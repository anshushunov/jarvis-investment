"""Бумага, которой нет в справочнике, заводится из снимка брокера.

Живой случай: HK0000051877 (79 штук) и HK0000123577 (92 штуки) лежат у брокера,
но в instrument их нет — в журнале по ним нет ни одной операции, а справочник
заполняется из операций. В расхождениях они показаны безымянными, и
конвертации их не во что зачислять.

Заводить по ISIN «на глазок» нельзя: одному ISIN в справочнике брокера
соответствует запись на каждый режим торгов, с разными флагами и валютой. В
фазе 2a обе наивные стратегии дали ошибки на миллионы. Здесь этой проблемы нет
по построению: коннектор уже разрешил инструмент по FIGI позиции, остаётся
донести результат до записи снимка.
"""

from decimal import Decimal

from sqlalchemy import select

from app.connectors.base import BrokerInstrument, BrokerPosition
from app.models import Account, BrokerHolding, Instrument
from app.sync.holdings import store_holdings


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def test_unknown_isin_gets_an_instrument_from_the_snapshot(session):
    account = _account(session)

    store_holdings(session, account, [BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("79"),
        blocked=Decimal("79"),
        reference=BrokerInstrument(
            isin="HK0000051877", ticker="3690", kind="share",
            name="Meituan Class B", currency="HKD",
            buy_available=False, sell_available=False,
        ),
    )])

    instrument = session.execute(
        select(Instrument).where(Instrument.isin == "HK0000051877")
    ).scalar_one()
    assert instrument.kind == "share"
    assert instrument.currency == "HKD"
    assert instrument.issuer == "Meituan Class B"
    assert instrument.trading_restricted is True

    holding = session.execute(select(BrokerHolding)).scalar_one()
    assert holding.instrument_id == instrument.id


def test_second_snapshot_does_not_duplicate_and_refreshes_reference(session):
    account = _account(session)
    position = BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("79"),
        blocked=Decimal("79"),
        reference=BrokerInstrument(isin="HK0000051877", ticker="3690",
                                   kind="share", name="Meituan Class B",
                                   currency="HKD", buy_available=False,
                                   sell_available=False),
    )
    store_holdings(session, account, [position])

    store_holdings(session, account, [BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("79"),
        blocked=Decimal("0"),
        reference=BrokerInstrument(isin="HK0000051877", ticker="3690",
                                   kind="share", name="Meituan Class B",
                                   currency="HKD", buy_available=True,
                                   sell_available=True),
    )])

    instruments = session.execute(
        select(Instrument).where(Instrument.isin == "HK0000051877")
    ).scalars().all()
    assert len(instruments) == 1
    # Разблокировка — такое же сообщение справочника, как и блокировка.
    assert instruments[0].trading_restricted is False


def test_merge_of_two_references_keeps_the_first_ones_reference(session):
    """Две порции одной бумаги на одном счёте (разные FIGI, один ISIN) несут
    разные справочные сведения — такое бывает, если один из ответов брокера
    устарел или неполон. Побеждает первая порция по порядку в снимке брокера:
    это не выбор «по FIGI» (обе уже корректно разрешены по своему FIGI), а
    произвольный, но детерминированный выбор одной из двух ссылок на одну и
    ту же бумагу. Тест ловит порядок явно: если поменять
    `existing.reference or item.reference` местами на `item.reference or
    existing.reference`, эта проверка провалится, потому что у первой и
    второй позиции разные issuer/currency/trading_restricted."""
    account = _account(session)

    first = BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("50"),
        blocked=Decimal("50"),
        reference=BrokerInstrument(isin="HK0000051877", ticker="3690",
                                   kind="share", name="Meituan First",
                                   currency="HKD", buy_available=False,
                                   sell_available=False),
    )
    second = BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("29"),
        blocked=Decimal("0"),
        reference=BrokerInstrument(isin="HK0000051877", ticker="3690",
                                   kind="share", name="Meituan Second",
                                   currency="USD", buy_available=True,
                                   sell_available=True),
    )

    store_holdings(session, account, [first, second])

    instrument = session.execute(
        select(Instrument).where(Instrument.isin == "HK0000051877")
    ).scalar_one()
    assert instrument.issuer == "Meituan First"
    assert instrument.currency == "HKD"
    assert instrument.trading_restricted is True

    holding = session.execute(select(BrokerHolding)).scalar_one()
    assert holding.quantity == Decimal("79")
    assert holding.blocked == Decimal("50")


def test_merge_falls_back_to_the_second_positions_reference_when_the_first_has_none(session):
    """Первая порция брокером отдана без справочных сведений (reference=None),
    вторая — со сведениями. Слияние не должно терять единственную доступную
    ссылку только потому, что она пришла второй."""
    account = _account(session)

    first = BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("50"),
        blocked=Decimal("0"),
    )
    second = BrokerPosition(
        isin="HK0000051877", ticker="3690", quantity=Decimal("29"),
        blocked=Decimal("29"),
        reference=BrokerInstrument(isin="HK0000051877", ticker="3690",
                                   kind="share", name="Meituan Second",
                                   currency="USD", buy_available=True,
                                   sell_available=True),
    )

    store_holdings(session, account, [first, second])

    instrument = session.execute(
        select(Instrument).where(Instrument.isin == "HK0000051877")
    ).scalar_one()
    assert instrument.issuer == "Meituan Second"
    assert instrument.currency == "USD"
    assert instrument.trading_restricted is False

    holding = session.execute(select(BrokerHolding)).scalar_one()
    assert holding.quantity == Decimal("79")
    assert holding.blocked == Decimal("29")


def test_position_without_reference_still_stores_holding(session):
    """Брокер, который справочных сведений не даёт, не должен ронять снимок:
    строка обязана сохраниться, просто без связи с инструментом."""
    account = _account(session)

    store_holdings(session, account, [BrokerPosition(
        isin="XX0000000001", ticker=None, quantity=Decimal("5"),
        blocked=Decimal("0"),
    )])

    holding = session.execute(select(BrokerHolding)).scalar_one()
    assert holding.isin == "XX0000000001"
    assert holding.instrument_id is None
