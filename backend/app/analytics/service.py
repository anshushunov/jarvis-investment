from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.instruments import kinds
from app.marketdata.service import latest_prices
from app.models import Account, Instrument, Position
from app.money import money

# Ключи — доменные виды инструментов (app/instruments/kinds.py).
CLASS_BY_KIND = {
    kinds.SHARE: "equity",
    kinds.BOND: "bonds",
    kinds.CURRENCY: "cash",
    kinds.METAL: "gold",
    kinds.FUTURES: "derivatives",
}

# Базовая валюта портфеля. Совокупный капитал и все разбивки считаются только
# по рублёвой части: суммировать позиции в USD, HKD и CNY с рублёвыми без
# пересчёта по курсам — значит молча завышать капитал. Полноценный пересчёт по
# курсам — отдельная задача следующей фазы; до неё валюты, отличные от базовой,
# показываются собственными итогами (Overview.by_currency), а не вливаются в
# рублёвый.
BASE_CURRENCY = "RUB"


@dataclass(frozen=True)
class PositionRow:
    isin: str | None
    ticker: str | None
    name: str
    broker: str
    # Счёт, на котором лежит позиция. Один и тот же тикер на пяти счетах
    # одного брокера давал пять визуально одинаковых строк, различить которые
    # было нечем. Идентификатор, а не подпись: подпись строится при чтении.
    account_id: int
    # Валюта, в которой номинирована бумага: и средняя, и текущая цена, и
    # стоимость позиции — в ней, а не в рублях. Без неё интерфейс дописывал
    # знак рубля к суммам в USD, HKD и CNY.
    currency: str
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
    # Только рублёвая часть — см. BASE_CURRENCY.
    total_value: Decimal
    positions_value: Decimal
    # Разбивки считаются по той же рублёвой части, чтобы сходиться с итогом.
    by_asset_class: dict[str, Decimal]
    # Ключ — идентификатор счёта, а не подпись: подпись строится при чтении
    # (app/accounts/labels.py), одной функцией на весь проект. Раньше здесь
    # была подпись, и она же уезжала ключом в постоянное хранилище — появление
    # второго счёта с тем же именем меняло ключ, и исторические снимки
    # переставали склеиваться по счёту.
    by_account: dict[int, Decimal]
    # Итог по каждой валюте, включая рублёвую (by_currency[BASE_CURRENCY] ==
    # total_value). Складывать эти суммы между собой нельзя — это разные деньги.
    by_currency: dict[str, Decimal]
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


def _currency_of(instrument: Instrument) -> str:
    return (instrument.currency or BASE_CURRENCY).upper()


def position_rows(session: Session) -> list[PositionRow]:
    prices = latest_prices(session)
    result: list[PositionRow] = []

    for position, instrument, account in _rows(session):
        latest = prices.get(instrument.id)
        last_price = latest.close if latest is not None else None
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
                account_id=account.id,
                currency=_currency_of(instrument),
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
    # Один проход по таблице цен на весь показ дашборда: цена и её дата
    # приходят вместе (см. LatestPrice в app/marketdata/service.py).
    prices = latest_prices(session)
    by_class: dict[str, Decimal] = {}
    by_account_id: dict[int, Decimal] = {}
    by_currency: dict[str, Decimal] = {}
    total = money("0")
    as_of: date | None = None
    positions_total = 0
    valued_positions = 0

    for position, instrument, account in _rows(session):
        positions_total += 1
        latest = prices.get(instrument.id)
        if latest is None:
            # Неоценённая позиция не попадает ни в итог, ни в разбивки — но
            # молча выпасть из ответа она не должна: её считает positions_total,
            # и дашборд обязан показать, что оценены не все.
            continue
        valued_positions += 1
        value = money(position.quantity * latest.close)

        # Дата актуальности — по всем оценённым позициям, независимо от валюты:
        # она про свежесть котировок, а не про состав рублёвого итога.
        if as_of is None or latest.on_date > as_of:
            as_of = latest.on_date

        currency = _currency_of(instrument)
        by_currency[currency] = money(by_currency.get(currency, money("0")) + value)
        if currency != BASE_CURRENCY:
            # В рублёвый итог и рублёвые разбивки не идёт: без пересчёта по
            # курсу это было бы сложением разных денег под знаком рубля.
            continue

        total = money(total + value)

        klass = asset_class_of(instrument)
        by_class[klass] = money(by_class.get(klass, money("0")) + value)

        by_account_id[account.id] = money(by_account_id.get(account.id, money("0")) + value)

    return Overview(
        total_value=total,
        positions_value=total,
        by_asset_class=by_class,
        by_account=dict(sorted(by_account_id.items())),
        by_currency=dict(sorted(by_currency.items())),
        # Самая поздняя дата котировки, а не самая ранняя: вопрос, на который
        # она отвечает, — «когда последний раз обновлялись цены». Честность
        # главной цифры обеспечивается признаком покрытия рядом
        # (valued_positions/positions_total), а не сдвигом даты назад.
        as_of=as_of,
        valued_positions=valued_positions,
        positions_total=positions_total,
    )
