from datetime import date
from decimal import Decimal

from app.marketdata.fx import latest_rates, refresh_fx_rates, to_base
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


def test_to_base_returns_none_for_unknown_currency(session):
    """Курса нет — честное «оценки нет». Молчаливое «взять как рубли» завысило
    бы гонконгскую позицию в десять раз."""
    rates = {"RUB": Decimal("1")}

    assert to_base(Decimal("100"), "HKD", rates) is None
    assert to_base(Decimal("100"), "RUB", rates) == Decimal("100.0000")
