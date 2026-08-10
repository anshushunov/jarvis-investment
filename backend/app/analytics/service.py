from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cash import blocked_cash_by_account, cash_by_account
from app.analytics.valuation import value_position
from app.instruments import kinds
from app.marketdata.fx import latest_rate_dates, latest_rates, to_base
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
    # Валюта средней цены — валюта расчётов по бумаге из справочника брокера, и
    # она не обязана совпадать с `currency` (валютой котировки). У замещающей
    # облигации справочник говорит «рубли», покупалась она за рубли, а MOEX
    # котирует её в процентах от валютного номинала — и средняя в рублях
    # подписывалась знаком доллара.
    average_price_currency: str
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
    # Валюты, которые в пересчёт не попали, потому что курса к рублю на дату
    # нет. Не то же самое, что «валюты портфеля минус посчитанные»: у позиции
    # без котировки курс не спрашивается вовсе, и её валюта сюда не попадает —
    # причина у неё другая. Пустая таблица курсов и нехватка одной строки в ней
    # дают здесь одинаково честный ответ: без него остаток в серебре исчезал из
    # капитала молча, а покрытие по позициям об этом не сообщало ничего.
    currencies_without_rate: list[str]
    as_of: date | None
    # Дата курсов, по которым сделан пересчёт. Отдельно от as_of: котировки
    # обновляются каждые пятнадцать минут, курсы — раз в сутки, и несвежесть у
    # них разная. Это самый старый из использованных курсов, а не самый свежий
    # из имеющихся: вопрос стоит «насколько несвежи курсы, по которым посчитана
    # эта цифра».
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
        # Валюта расчётов по бумаге (справочник брокера) против валюты её
        # котировки. У замещающей облигации это рубль против доллара или юаня.
        reference_currency = _currency_of(instrument)
        price_currency = (valued.currency or reference_currency).upper()

        if valued.value is None or price_currency != reference_currency:
            # Не ноль: «0 ₽» и «0,0%» в таблице читаются как «бумага ничего не
            # стоит», хотя на деле котировки просто нет.
            #
            # Вторая причина — валюты разошлись: средняя цена из журнала в
            # рублях, а стоимость позиции в долларах, и вычитание одного из
            # другого даёт не доходность, а курс. У живого RU000A10CRC4 средняя
            # 8138,62 ₽ против последней 96,50 $ давала «−98,8 %», хотя 8138/96,5
            # — это просто 84 рубля за доллар. Неизвестная доходность честнее
            # уверенного минуса: считать её здесь нечем, для этого нужен курс на
            # дату каждой операции (фаза 4).
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
                currency=price_currency,
                quantity=position.quantity,
                average_price=position.average_price,
                average_price_currency=reference_currency,
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
    # Дата берётся один раз на весь обзор: два отдельных вызова разошлись бы на
    # сутки у прогона, начатого за миг до московской полуночи, и курсы оказались
    # бы датированы не тем днём, по которому посчитаны.
    today = moscow_today()
    rates = latest_rates(session, today)
    blocked = blocked_by_instrument(session)

    by_class: dict[str, Decimal] = {}
    by_account_id: dict[int, Decimal] = {}
    by_currency: dict[str, Decimal] = {}
    position_currencies: set[str] = set()
    # Валюты, курс которых реально участвовал в пересчёте, и валюты, у которых
    # его не нашлось. Первые задают дату «курсы на», вторые — предупреждение о
    # непосчитанной части капитала. Обе собираются по ходу, а не выводятся
    # потом из таблиц: только здесь видно, какой курс какой суммой был спрошен.
    rate_dates = latest_rate_dates(session, today)
    converted_currencies: set[str] = set()
    missing_rates: set[str] = set()
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
            if valued.value is not None and valued.currency:
                # Цена есть, а курса нет — причина именно в курсе, и её надо
                # назвать. У позиции без котировки курс не спрашивался вовсе,
                # записывать её валюту сюда значило бы обвинить не то.
                missing_rates.add(valued.currency.upper())
            continue

        if valued.currency:
            converted_currencies.add(valued.currency.upper())
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
            # и та же бумага. Доля берётся от модулей и обрезается единицей,
            # потому что числитель и знаменатель приходят из разных источников:
            # blocked — из снимка брокера (broker_holding), quantity — из
            # журнала операций. Их расхождение здесь не гипотеза: система его
            # специально ищет и хранит отдельной таблицей со статусом
            # quantity_mismatch (app/sync/reconcile.py). Без обрезки бумага, у
            # которой брокер показывает blocked 92 при десяти в журнале, дала бы
            # недоступного в девять раз больше собственной стоимости; без
            # модулей знаковое деление у короткой позиции превратило бы
            # обязательство в положительное «недоступно».
            share = min(abs(blocked_quantity) / abs(position.quantity), Decimal("1"))
            restricted_value = money(restricted_value + valued.value_base * share)

    cash_total = money("0")
    blocked_cash = blocked_cash_by_account(session)
    for account_id, balances in cash_by_account(session).items():
        for currency, amount in balances.items():
            # Остаток виден в своей валюте всегда, даже когда пересчитать его
            # нечем: иначе валюта без курса исчезает бесследно.
            by_currency[currency] = money(by_currency.get(currency, money("0")) + amount)

            # Заблокированная часть остатка недоступна к распоряжению так же,
            # как заблокированные бумаги, и в restricted_value входит наравне с
            # ними. В капитал она уже входит в составе amount, а не сверх него
            # (см. BrokerCash), поэтому cash_total от неё не меняется.
            blocked_amount = blocked_cash.get(account_id, {}).get(currency)
            if blocked_amount is not None:
                # Обрезка остатком — та же защита, что и у бумаг выше: соглашение
                # «blocked — часть amount» держится на слове брокера, проверить
                # его на живом счёте пока нечем (у владельца блокировок нет ни в
                # одной валюте). Пришли бы данные иначе — «недоступно» вышло бы
                # больше самого капитала, а такая цифра не объясняется ничем.
                # Отрицательный остаток — долг, блокировать в нём нечего.
                capped = max(money("0"), min(blocked_amount, amount))
                blocked_in_base = to_base(capped, currency, rates)
                if blocked_in_base is not None:
                    restricted_value = money(restricted_value + blocked_in_base)

            in_base = to_base(amount, currency, rates)
            if in_base is None:
                # Курса нет — в рублёвый капитал и рублёвые разбивки остаток
                # войти не может, и валюта обязана быть названа: иначе грамм
                # серебра или золота исчезает из капитала, не оставив следа ни
                # в одной цифре на экране (покрытие считает только позиции).
                missing_rates.add(currency.upper())
                continue
            converted_currencies.add(currency.upper())
            cash_total = money(cash_total + in_base)
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
        currencies_without_rate=sorted(missing_rates),
        # Самая поздняя дата котировки, а не самая ранняя: вопрос, на который
        # она отвечает, — «когда последний раз обновлялись цены». Честность
        # главной цифры обеспечивается признаком покрытия рядом
        # (valued_positions/positions_total), а не сдвигом даты назад.
        as_of=as_of,
        # А вот у курсов — наоборот, самая ранняя из использованных: вопрос
        # другой, «насколько несвежи курсы, по которым посчитана эта цифра».
        # Максимум по всей таблице отвечал на него неверно — золото с MOEX
        # обновляется ежедневно, и его сегодняшняя дата прикрывала бы курсы ЦБ
        # недельной давности, по которым посчитаны доллары, юани и гонконгские
        # доллары. Рубль в расчёт не идёт: у него нет курса и нечему устареть,
        # и у чисто рублёвого портфеля дата курсов пустая — их там не было.
        fx_as_of=min(
            (rate_dates[currency] for currency in converted_currencies if currency in rate_dates),
            default=None,
        ),
        valued_positions=valued_positions,
        positions_total=positions_total,
    )
