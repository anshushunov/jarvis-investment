from datetime import date
from decimal import Decimal

from app.connectors.base import BrokerPrice
from app.marketdata.broker_prices import store_broker_prices
from app.marketdata.service import MOEX_SOURCE, TBANK_SOURCE
from app.models import Instrument, Price


def add_instrument(session, isin: str, currency: str = "RUB") -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin, secid=isin, kind="share", currency=currency)
    session.add(instrument)
    session.flush()
    return instrument


def test_stores_price_with_broker_source(session):
    add_instrument(session, "HK0000009866", currency="HKD")

    written = store_broker_prices(
        session,
        [BrokerPrice(isin="HK0000009866", price=Decimal("36.90"), currency="HKD")],
        date(2026, 8, 9),
    )

    assert written == 1
    stored = session.query(Price).one()
    assert (stored.close, stored.currency, stored.source) == (Decimal("36.9000"), "HKD", TBANK_SOURCE)


def test_unknown_isin_is_skipped(session):
    """Инструмента нет в справочнике — цену не к чему привязать. Заводить
    инструмент из цены нельзя: справочные сведения о нём приходят с операциями,
    и пустая заготовка навсегда осталась бы «видом неизвестно»."""
    written = store_broker_prices(
        session, [BrokerPrice(isin="XX0000000000", price=Decimal("1"), currency="RUB")],
        date(2026, 8, 9),
    )

    assert written == 0
    assert session.query(Price).count() == 0


def test_repeated_run_updates_the_same_row(session):
    instrument = add_instrument(session, "HK0000009866", currency="HKD")
    store_broker_prices(session, [BrokerPrice(isin="HK0000009866", price=Decimal("36.90"),
                                              currency="HKD")], date(2026, 8, 9))
    store_broker_prices(session, [BrokerPrice(isin="HK0000009866", price=Decimal("37.50"),
                                              currency="HKD")], date(2026, 8, 9))

    stored = session.query(Price).filter(Price.instrument_id == instrument.id).all()
    assert len(stored) == 1
    assert stored[0].close == Decimal("37.5000")


def test_broker_price_does_not_touch_exchange_price(session):
    """Две записи за один день от разных источников сосуществуют — выбор между
    ними делает чтение, а не порядок записи."""
    instrument = add_instrument(session, "RU0009029540")
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
                      close=Decimal("314.28"), currency="RUB", source=MOEX_SOURCE))
    session.flush()

    store_broker_prices(session, [BrokerPrice(isin="RU0009029540", price=Decimal("315.00"),
                                              currency="RUB")], date(2026, 8, 9))

    assert session.query(Price).count() == 2
