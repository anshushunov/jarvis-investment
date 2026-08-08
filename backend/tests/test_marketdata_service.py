import json
from datetime import date
from decimal import Decimal

import httpx

from app.marketdata.service import LatestPrice, latest_prices, refresh_last_prices
from app.models import Instrument, Price


class FakeMoex:
    def __init__(self, prices: dict[str, Decimal | None]) -> None:
        self.prices = prices
        self.calls: list[str] = []
        self.calls_with_market: list[tuple[str, str, str]] = []

    def last_price(self, secid: str, market: str = "shares", engine: str = "stock") -> Decimal | None:
        self.calls.append(secid)
        self.calls_with_market.append((secid, engine, market))
        return self.prices.get(secid)


def add_instrument(session, secid: str) -> Instrument:
    instrument = Instrument(isin=f"RU{secid:0>10}", ticker=secid, secid=secid,
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def test_writes_price_for_each_instrument(session):
    add_instrument(session, "SBER")
    add_instrument(session, "GAZP")
    client = FakeMoex({"SBER": Decimal("314.28"), "GAZP": Decimal("128.10")})

    updated = refresh_last_prices(session, client, date(2026, 3, 12))

    assert updated == 2
    assert sorted(client.calls) == ["GAZP", "SBER"]


def test_missing_price_is_skipped_without_error(session):
    add_instrument(session, "SBER")
    add_instrument(session, "DEAD")
    client = FakeMoex({"SBER": Decimal("314.28"), "DEAD": None})

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 1


def test_second_run_same_day_updates_instead_of_duplicating(session):
    add_instrument(session, "SBER")
    refresh_last_prices(session, FakeMoex({"SBER": Decimal("300")}), date(2026, 3, 12))
    refresh_last_prices(session, FakeMoex({"SBER": Decimal("314.28")}), date(2026, 3, 12))

    rows = session.query(Price).all()
    assert len(rows) == 1
    assert rows[0].close == Decimal("314.2800")


def test_latest_prices_takes_most_recent_date(session):
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 3, 10), close=Decimal("300"), source="moex"),
        Price(instrument_id=instrument.id, on_date=date(2026, 3, 12), close=Decimal("314.28"), source="moex"),
    ])
    session.flush()

    # Цена и её дата приходят одним проходом: аналитике нужны обе, и раньше
    # она ради даты делала второй такой же оконный запрос.
    assert latest_prices(session) == {
        instrument.id: LatestPrice(close=Decimal("314.2800"), on_date=date(2026, 3, 12))
    }


def test_instrument_without_secid_is_not_requested(session):
    instrument = Instrument(isin="RU000MANUAL1", ticker=None, secid=None,
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    client = FakeMoex({})

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 0
    assert client.calls == []


class FlakyMoex:
    """Один инструмент падает с сетевой/HTTP ошибкой, остальные — как обычно."""

    def __init__(self, prices: dict[str, Decimal | None], broken: set[str]) -> None:
        self.prices = prices
        self.broken = broken
        self.calls: list[str] = []

    def last_price(self, secid: str, market: str = "shares", engine: str = "stock") -> Decimal | None:
        self.calls.append(secid)
        if secid in self.broken:
            raise httpx.HTTPStatusError("boom", request=None, response=None)
        return self.prices.get(secid)


def test_one_instrument_failure_does_not_abort_the_whole_run(session, caplog):
    add_instrument(session, "SBER")
    add_instrument(session, "GAZP")
    client = FlakyMoex({"SBER": Decimal("314.28"), "GAZP": Decimal("128.10")}, broken={"GAZP"})

    with caplog.at_level("WARNING"):
        updated = refresh_last_prices(session, client, date(2026, 3, 12))

    assert updated == 1
    assert sorted(client.calls) == ["GAZP", "SBER"]
    rows = session.query(Price).all()
    assert len(rows) == 1
    assert rows[0].close == Decimal("314.2800")
    assert any("GAZP" in record.getMessage() for record in caplog.records)


def test_currency_instrument_is_requested_on_currency_engine(session):
    instrument = Instrument(isin="RU000CURR001", ticker="USD000UTSTOM", secid="USD000UTSTOM",
                            kind="currency", currency="RUB")
    session.add(instrument)
    session.flush()
    client = FakeMoex({"USD000UTSTOM": Decimal("92.5")})

    updated = refresh_last_prices(session, client, date(2026, 3, 12))

    assert updated == 1
    assert client.calls_with_market == [("USD000UTSTOM", "currency", "selt")]


class BrokenBodyMoex:
    """ISS вернул тело, которое нельзя разобрать как JSON."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def last_price(self, secid: str, market: str = "shares", engine: str = "stock") -> Decimal | None:
        self.calls.append(secid)
        json.loads("not-json")
        return None


def test_broken_iss_response_body_is_skipped_without_error(session, caplog):
    add_instrument(session, "SBER")
    client = BrokenBodyMoex()

    with caplog.at_level("WARNING"):
        updated = refresh_last_prices(session, client, date(2026, 3, 12))

    assert updated == 0
    assert client.calls == ["SBER"]
    assert any("SBER" in record.getMessage() for record in caplog.records)
