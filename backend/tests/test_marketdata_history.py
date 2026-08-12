from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.marketdata.history import load_price_history
from app.marketdata.moex import MoexHistoryPoint
from app.marketdata.yahoo import YahooHistory
from app.models import Instrument, Price

START = date(2024, 6, 3)
END = date(2024, 6, 4)


class FakeMoex:
    def __init__(self, points: list[MoexHistoryPoint]) -> None:
        self.points = points
        self.calls: list[tuple[str, str, str]] = []

    def close_history(self, secid, start, end, market="shares", engine="stock"):
        self.calls.append((secid, market, engine))
        return self.points


class FakeYahoo:
    def __init__(self, history: YahooHistory | None) -> None:
        self.history = history
        self.calls: list[str] = []

    def close_history(self, symbol, start, end):
        self.calls.append(symbol)
        return self.history


def _instrument(session, **kwargs) -> Instrument:
    defaults = {"isin": "RU000A0JQUZ6", "ticker": "AGRO", "secid": "AGRO",
                "currency": "RUB", "kind": "share"}
    instrument = Instrument(**{**defaults, **kwargs})
    session.add(instrument)
    session.flush()
    return instrument


def _prices(session, instrument) -> list[Price]:
    return list(session.execute(
        select(Price).where(Price.instrument_id == instrument.id).order_by(Price.on_date)
    ).scalars())


def test_russian_share_is_loaded_from_moex(session):
    instrument = _instrument(session)
    moex = FakeMoex([MoexHistoryPoint(on_date=START, close=Decimal("1350.0000"))])

    written = load_price_history(session, instrument, START, END,
                                 moex=moex, yahoo=FakeYahoo(None))

    assert written == 1
    price = _prices(session, instrument)[0]
    assert (price.close, price.currency, price.source) == (Decimal("1350.0000"), "RUB", "moex")
    assert moex.calls == [("AGRO", "shares", "stock")]


def test_bond_price_is_converted_by_the_face_value_of_that_day(session):
    """Облигация котируется в процентах от номинала, и у амортизируемого
    выпуска номинал меняется по ходу истории: 91.3995% от юаневой тысячи —
    913.995 юаня, а не 91 рубль."""
    instrument = _instrument(session, isin="RU000A1054W1", ticker="RU000A1054W1",
                             secid="RU000A1054W1", kind="bond", currency="CNY")
    moex = FakeMoex([MoexHistoryPoint(on_date=START, close=Decimal("91.3995"),
                                      face_value=Decimal("1000.0000"), face_unit="CNY")])

    load_price_history(session, instrument, START, END, moex=moex, yahoo=FakeYahoo(None))

    price = _prices(session, instrument)[0]
    assert (price.close, price.currency) == (Decimal("913.9950"), "CNY")
    assert moex.calls == [("RU000A1054W1", "bonds", "stock")]


def test_foreign_share_is_loaded_from_yahoo(session):
    instrument = _instrument(session, isin="KYG017191142", ticker="9988",
                             secid="9988", currency="HKD")
    yahoo = FakeYahoo(YahooHistory(currency="HKD", points=[(START, Decimal("76.6500"))]))

    written = load_price_history(session, instrument, START, END, moex=FakeMoex([]), yahoo=yahoo)

    assert written == 1
    price = _prices(session, instrument)[0]
    assert (price.close, price.currency, price.source) == (Decimal("76.6500"), "HKD", "yahoo")
    assert yahoo.calls == ["9988.HK"]


def test_symbol_answering_in_another_currency_is_refused(session):
    """Тикер `700` на американском рынке — не Tencent. Цена чужой бумаги ничем
    не отличается от настоящей, кроме того, что неверна, поэтому несовпадение
    валюты — отказ, а не предупреждение."""
    instrument = _instrument(session, isin="KYG875721634", ticker="700", secid="700", currency="HKD")
    yahoo = FakeYahoo(YahooHistory(currency="USD", points=[(START, Decimal("12.3400"))]))

    written = load_price_history(session, instrument, START, END, moex=FakeMoex([]), yahoo=yahoo)

    assert written == 0
    assert _prices(session, instrument) == []


def test_instrument_without_symbol_is_skipped_without_calling_anyone(session):
    instrument = _instrument(session, isin="US87238U2033", ticker="US87238U2033",
                             secid="US87238U2033", currency="USD")
    yahoo = FakeYahoo(YahooHistory(currency="USD", points=[(START, Decimal("1.0000"))]))

    assert load_price_history(session, instrument, START, END, moex=FakeMoex([]), yahoo=yahoo) == 0
    assert yahoo.calls == []


def test_repeated_load_updates_instead_of_duplicating(session):
    """Прогон повторяется, и второй заход обязан оставить одну строку на день:
    ключ таблицы цен — инструмент, дата и источник."""
    instrument = _instrument(session)
    moex = FakeMoex([MoexHistoryPoint(on_date=START, close=Decimal("1350.0000"))])
    load_price_history(session, instrument, START, END, moex=moex, yahoo=FakeYahoo(None))

    moex.points = [MoexHistoryPoint(on_date=START, close=Decimal("1360.0000"))]
    load_price_history(session, instrument, START, END, moex=moex, yahoo=FakeYahoo(None))

    prices = _prices(session, instrument)
    assert len(prices) == 1
    assert prices[0].close == Decimal("1360.0000")
