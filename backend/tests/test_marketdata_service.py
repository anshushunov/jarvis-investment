import json
from datetime import date
from decimal import Decimal

import httpx

from app.marketdata.moex import MoexQuote
from app.marketdata.service import LatestPrice, latest_prices, refresh_last_prices
from app.models import Instrument, Price


class FakeMoex:
    def __init__(
        self,
        prices: dict[str, Decimal | None],
        face_values: dict[str, tuple[Decimal, str]] | None = None,
    ) -> None:
        self.prices = prices
        self.face_values = face_values or {}
        self.calls: list[str] = []
        self.calls_with_market: list[tuple[str, str, str]] = []

    def quote(self, secid: str, market: str = "shares", engine: str = "stock") -> MoexQuote:
        self.calls.append(secid)
        self.calls_with_market.append((secid, engine, market))
        face_value, face_unit = self.face_values.get(secid, (None, None))
        return MoexQuote(price=self.prices.get(secid), face_value=face_value, face_unit=face_unit)


def add_bond(session, secid: str) -> Instrument:
    instrument = Instrument(isin=secid, ticker=secid, secid=secid, kind="bond", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


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


def test_bond_price_is_converted_from_percent_of_face_value(session):
    """MOEX котирует облигации в процентах от номинала, а позиция считается в
    деньгах. Без пересчёта облигация с номиналом 1000 ₽ оценивалась в сотню
    рублей — портфель облигаций на миллионы показывался десятками тысяч."""
    add_bond(session, "RU000A10EJQ7")
    client = FakeMoex(
        {"RU000A10EJQ7": Decimal("100.19")},
        face_values={"RU000A10EJQ7": (Decimal("1000"), "SUR")},
    )

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 1
    assert session.query(Price).one().close == Decimal("1001.9000")


def test_bond_with_foreign_face_value_is_left_unvalued(session):
    """Замещающая облигация: номинал в долларах, котировка в процентах, расчёты
    в рублях. Пересчитать её без курсов нельзя, а рублёвое число под видом
    оценки хуже честного «цены нет»."""
    add_bond(session, "RU000A107VV1")
    client = FakeMoex(
        {"RU000A107VV1": Decimal("99")},
        face_values={"RU000A107VV1": (Decimal("1000"), "USD")},
    )

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 0
    assert session.query(Price).count() == 0


def test_bond_without_face_value_is_left_unvalued(session):
    add_bond(session, "RU000NOFACE")
    client = FakeMoex({"RU000NOFACE": Decimal("99")})

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 0


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

    def quote(self, secid: str, market: str = "shares", engine: str = "stock") -> MoexQuote:
        self.calls.append(secid)
        if secid in self.broken:
            raise httpx.HTTPStatusError("boom", request=None, response=None)
        return MoexQuote(price=self.prices.get(secid))


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


def test_non_ruble_instrument_is_not_requested_from_moex(session):
    """MOEX ISS отдаёт котировки в рублях. Для гонконгской бумаги такая цена —
    не оценка: рублёвое число под знаком HK$ выглядит правдой, но ею не
    является, а пересчёта по курсам в этой фазе нет."""
    session.add(Instrument(isin="KYG875721634", ticker="700", secid="700",
                           kind="share", currency="HKD"))
    session.flush()
    client = FakeMoex({"700": Decimal("300")})

    assert refresh_last_prices(session, client, date(2026, 3, 12)) == 0
    assert client.calls == []


def test_ruble_price_of_a_non_ruble_instrument_is_not_used_for_valuation(session):
    """Фильтр стоит не только на загрузке: в базе могли остаться котировки,
    записанные до того, как валюта инструмента была исправлена по справочнику
    брокера."""
    stale = Instrument(isin="KYG875721634", ticker="700", secid="700",
                       kind="share", currency="HKD")
    session.add(stale)
    session.flush()
    session.add(Price(instrument_id=stale.id, on_date=date(2026, 3, 12),
                      close=Decimal("300"), source="moex"))
    session.flush()

    assert latest_prices(session) == {}


def test_price_from_another_source_is_kept_for_a_non_ruble_instrument(session):
    """Правило про рубли — про котировки MOEX, а не про валютные инструменты
    вообще: курсовой источник, когда он появится, под него не подпадает."""
    foreign = Instrument(isin="KYG875721634", ticker="700", secid="700",
                         kind="share", currency="HKD")
    session.add(foreign)
    session.flush()
    session.add(Price(instrument_id=foreign.id, on_date=date(2026, 3, 12),
                      close=Decimal("300"), source="manual"))
    session.flush()

    assert latest_prices(session) == {
        foreign.id: LatestPrice(close=Decimal("300.0000"), on_date=date(2026, 3, 12))
    }


class BrokenBodyMoex:
    """ISS вернул тело, которое нельзя разобрать как JSON."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def quote(self, secid: str, market: str = "shares", engine: str = "stock") -> MoexQuote:
        self.calls.append(secid)
        json.loads("not-json")
        return MoexQuote(price=None)


def test_broken_iss_response_body_is_skipped_without_error(session, caplog):
    add_instrument(session, "SBER")
    client = BrokenBodyMoex()

    with caplog.at_level("WARNING"):
        updated = refresh_last_prices(session, client, date(2026, 3, 12))

    assert updated == 0
    assert client.calls == ["SBER"]
    assert any("SBER" in record.getMessage() for record in caplog.records)
