from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.marketdata.service import latest_prices
from app.models import Account, Instrument, Position, Price
from app.money import money

CLASS_BY_KIND = {
    "share": "equity",
    "bond": "bonds",
    "currency": "cash",
    "metal": "gold",
    "futures": "derivatives",
}


@dataclass(frozen=True)
class PositionRow:
    isin: str | None
    ticker: str | None
    name: str
    broker: str
    quantity: Decimal
    average_price: Decimal
    last_price: Decimal | None
    market_value: Decimal
    profit: Decimal
    profit_percent: Decimal


@dataclass(frozen=True)
class Overview:
    total_value: Decimal
    positions_value: Decimal
    by_asset_class: dict[str, Decimal]
    by_account: dict[str, Decimal]
    as_of: date | None


def asset_class_of(instrument: Instrument) -> str:
    if instrument.kind == "etf":
        return instrument.asset_class or "mixed"
    return CLASS_BY_KIND.get(instrument.kind, "other")


def _rows(session: Session):
    return session.execute(
        select(Position, Instrument, Account)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .join(Account, Position.account_id == Account.id)
    ).all()


def _latest_price_dates(session: Session) -> dict[int, date]:
    ranked = select(
        Price.instrument_id,
        Price.on_date,
        func.row_number().over(
            partition_by=Price.instrument_id, order_by=Price.on_date.desc()
        ).label("rn"),
    ).subquery()

    rows = session.execute(
        select(ranked.c.instrument_id, ranked.c.on_date).where(ranked.c.rn == 1)
    ).all()
    return {instrument_id: on_date for instrument_id, on_date in rows}


def position_rows(session: Session) -> list[PositionRow]:
    prices = latest_prices(session)
    result: list[PositionRow] = []

    for position, instrument, account in _rows(session):
        last_price = prices.get(instrument.id)
        market_value = money(position.quantity * last_price) if last_price else money("0")
        cost = money(position.quantity * position.average_price)
        profit = money(market_value - cost) if last_price else money("0")
        percent = money(profit / cost * 100) if last_price and cost != 0 else money("0")

        result.append(
            PositionRow(
                isin=instrument.isin,
                ticker=instrument.ticker,
                name=instrument.issuer or instrument.ticker or instrument.isin or "—",
                broker=account.broker,
                quantity=position.quantity,
                average_price=position.average_price,
                last_price=last_price,
                market_value=market_value,
                profit=profit,
                profit_percent=percent,
            )
        )
    return result


def portfolio_overview(session: Session) -> Overview:
    prices = latest_prices(session)
    price_dates = _latest_price_dates(session)
    by_class: dict[str, Decimal] = {}
    by_account: dict[str, Decimal] = {}
    total = money("0")
    as_of: date | None = None

    for position, instrument, account in _rows(session):
        last_price = prices.get(instrument.id)
        if last_price is None:
            continue
        value = money(position.quantity * last_price)
        total = money(total + value)

        klass = asset_class_of(instrument)
        by_class[klass] = money(by_class.get(klass, money("0")) + value)
        by_account[account.name] = money(by_account.get(account.name, money("0")) + value)

        price_date = price_dates.get(instrument.id)
        if price_date is not None and (as_of is None or price_date > as_of):
            as_of = price_date

    return Overview(
        total_value=total,
        positions_value=total,
        by_asset_class=by_class,
        by_account=by_account,
        as_of=as_of,
    )
