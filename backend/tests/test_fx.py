from datetime import date
from decimal import Decimal

from app.marketdata.fx import (
    latest_rate_date,
    latest_rates,
    refresh_fx_rates,
    refresh_metal_rates,
    to_base,
)
from app.marketdata.moex import MoexQuote
from app.models import FxRate


class FakeCbr:
    def __init__(self, effective: date, rates: dict[str, Decimal]) -> None:
        self.effective = effective
        self.rates_by_code = rates
        self.calls: list[date] = []

    def rates(self, on_date: date) -> tuple[date, dict[str, Decimal]]:
        self.calls.append(on_date)
        return self.effective, self.rates_by_code


def test_stores_rates_under_effective_date(session):
    client = FakeCbr(date(2026, 8, 8), {"USD": Decimal("82.1665"), "HKD": Decimal("10.4724")})

    written = refresh_fx_rates(session, client, date(2026, 8, 9))

    assert written == 2
    stored = session.query(FxRate).order_by(FxRate.currency).all()
    assert [(r.currency, r.on_date, r.source) for r in stored] == [
        ("HKD", date(2026, 8, 8), "cbr"),
        ("USD", date(2026, 8, 8), "cbr"),
    ]


def test_second_run_updates_instead_of_duplicating(session):
    client = FakeCbr(date(2026, 8, 8), {"USD": Decimal("82.1665")})
    refresh_fx_rates(session, client, date(2026, 8, 9))

    client.rates_by_code = {"USD": Decimal("83.0000")}
    refresh_fx_rates(session, client, date(2026, 8, 9))

    stored = session.query(FxRate).all()
    assert len(stored) == 1
    assert stored[0].rate == Decimal("83.00000000")


def test_latest_rates_take_newest_on_or_before_date(session):
    session.add_all([
        FxRate(currency="USD", on_date=date(2026, 8, 6), rate=Decimal("80"), source="cbr"),
        FxRate(currency="USD", on_date=date(2026, 8, 8), rate=Decimal("82"), source="cbr"),
        FxRate(currency="USD", on_date=date(2026, 8, 12), rate=Decimal("85"), source="cbr"),
    ])
    session.flush()

    rates = latest_rates(session, date(2026, 8, 10))

    assert rates["USD"] == Decimal("82")


def test_rouble_needs_no_stored_rate(session):
    """Единица для рубля подставляется всегда: без неё рублёвые суммы
    оставались бы непересчитанными ровно в тот день, когда ЦБ недоступен."""
    assert latest_rates(session, date(2026, 8, 10))["RUB"] == Decimal("1")


def test_latest_rate_date_is_none_when_no_rates(session):
    assert latest_rate_date(session, date(2026, 8, 10)) is None


def test_latest_rate_date_is_the_freshest_on_or_before(session):
    """Дата курсов — своя, отдельная от даты котировок: ЦБ публикует раз в
    сутки, а по выходным не публикует вовсе, и «данные на» у курсов сдвинуто
    назад относительно цен."""
    session.add_all([
        FxRate(currency="USD", on_date=date(2026, 8, 6), rate=Decimal("80"), source="cbr"),
        FxRate(currency="HKD", on_date=date(2026, 8, 8), rate=Decimal("10"), source="cbr"),
        FxRate(currency="USD", on_date=date(2026, 8, 12), rate=Decimal("85"), source="cbr"),
    ])
    session.flush()

    assert latest_rate_date(session, date(2026, 8, 10)) == date(2026, 8, 8)


def test_to_base_returns_none_for_unknown_currency(session):
    """Курса нет — честное «оценки нет». Молчаливое «взять как рубли» завысило
    бы гонконгскую позицию в десять раз."""
    rates = {"RUB": Decimal("1")}

    assert to_base(Decimal("100"), "HKD", rates) is None
    assert to_base(Decimal("100"), "RUB", rates) == Decimal("100.0000")


class FakeMoexForMetals:
    def __init__(self, prices: dict[str, Decimal | None]) -> None:
        self.prices = prices
        self.calls: list[tuple[str, str, str]] = []

    def quote(self, secid: str, market: str = "shares", engine: str = "stock") -> MoexQuote:
        self.calls.append((secid, engine, market))
        return MoexQuote(price=self.prices.get(secid))


def test_gold_rate_comes_from_moex(session):
    """У ЦБ в XML_daily драгоценных металлов нет, а в денежных остатках
    Т-Банка золото лежит наравне с валютами — 10 граммов под кодом xau."""
    client = FakeMoexForMetals({"GLDRUB_TOM": Decimal("11410")})

    written = refresh_metal_rates(session, client, date(2026, 8, 9))

    assert written == 1
    assert client.calls == [("GLDRUB_TOM", "currency", "selt")]
    assert latest_rates(session, date(2026, 8, 9))["XAU"] == Decimal("11410")
    assert session.query(FxRate).one().source == "moex"


def test_metal_without_quote_is_skipped(session):
    """Нет котировки — нет строки курса. Позиция в золоте останется
    неоценённой, и это честнее нуля."""
    written = refresh_metal_rates(session, FakeMoexForMetals({}), date(2026, 8, 9))

    assert written == 0
    assert "XAU" not in latest_rates(session, date(2026, 8, 9))
