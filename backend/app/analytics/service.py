from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.instruments import kinds
from app.marketdata.service import latest_prices
from app.models import Account, Instrument, Position, Price
from app.money import money

# Ключи — доменные виды инструментов (app/instruments/kinds.py).
CLASS_BY_KIND = {
    kinds.SHARE: "equity",
    kinds.BOND: "bonds",
    kinds.CURRENCY: "cash",
    kinds.METAL: "gold",
    kinds.FUTURES: "derivatives",
}


@dataclass(frozen=True)
class PositionRow:
    isin: str | None
    ticker: str | None
    name: str
    broker: str
    quantity: Decimal
    average_price: Decimal
    # None — «оценки нет», и это не то же самое, что ноль: у бумаги без
    # котировки стоимость неизвестна, а не равна нулю. Ноль остаётся законным
    # значением для бумаги, которая действительно ничего не стоит (дефолт).
    last_price: Decimal | None
    market_value: Decimal | None
    profit: Decimal | None
    profit_percent: Decimal | None


@dataclass(frozen=True)
class Overview:
    total_value: Decimal
    positions_value: Decimal
    by_asset_class: dict[str, Decimal]
    by_account: dict[str, Decimal]
    as_of: date | None
    # Покрытие оценкой: сколько позиций удалось оценить из скольких всего.
    # Без этой пары главная цифра дашборда может быть посчитана по четверти
    # портфеля и выглядеть при этом совершенно уверенно — с экрана не заметить.
    valued_positions: int
    positions_total: int


def asset_class_of(instrument: Instrument) -> str:
    if instrument.kind == kinds.ETF:
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
        cost = money(position.quantity * position.average_price)

        if last_price is None:
            # Не ноль: «0 ₽» и «0,0%» в таблице читаются как «бумага ничего не
            # стоит», хотя на деле котировки просто нет.
            market_value = None
            profit = None
            percent = None
        else:
            market_value = money(position.quantity * last_price)
            profit = money(market_value - cost)
            percent = money(profit / cost * 100) if cost != 0 else money("0")

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


def _account_labels(accounts_by_id: dict[int, Account]) -> dict[int, str]:
    """Строит подпись для каждого счёта: имя, если оно уникально среди
    участвующих счетов, иначе имя с добавлением внешнего идентификатора —
    имя одно на несколько счетов не редкость (например, коннектор
    Т-Банка подставляет заглушку «Счёт», если брокер имени не дал), а
    уникален только `(broker, external_id)`."""
    name_counts: dict[str, int] = {}
    for account in accounts_by_id.values():
        name_counts[account.name] = name_counts.get(account.name, 0) + 1

    return {
        account_id: account.name
        if name_counts[account.name] == 1
        else f"{account.name} ({account.external_id})"
        for account_id, account in accounts_by_id.items()
    }


def portfolio_overview(session: Session) -> Overview:
    prices = latest_prices(session)
    price_dates = _latest_price_dates(session)
    by_class: dict[str, Decimal] = {}
    by_account_id: dict[int, Decimal] = {}
    accounts_by_id: dict[int, Account] = {}
    total = money("0")
    as_of: date | None = None
    positions_total = 0
    valued_positions = 0

    for position, instrument, account in _rows(session):
        positions_total += 1
        last_price = prices.get(instrument.id)
        if last_price is None:
            # Неоценённая позиция не попадает ни в итог, ни в разбивки — но
            # молча выпасть из ответа она не должна: её считает positions_total,
            # и дашборд обязан показать, что оценены не все.
            continue
        valued_positions += 1
        value = money(position.quantity * last_price)
        total = money(total + value)

        klass = asset_class_of(instrument)
        by_class[klass] = money(by_class.get(klass, money("0")) + value)

        by_account_id[account.id] = money(by_account_id.get(account.id, money("0")) + value)
        accounts_by_id[account.id] = account

        price_date = price_dates.get(instrument.id)
        if price_date is not None and (as_of is None or price_date > as_of):
            as_of = price_date

    labels = _account_labels(accounts_by_id)
    by_account = {labels[account_id]: value for account_id, value in sorted(by_account_id.items())}

    return Overview(
        total_value=total,
        positions_value=total,
        by_asset_class=by_class,
        by_account=by_account,
        # Самая поздняя дата котировки, а не самая ранняя: вопрос, на который
        # она отвечает, — «когда последний раз обновлялись цены». Честность
        # главной цифры обеспечивается признаком покрытия рядом
        # (valued_positions/positions_total), а не сдвигом даты назад.
        as_of=as_of,
        valued_positions=valued_positions,
        positions_total=positions_total,
    )
