import json
from datetime import date, timedelta
from decimal import Decimal

import httpx

from app.marketdata.moex import MoexQuote
from app.marketdata.service import (
    MOEX_SOURCE,
    PRICE_MAX_AGE,
    TBANK_SOURCE,
    LatestPrice,
    prices_as_of,
    refresh_last_prices,
)
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
        Price(instrument_id=instrument.id, on_date=date(2026, 3, 10), close=Decimal("300"),
              currency="RUB", source=MOEX_SOURCE),
        Price(instrument_id=instrument.id, on_date=date(2026, 3, 12), close=Decimal("314.28"),
              currency="RUB", source=MOEX_SOURCE),
    ])
    session.flush()

    # Цена, её дата, валюта и источник приходят одним проходом: аналитике
    # нужны все четыре, и раньше она ради даты делала второй такой же оконный
    # запрос.
    assert prices_as_of(session, date(2026, 3, 12)) == {
        instrument.id: LatestPrice(close=Decimal("314.2800"), on_date=date(2026, 3, 12),
                                   currency="RUB", source=MOEX_SOURCE)
    }


def _price(session, instrument, on_date, close, source=MOEX_SOURCE, currency="RUB") -> None:
    session.add(Price(instrument_id=instrument.id, on_date=on_date, close=close,
                      currency=currency, source=source))
    session.flush()


def test_price_of_the_day_ignores_later_quotes(session):
    """Точка истории обязана считаться ценой своего дня: завтрашняя котировка
    в ней — это знание из будущего, от которого график поедет вверх ровно там,
    где рынок падал."""
    instrument = add_instrument(session, "SBER")
    _price(session, instrument, date(2024, 6, 3), Decimal("100.0000"))
    _price(session, instrument, date(2024, 6, 5), Decimal("120.0000"))

    prices = prices_as_of(session, date(2024, 6, 4))

    assert prices[instrument.id].close == Decimal("100.0000")
    assert prices[instrument.id].on_date == date(2024, 6, 3)


def test_price_older_than_the_limit_is_not_a_price(session):
    """Бумага не торговалась две недели — цены на дату нет. Показать
    двухнедельную как сегодняшнюю значит выдать остановку торгов за факт."""
    instrument = add_instrument(session, "SBER")
    _price(session, instrument, date(2024, 6, 3), Decimal("100.0000"))

    assert prices_as_of(session, date(2024, 6, 3) + PRICE_MAX_AGE + timedelta(days=1)) == {}


def test_price_within_the_limit_survives_a_weekend(session):
    instrument = add_instrument(session, "SBER")
    _price(session, instrument, date(2024, 6, 3), Decimal("100.0000"))

    prices = prices_as_of(session, date(2024, 6, 3) + PRICE_MAX_AGE)

    assert prices[instrument.id].close == Decimal("100.0000")


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


def test_moex_price_of_share_is_in_roubles(session):
    """MOEX котирует акции и фонды в рублях всегда — валюта цены не зависит от
    валюты инструмента."""
    add_instrument(session, "SBER")
    refresh_last_prices(session, FakeMoex({"SBER": Decimal("314.28")}), date(2026, 3, 12))

    stored = session.query(Price).one()
    assert stored.currency == "RUB"
    assert stored.source == MOEX_SOURCE


def test_bond_with_foreign_face_value_is_priced_in_that_currency(session):
    """Замещающая облигация котируется в процентах от номинала, номинал — в
    юанях. Раньше такая бумага оставалась неоценённой вовсе: пересчитать её без
    курсов было нельзя, а рублёвое число под видом оценки хуже честного «цены
    нет». Курсы теперь есть."""
    add_bond(session, "RU000A1054W1")
    client = FakeMoex({"RU000A1054W1": Decimal("96.92")},
                      face_values={"RU000A1054W1": (Decimal("1000"), "CNY")})

    refresh_last_prices(session, client, date(2026, 8, 9))

    stored = session.query(Price).one()
    assert stored.close == Decimal("969.2000")
    assert stored.currency == "CNY"


def test_two_sources_coexist_for_the_same_day(session):
    """Ключ уникальности включает источник: цена брокера не затирает биржевую,
    иначе выбор между ними зависел бы от того, кто записался последним."""
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("314.28"), currency="RUB", source=MOEX_SOURCE),
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("315.00"), currency="RUB", source=TBANK_SOURCE),
    ])
    session.flush()

    assert session.query(Price).count() == 2


def test_moex_wins_over_broker_on_the_same_day(session):
    """Биржа — независимый источник, брокер — тот, с кем мы сверяемся. При
    равной свежести берётся биржевая цена."""
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("314.28"), currency="RUB", source=MOEX_SOURCE),
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("315.00"), currency="RUB", source=TBANK_SOURCE),
    ])
    session.flush()

    latest = prices_as_of(session, date(2026, 8, 9))[instrument.id]

    assert latest.close == Decimal("314.28")
    assert latest.source == MOEX_SOURCE


def test_fresher_broker_price_beats_stale_exchange_price(session):
    """Свежесть важнее происхождения: вчерашняя биржевая цена хуже сегодняшней
    брокерской, потому что оценка отвечает на вопрос «сколько стоит сейчас»."""
    instrument = add_instrument(session, "SBER")
    session.add_all([
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 8),
              close=Decimal("310.00"), currency="RUB", source=MOEX_SOURCE),
        Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
              close=Decimal("315.00"), currency="RUB", source=TBANK_SOURCE),
    ])
    session.flush()

    latest = prices_as_of(session, date(2026, 8, 9))[instrument.id]

    assert latest.close == Decimal("315.00")
    assert latest.source == TBANK_SOURCE


def test_price_of_foreign_instrument_is_no_longer_filtered_out(session):
    """Раньше цена инструмента, номинированного не в рубле, отбрасывалась при
    чтении: пересчитать её было нечем. Теперь валюта хранится у самой цены и
    пересчёт есть, поэтому отбрасывать нечего."""
    instrument = Instrument(isin="HK0000009866", ticker="9866", secid="9866",
                            kind="share", currency="HKD")
    session.add(instrument)
    session.flush()
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 8, 9),
                      close=Decimal("36.90"), currency="HKD", source=TBANK_SOURCE))
    session.flush()

    latest = prices_as_of(session, date(2026, 8, 9))[instrument.id]

    assert latest.currency == "HKD"
