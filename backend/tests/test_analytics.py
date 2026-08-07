from datetime import date
from decimal import Decimal

from app.analytics.service import portfolio_overview, position_rows
from app.models import Account, DailySnapshot, Instrument, Position, Price
from app.snapshots.service import take_snapshot


def seed(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    share = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                       kind="share", currency="RUB", issuer="Сбербанк")
    fund = Instrument(isin="RU000A0JXMB2", ticker="TMOS", secid="TMOS",
                      kind="etf", currency="RUB", asset_class="equity")
    bond = Instrument(isin="RU000A101234", ticker="OFZ", secid="OFZ",
                      kind="bond", currency="RUB")
    session.add_all([account, share, fund, bond])
    session.flush()

    session.add_all([
        Position(account_id=account.id, instrument_id=share.id,
                 quantity=Decimal("10"), average_price=Decimal("100")),
        Position(account_id=account.id, instrument_id=fund.id,
                 quantity=Decimal("100"), average_price=Decimal("7")),
        Position(account_id=account.id, instrument_id=bond.id,
                 quantity=Decimal("5"), average_price=Decimal("1000")),
    ])
    session.add_all([
        Price(instrument_id=share.id, on_date=date(2026, 3, 12), close=Decimal("150"), source="moex"),
        Price(instrument_id=fund.id, on_date=date(2026, 3, 12), close=Decimal("8"), source="moex"),
        Price(instrument_id=bond.id, on_date=date(2026, 3, 12), close=Decimal("1010"), source="moex"),
    ])
    session.flush()
    return account


def test_total_value_uses_last_prices(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.positions_value == Decimal("7350.0000")


def test_fund_is_counted_by_its_asset_class(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.by_asset_class["equity"] == Decimal("2300.0000")
    assert overview.by_asset_class["bonds"] == Decimal("5050.0000")
    assert "etf" not in overview.by_asset_class


def test_position_row_computes_profit(session):
    seed(session)
    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["SBER"].market_value == Decimal("1500.0000")
    assert rows["SBER"].profit == Decimal("500.0000")
    assert rows["SBER"].profit_percent == Decimal("50.0000")


def test_position_without_price_has_zero_market_value(session):
    account = seed(session)
    nameless = Instrument(isin="RU000NOPRICE", ticker="NONE", secid=None,
                          kind="share", currency="RUB")
    session.add(nameless)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=nameless.id,
                         quantity=Decimal("1"), average_price=Decimal("50")))
    session.flush()

    rows = {row.ticker: row for row in position_rows(session)}
    assert rows["NONE"].last_price is None
    assert rows["NONE"].market_value == Decimal("0.0000")


def test_snapshot_stores_total_and_breakdown(session):
    seed(session)
    snapshot = take_snapshot(session, date(2026, 3, 12))
    assert snapshot.total_value == Decimal("7350.0000")
    assert snapshot.by_asset_class["equity"] == "2300.0000"


def test_snapshot_same_day_is_overwritten(session):
    seed(session)
    take_snapshot(session, date(2026, 3, 12))
    take_snapshot(session, date(2026, 3, 12))
    assert session.query(DailySnapshot).count() == 1


def test_overview_as_of_uses_max_price_date(session):
    seed(session)
    overview = portfolio_overview(session)
    assert overview.as_of == date(2026, 3, 12)


def test_overview_as_of_prefers_latest_of_mixed_dates(session):
    account = seed(session)
    later = Instrument(isin="RU000LATER01", ticker="LATER", secid="LATER",
                       kind="share", currency="RUB", issuer="Позже")
    session.add(later)
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=later.id,
                         quantity=Decimal("1"), average_price=Decimal("10")))
    session.add(Price(instrument_id=later.id, on_date=date(2026, 3, 15),
                       close=Decimal("20"), source="moex"))
    session.flush()

    overview = portfolio_overview(session)
    assert overview.as_of == date(2026, 3, 15)


def test_overview_as_of_empty_when_no_prices(session):
    overview = portfolio_overview(session)
    assert overview.as_of is None


def test_snapshot_roundtrip_keeps_decimal(session):
    seed(session)
    take_snapshot(session, date(2026, 3, 12))
    session.expire_all()
    stored = session.query(DailySnapshot).filter(DailySnapshot.on_date == date(2026, 3, 12)).one()
    assert stored.by_asset_class["equity"] == "2300.0000"
    assert Decimal(stored.by_asset_class["equity"]) == Decimal("2300.0000")
    assert Decimal(stored.by_account["Брокерский"]) == Decimal("7350.0000")
