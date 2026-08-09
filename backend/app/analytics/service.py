from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cash import cash_by_account
from app.analytics.valuation import value_position
from app.instruments import kinds
from app.marketdata.fx import latest_rate_date, latest_rates, to_base
from app.marketdata.service import latest_prices
from app.models import Account, Instrument, Position
from app.money import BASE_CURRENCY, money
from app.sync.holdings import blocked_by_instrument
from app.timeutils import moscow_today

# Ключи — доменные виды инструментов (app/instruments/kinds.py).
CLASS_BY_KIND = {
    kinds.SHARE: "equity",
    kinds.BOND: "bonds",
    kinds.CURRENCY: "cash",
    kinds.METAL: "gold",
    kinds.FUTURES: "derivatives",
}

# Классы активов для денежных остатков. Драгоценные металлы приходят от брокера
# валютными кодами (XAU — золото в граммах), но деньгами не являются: их место
# в аллокации — металлы, иначе портфель с граммом золота выглядит как портфель
# с наличными.
METAL_CURRENCIES = {"XAU": "gold", "XAG": "silver", "XPT": "platinum", "XPD": "palladium"}
CASH_CLASS = "cash"


def cash_asset_class(currency: str) -> str:
    return METAL_CURRENCIES.get(currency.upper(), CASH_CLASS)

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
    # Стоимость позиции в рублях. None, когда цена есть, а курса нет: тогда
    # market_value в валюте показать можно, а в рублёвый итог позиция не войдёт.
    value_base: Decimal | None
    # Метка источника цены: биржа или брокер. Оценка по данным брокера не
    # независима — это видно на экране, а не только в базе.
    price_source: str | None
    # Заблокированная часть количества по данным брокера (broker_holding).
    blocked: Decimal
    # Бумагой нельзя распорядиться вовсе: брокер не даёт ни купить, ни продать
    # (Instrument.trading_restricted). Причина другая, чем у blocked, и обе
    # встречаются по отдельности.
    restricted: bool
    profit: Decimal | None
    profit_percent: Decimal | None


@dataclass(frozen=True)
class Overview:
    # Весь капитал в рублях: бумаги плюс деньги, всё пересчитано по курсам.
    # Позиция, для которой нет цены или нет курса, в итог не входит и считается
    # неоценённой — см. valued_positions.
    total_value: Decimal
    # Из чего он складывается. Раньше поле под стоимость бумаг было дословным
    # дублем итога и потому убрано из контракта; с приходом денег оно перестало
    # им быть.
    securities_value: Decimal
    cash_value: Decimal
    # Часть капитала, которой нельзя распорядиться: заблокированные брокером
    # количества плюс бумаги, ограниченные в обороте. Входит в total_value, а
    # не вычитается из него — брокер считает так же, и капитал обязан с ним
    # сходиться. Отдельная цифра отвечает на другой вопрос: сколько из этих
    # денег реально доступно.
    restricted_value: Decimal
    # Разбивки считаются по той же оценённой в рублях части, чтобы сходиться
    # с итогом.
    by_asset_class: dict[str, Decimal]
    # Ключ — идентификатор счёта, а не подпись: подпись строится при чтении
    # (app/accounts/labels.py), одной функцией на весь проект. Раньше здесь
    # была подпись, и она же уезжала ключом в постоянное хранилище — появление
    # второго счёта с тем же именем меняло ключ, и исторические снимки
    # переставали склеиваться по счёту.
    by_account: dict[int, Decimal]
    # Итог по каждой валюте в ней самой, без пересчёта: сколько именно
    # гонконгских долларов в портфеле. Складывать между собой нельзя.
    by_currency: dict[str, Decimal]
    # Валюты всех позиций портфеля — независимо от того, удалось ли их оценить.
    # Отвечает на вопрос «портфель вообще только рублёвый?», на который
    # by_currency ответить не может: позиция без котировки в него не попадает
    # вовсе, а валютой при этом обладает.
    position_currencies: list[str]
    as_of: date | None
    # Дата курсов, по которым сделан пересчёт. Отдельно от as_of: котировки
    # обновляются каждые пятнадцать минут, курсы — раз в сутки, и несвежесть у
    # них разная.
    fx_as_of: date | None
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
    rates = latest_rates(session, moscow_today())
    blocked = blocked_by_instrument(session)
    result: list[PositionRow] = []

    for position, instrument, account in _rows(session):
        valued = value_position(position.quantity, prices.get(instrument.id), rates)
        cost = money(position.quantity * position.average_price)

        if valued.value is None:
            # Не ноль: «0 ₽» и «0,0%» в таблице читаются как «бумага ничего не
            # стоит», хотя на деле котировки просто нет.
            profit = None
            percent = None
        else:
            profit = money(valued.value - cost)
            # По модулю себестоимости: у короткой позиции количество, а с ним и
            # себестоимость отрицательные, и деление на неё как есть перевернуло
            # бы знак доходности — заработок на шорте показывался бы убытком.
            percent = money(profit / abs(cost) * 100) if cost != 0 else money("0")

        result.append(
            PositionRow(
                isin=instrument.isin,
                ticker=instrument.ticker,
                name=instrument.issuer or instrument.ticker or instrument.isin or "—",
                broker=account.broker,
                account_id=account.id,
                # Валюта строки — валюта цены, а не справочника: у замещающей
                # облигации справочник брокера говорит «рубли» (расчёты по ней
                # рублёвые), а котируется она в юанях.
                currency=valued.currency or _currency_of(instrument),
                quantity=position.quantity,
                average_price=position.average_price,
                last_price=valued.price,
                market_value=valued.value,
                value_base=valued.value_base,
                price_source=valued.price_source,
                blocked=blocked.get((account.id, instrument.id), Decimal("0")),
                restricted=instrument.trading_restricted,
                profit=profit,
                profit_percent=percent,
            )
        )
    return result


def portfolio_overview(session: Session) -> Overview:
    # Один проход по таблице цен на весь показ дашборда: цена, её валюта и её
    # дата приходят вместе (см. LatestPrice в app/marketdata/service.py).
    prices = latest_prices(session)
    rates = latest_rates(session, moscow_today())
    blocked = blocked_by_instrument(session)

    by_class: dict[str, Decimal] = {}
    by_account_id: dict[int, Decimal] = {}
    by_currency: dict[str, Decimal] = {}
    position_currencies: set[str] = set()
    securities = money("0")
    restricted_value = money("0")
    as_of: date | None = None
    positions_total = 0
    valued_positions = 0

    for position, instrument, account in _rows(session):
        positions_total += 1
        latest = prices.get(instrument.id)
        valued = value_position(position.quantity, latest, rates)
        position_currencies.add(valued.currency or _currency_of(instrument))

        if valued.value is not None and latest is not None:
            currency = valued.currency or _currency_of(instrument)
            by_currency[currency] = money(by_currency.get(currency, money("0")) + valued.value)
            # Дата актуальности — по всем позициям, у которых есть цена,
            # независимо от того, удалось ли перевести её в рубли: она про
            # свежесть котировок.
            if as_of is None or latest.on_date > as_of:
                as_of = latest.on_date

        if valued.value_base is None:
            # Неоценённая позиция не попадает ни в итог, ни в разбивки — но
            # молча выпасть из ответа она не должна: её считает positions_total,
            # и дашборд обязан показать, что оценены не все.
            continue

        valued_positions += 1
        securities = money(securities + valued.value_base)

        klass = asset_class_of(instrument)
        by_class[klass] = money(by_class.get(klass, money("0")) + valued.value_base)
        by_account_id[account.id] = money(
            by_account_id.get(account.id, money("0")) + valued.value_base
        )

        # Недоступная часть позиции. Две причины дают её по-разному: бумага,
        # ограниченная в обороте, недоступна целиком, а заблокированное
        # количество — только своей долей. Когда верно и то и другое,
        # ограничение бумаги поглощает блокировку количества, и складывать их
        # нельзя — получится больше, чем сама позиция.
        blocked_quantity = blocked.get((account.id, instrument.id), Decimal("0"))
        if instrument.trading_restricted:
            restricted_value = money(restricted_value + valued.value_base)
        elif blocked_quantity and position.quantity != 0:
            # Доля по количеству: цена у заблокированной и свободной части одна
            # и та же бумага.
            restricted_value = money(
                restricted_value + valued.value_base * blocked_quantity / position.quantity
            )

    cash_total = money("0")
    for account_id, balances in cash_by_account(session).items():
        for currency, amount in balances.items():
            in_base = to_base(amount, currency, rates)
            if in_base is None:
                # Курса нет — остаток в капитал не входит, но в разбивке по
                # валютам виден: иначе он исчезает бесследно.
                by_currency[currency] = money(by_currency.get(currency, money("0")) + amount)
                continue
            cash_total = money(cash_total + in_base)
            by_currency[currency] = money(by_currency.get(currency, money("0")) + amount)
            klass = cash_asset_class(currency)
            by_class[klass] = money(by_class.get(klass, money("0")) + in_base)
            by_account_id[account_id] = money(
                by_account_id.get(account_id, money("0")) + in_base
            )

    return Overview(
        total_value=money(securities + cash_total),
        securities_value=securities,
        cash_value=cash_total,
        restricted_value=restricted_value,
        by_asset_class=by_class,
        by_account=dict(sorted(by_account_id.items())),
        by_currency=dict(sorted(by_currency.items())),
        position_currencies=sorted(position_currencies),
        # Самая поздняя дата котировки, а не самая ранняя: вопрос, на который
        # она отвечает, — «когда последний раз обновлялись цены». Честность
        # главной цифры обеспечивается признаком покрытия рядом
        # (valued_positions/positions_total), а не сдвигом даты назад.
        as_of=as_of,
        fx_as_of=latest_rate_date(session, moscow_today()),
        valued_positions=valued_positions,
        positions_total=positions_total,
    )
