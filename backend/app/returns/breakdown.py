"""Разрезы отчёта: по бумагам, по классам активов и одной строкой — деньги.

Отделено от сборки отчёта (`service.py`) по ответственности: там периоды,
портфель, счета и покрытие, здесь — три разреза, которые считаются за один
проход по журналу и ценам. Общая арифметика периметра у обоих одна и лежит в
`metrics.py`.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import (
    METAL_CURRENCIES,
    asset_class_of,
    cash_asset_class,
)
from app.analytics.valuation import value_position
from app.marketdata.service import LatestPrice, prices_as_of
from app.models import DailySnapshot, Instrument
from app.money import BASE_CURRENCY, money
from app.positions.engine import LedgerEntry, OpenLot
from app.positions.history import holdings_at
from app.returns.flows import CashFlow, instrument_flows
from app.returns.fx_split import REASON_NO_PRICE, REASON_NO_RATE, split_position
from app.returns.metrics import (
    REASON_CASH,
    REASON_NO_HISTORY,
    Metric,
    Period,
    metric,
    over_period,
    period_days,
    series,
    series_start,
)
from app.returns.rates import RateBook
from app.returns.xirr import Flow, xirr

# Классы денежных остатков: рубли, валюта и металлы. Имена не перечисляются —
# их отвечает `app/analytics/service.py::cash_asset_class`, тот же, кто их
# расставляет живому портфелю. Совпадение по имени доверия не заслуживает:
# `asset_class_of` возвращает те же `cash` и `gold` инструментам вида «валюта»
# и «металл», а `portfolio_overview` кладёт бумаги и остатки в один
# `by_asset_class`. Сегодняшняя стоимость периметра поэтому берётся из
# `Overview.cash_value` (только остатки), а не суммой по этим ключам; в
# исторических снимках другого источника нет, и там ограничение остаётся.
#
# В разрезе доходности все они — один периметр и одна строка. Отделить
# перекладывание рублей в золото от покупки валюты нечем: и то и другое лежит в
# журнале записью без бумаги (замер 14.08.2026: 13 покупок золота на 83 686,80 ₽
# среди 498 конверсий валюты, отличает их только название от брокера). Отдельная
# строка золота показала бы прибылью всю его стоимость — 117 130 ₽ вместо
# настоящих 33 443 ₽.
MONEY_CLASSES = frozenset(
    cash_asset_class(currency) for currency in (BASE_CURRENCY, *METAL_CURRENCIES))

# Ключ строки «Деньги и металлы» в разрезе по классам. Собственный, а не `cash`:
# под именем «Деньги» лежало бы ещё и золото — 117 130 ₽ живого портфеля, —
# и экран «Аналитика» противоречил бы экрану «Портфель», где у золота своя доля
# аллокации. Одна строка на весь денежный периметр: см. комментарий выше.
MONEY_ROW_CLASS = "cash_and_metals"


@dataclass(frozen=True)
class AssetClassRow:
    asset_class: str
    metric: Metric


@dataclass(frozen=True)
class InstrumentRow:
    instrument_id: int
    ticker: str | None
    name: str
    xirr: Decimal | None
    # None — не ноль: прибыль неизвестна, потому что позицию не удалось оценить
    # на конец периода или на его начало. Ноль означал бы «бумага не принесла
    # ничего», а на деле неизвестно, принесла ли.
    profit: Decimal | None
    value: Decimal | None
    closed: bool
    # Нереализованная («бумажная») прибыль открытых партий за всё время
    # владения — то, что раскладывают price_part и fx_part. С `profit` не
    # совпадает у бумаги с частичными продажами: та содержит ещё и
    # реализованный результат периода, которого разложение не видит по
    # устройству (дизайн, раздел 4.4). Замер 14.08.2026 у Озона: 70 568 ₽
    # прибыли периода против 53 555 ₽ нереализованной.
    unrealized: Decimal | None
    price_part: Decimal | None
    fx_part: Decimal | None
    reason: str | None


def _rates_at(book: RateBook, prices: dict[int, LatestPrice], on_date: date) -> dict[str, Decimal]:
    """Курсы валют котировок на дату — в том виде, в каком их ждёт оценка
    позиции (`app/analytics/valuation.py`). Берутся из уже прочитанной книги
    курсов, а не отдельным запросом на каждую дату."""
    rates: dict[str, Decimal] = {}
    for currency in {price.currency.upper() for price in prices.values()} | {BASE_CURRENCY}:
        rate = book.rate(currency, on_date)
        if rate is not None:
            rates[currency] = rate
    return rates


def _lots_at(journals: list[list[LedgerEntry]], on_date: date) -> dict[int, list[OpenLot]]:
    """Открытые партии всех счетов на конец дня, сведённые по бумаге.

    Состав на дату восстанавливает `app/positions/history.py::holdings_at` — та
    же свёртка журнала, что строит и сегодняшнюю позицию. Второй свёртки в
    проекте быть не должно: разъедется трактовка решений владельца.
    """
    result: dict[int, list[OpenLot]] = {}
    for entries in journals:
        for instrument_id, state in holdings_at(entries, on_date).items():
            result.setdefault(instrument_id, []).extend(state.lots)
    return result


def _position_value(lots: list[OpenLot], price: LatestPrice | None,
                    rates: dict[str, Decimal]) -> Decimal | None:
    """Стоимость набора партий в рублях.

    Ноль — партий нет: позиции на эту дату не существовало, и это точное знание.
    None — оценить нечем: нет цены на дату или нет курса её валюты. Ноль вместо
    None означал бы «бумага ничего не стоит», и позиция исчезала бы и из
    стоимости, и из прибыли, не оставив следа, — ровно то, ради чего в проекте
    существует раздельный `ValuedPosition.value_base`.
    """
    if not lots:
        return Decimal("0")
    quantity = sum((lot.quantity_left for lot in lots), Decimal("0"))
    return value_position(quantity, price, rates).value_base


def instrument_and_class_rows(session: Session, book: RateBook, period: Period,
                               chart: list[DailySnapshot], opening: DailySnapshot | None,
                               journals: list[list[LedgerEntry]],
                               by_class_now: dict[str, Decimal],
                               incomplete: frozenset[date],
                               movement: Decimal, cash_now: Decimal):
    """Строки по бумагам и по классам активов за один проход.

    Класс бумаги берётся сегодняшний: истории смены класса система не хранит, и
    выдумывать её здесь нельзя. Упрощение названо на экране.

    Все параметры обязательные: у функции один вызывающий, а забытое движение
    денег дало бы неверную строку «Деньги» молча.
    """
    flows_by_instrument = instrument_flows(session, book, period.since, period.until)

    # Состав и цены — на одну и ту же дату, оба раза. Партии на сегодня против
    # цен на конец периода дали бы строку, в которой количество из одного дня
    # умножено на цену другого; сегодня `until` и есть сегодня, и дефект был бы
    # незаметен ровно до первого отчёта за прошлый период.
    end_lots = _lots_at(journals, period.until)
    end_prices = prices_as_of(session, period.until)
    end_rates = _rates_at(book, end_prices, period.until)

    # Начало периода — тот же день, от которого считает свою прибыль портфель
    # (снимок-точка отсчёта). Нет его — периметра до периода не существовало,
    # и начальной стоимости у бумаги тоже нет: так у периода «всё время».
    start_day = opening.on_date if opening is not None else None
    start_lots = _lots_at(journals, start_day) if start_day is not None else {}
    start_prices = prices_as_of(session, start_day) if start_day is not None else {}
    start_rates = _rates_at(book, start_prices, start_day) if start_day is not None else {}

    instruments = {
        row.id: row
        for row in session.execute(
            select(Instrument).where(Instrument.id.in_(
                set(flows_by_instrument) | set(end_lots) | set(start_lots)))
        ).scalars()
    }

    rows: list[InstrumentRow] = []
    class_flows: dict[str, list[CashFlow]] = {}

    for instrument_id, instrument in instruments.items():
        flows = flows_by_instrument.get(instrument_id, [])
        open_lots = end_lots.get(instrument_id, [])
        price = end_prices.get(instrument_id)

        value = _position_value(open_lots, price, end_rates)
        value_start = _position_value(start_lots.get(instrument_id, []),
                                      start_prices.get(instrument_id), start_rates)

        split = split_position(
            lots=open_lots, price=price,
            price_currency=(price.currency if price else instrument.currency),
            cost_currency=instrument.currency, book=book, on_date=period.until,
        ) if open_lots else None

        reason = split.reason if split else None
        if value is None:
            # Оценить нечем — прибыль и ставка неизвестны, а не равны нулю.
            reason = REASON_NO_PRICE if price is None else REASON_NO_RATE
        elif value_start is None:
            # Конец периода известен, начало — нет: прибыль периода не из чего
            # вычесть. Причина именно про историю, а не про сегодняшнюю цену.
            reason = REASON_NO_HISTORY

        rows.append(InstrumentRow(
            instrument_id=instrument_id,
            ticker=instrument.ticker,
            name=instrument.issuer or instrument.ticker or instrument.isin or "—",
            xirr=_instrument_rate(flows, value_start, value, period),
            profit=(money(value - value_start + sum((flow.amount for flow in flows), Decimal("0")))
                    if value is not None and value_start is not None else None),
            value=money(value) if value is not None else None,
            closed=not open_lots,
            unrealized=split.total if split else None,
            price_part=split.price_part if split else None,
            fx_part=split.fx_part if split else None,
            reason=reason,
        ))

        klass = asset_class_of(instrument)
        class_flows.setdefault(klass, []).extend(flows)

    by_class = []
    # Классы берутся объединением: сегодняшняя стоимость есть у одних, потоки
    # периода — у других. Класс, из которого всё продано, стоит сегодня ноль, но
    # прибыль за период принёс, и без его строки сумма по классам не сойдётся с
    # портфелем ровно на неё (то же решение, что и по проданным бумагам).
    for klass in sorted(set(by_class_now) | set(class_flows)):
        if klass in MONEY_CLASSES:
            # Деньги и металлы считаются одной строкой ниже: их периметр общий.
            continue
        value_now = by_class_now.get(klass, Decimal("0"))

        def pick(row, key=klass):
            return (row.by_asset_class or {}).get(key)

        klass_metric, _ = metric(class_flows.get(klass, []), series_start(opening, pick),
                                 value_now, series(chart, pick), period, incomplete)
        by_class.append(AssetClassRow(asset_class=klass, metric=klass_metric))

    row = money_row(cash_now, opening, movement)
    if row is not None:
        by_class.append(row)

    return rows, sorted(by_class, key=lambda row: row.asset_class)


def money_row(value_now: Decimal, opening: DailySnapshot | None,
               movement: Decimal) -> AssetClassRow | None:
    """Строка «Деньги» — остатки и металлы одним периметром.

    Прибыль считается независимо от всего остального отчёта: стоимость
    периметра на конец минус стоимость на начало минус чистое движение денег по
    журналу (`app/returns/flows.py::cash_movement`). Зеркало посчитанных
    потоков — «внешние минус бумаги минус Прочее» — давало ту же величину, но
    тождественно равную невязке разрезов: любая ошибка атрибуции молча
    становилась прибылью денег, и расхождение переставало ловить что-либо
    (дизайн, раздел 7: строка не свалка для остатка).

    Без этой строки рублёвая переоценка валютного остатка не видна нигде: замер
    14.08.2026 — 16 044,58 ₽ необъяснённого остатка при сходимости разрезов.

    Доходности у денег нет и не будет: решение владельца № 3. Остаток не растёт
    сам, а проценты на него приходят записями без бумаги — они в «Прочем».
    """
    value_start = sum(
        (series_start(opening, lambda row, key=klass: (row.by_asset_class or {}).get(key))
         for klass in MONEY_CLASSES), Decimal("0"))
    profit = money(value_now - value_start - movement)

    if not value_now and not value_start and not profit:
        # Денег в портфеле нет вовсе — строки тоже быть не должно: пустая строка
        # с нулями отвечает на вопрос, которого никто не задавал.
        return None
    return AssetClassRow(asset_class=MONEY_ROW_CLASS, metric=Metric(
        xirr=None, twr=None, profit=profit, invested=Decimal("0"),
        value=money(value_now), chain_days=None, reason=REASON_CASH))


def _instrument_rate(flows: list[CashFlow], value_start: Decimal | None,
                     value_end: Decimal | None, period: Period) -> Decimal | None:
    """Ставка по одной бумаге за период.

    Стоимость на начало периода входит вложением, на конец — изъятием: тем же
    способом, что и у портфеля. Без начальной стоимости бумага, купленная до
    периода, показывала бы прибылью всю свою стоимость, а ставка считалась бы по
    единственному потоку и молча выходила бы `None`.

    Неизвестная стоимость на любом из концов — не ноль: ставки в этом случае
    нет вовсе, и причина названа в строке.
    """
    if value_start is None or value_end is None:
        return None

    rate_flows = [Flow(on_date=flow.on_date, amount=flow.amount) for flow in flows]
    if value_start != 0 and period.since is not None:
        rate_flows.append(Flow(on_date=period.since, amount=-value_start))
    if value_end != 0:
        rate_flows.append(Flow(on_date=period.until, amount=value_end))

    rate = xirr(rate_flows)
    if rate is not None and not period.annualized:
        rate = over_period(rate, period_days(period))
    return rate
