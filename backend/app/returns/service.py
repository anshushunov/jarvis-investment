from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import (
    METAL_CURRENCIES,
    asset_class_of,
    cash_asset_class,
    portfolio_overview,
)
from app.analytics.valuation import value_position
from app.marketdata.service import LatestPrice, prices_as_of
from app.models import Account, DailySnapshot, Instrument
from app.money import BASE_CURRENCY, money
from app.positions.engine import LedgerEntry, OpenLot
from app.positions.history import holdings_at
from app.positions.service import ledger_entries
from app.returns.flows import (
    CashFlow,
    Unattributed,
    account_flows,
    cash_movement,
    instrument_flows,
    portfolio_flows,
    unattributed_flows,
    unconverted_flows,
)
from app.returns.fx_split import REASON_NO_PRICE, REASON_NO_RATE, split_position
from app.returns.rates import RateBook
from app.returns.twr import PRECISION, Chain, annualize, twr
from app.returns.xirr import DAYS_IN_YEAR, Flow, xirr
from app.snapshots.service import snapshot_account_values
from app.timeutils import moscow_today

PERIOD_ALL = "all"
PERIOD_12M = "12m"
PERIOD_YTD = "ytd"
PERIODS = (PERIOD_ALL, PERIOD_12M, PERIOD_YTD)

# Причины отсутствия числа. Каждая переводится в слова на экране.
REASON_NO_FLOWS = "no_flows"
REASON_NO_HISTORY = "no_history"
REASON_NO_FULL_DAYS = "no_full_days"
REASON_SERIES_GAPS = "series_gaps"
REASON_NO_SOLUTION = "no_solution"
REASON_CASH = "cash"

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
class Period:
    key: str
    since: date | None
    until: date
    annualized: bool


@dataclass(frozen=True)
class Metric:
    xirr: Decimal | None
    twr: Decimal | None
    profit: Decimal
    invested: Decimal
    value: Decimal
    reason: str | None = None


@dataclass(frozen=True)
class AccountRow:
    account_id: int
    metric: Metric


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


@dataclass(frozen=True)
class Coverage:
    days_total: int
    days_valued: int
    # None — покрытие позиций на последний день периода никто не считал (снимки
    # старше фазы 2c). Ноль означал бы «позиций нет вовсе», а это другое.
    positions_total: int | None
    positions_valued: int | None
    unpriced: list[str]
    chain_breaks: int
    # Сколько дней цепочка TWR действительно измерила. Без этого числа годовая
    # ставка не читается: 444 измеренных дня из 2219 и 2219 из 2219 — разные
    # ответы, а выглядят одинаково.
    chain_days: int
    currencies_without_rate: list[str]


@dataclass(frozen=True)
class ReturnsReport:
    period: Period
    portfolio: Metric
    coverage: Coverage
    by_account: list[AccountRow] = field(default_factory=list)
    by_asset_class: list[AssetClassRow] = field(default_factory=list)
    by_instrument: list[InstrumentRow] = field(default_factory=list)
    unattributed: Unattributed = Unattributed(Decimal("0"), Decimal("0"),
                                              Decimal("0"), Decimal("0"))


def period_bounds(period_key: str, today: date, first_day: date | None) -> Period:
    """Границы периода и признак «показывать в годовых».

    Порог аннуализации — годовая база XIRR (`app.returns.xirr.DAYS_IN_YEAR`),
    общая с ним и с `twr.annualize`: две константы «365» в двух модулях
    расходятся ровно тогда, когда одну из них поправят, а `_over_period` и
    `annualize` обязаны остаться обратными друг другу.

    Период короче года аннуализировать нельзя: ставка врёт кратно — два
    процента за полтора месяца превращаются в двадцать семь годовых, — и такой
    период показывается за период (дизайн, раздел 4.3).
    """
    if period_key == PERIOD_12M:
        since = today - timedelta(days=int(DAYS_IN_YEAR))
    elif period_key == PERIOD_YTD:
        since = date(today.year, 1, 1)
    else:
        since = first_day

    length = (today - since).days if since is not None else 0
    return Period(key=period_key, since=since, until=today, annualized=length >= DAYS_IN_YEAR)


def _period_days(period: Period) -> int:
    if period.since is None:
        return 0
    return (period.until - period.since).days


def _over_period(rate: Decimal, days: int) -> Decimal | None:
    """Годовая ставка, пересчитанная в доходность за период.

    Обратна `twr.annualize` и нужна XIRR: тот по устройству отвечает годовой
    ставкой, а на периоде короче года годовая величина врёт кратно. Прятать
    число вовсе нельзя — оно известно, врёт только годовая подпись под ним
    (дизайн, раздел 4.3).

    None у периода нулевой длины: доходности за нулевой период не существует, а
    вернуть годовую ставку под подписью «за период» значило бы соврать ровно на
    ту величину, ради которой пересчёт и делается.
    """
    if days <= 0:
        return None
    exponent = Decimal(days) / DAYS_IN_YEAR
    return ((Decimal("1") + rate) ** exponent - Decimal("1")).quantize(PRECISION)


def _snapshots(session: Session, since: date | None, until: date) -> list[DailySnapshot]:
    """Снимки внутри периода. Именно они, а не более широкий набор, отвечают за
    покрытие: «на скольких датах периода оценка была полна»."""
    query = select(DailySnapshot).where(DailySnapshot.on_date <= until)
    if since is not None:
        query = query.where(DailySnapshot.on_date >= since)
    return list(session.execute(query.order_by(DailySnapshot.on_date)).scalars().all())


def _opening(session: Session, since: date | None) -> DailySnapshot | None:
    """Последний снимок ДО периода — точка отсчёта.

    Снимок первого дня периода на эту роль не годится: он снят на конец дня и
    уже содержит пополнение этого дня, а пополнение этого дня входит и в потоки
    периода. Взяв его началом отсчёта, прибыль вычла бы пополнение дважды: занёс
    100 000 в первый день, портфель стоит 130 000 — заработано 30 000, а не
    минус 70 000.

    Пусто — периметра до периода не существовало, и ноль здесь законное начало
    отсчёта, а не пропуск данных. Так всегда у периода «всё время»: он начинается
    с первого дня истории.
    """
    if since is None:
        return None
    return session.execute(
        select(DailySnapshot)
        .where(DailySnapshot.on_date < since)
        .order_by(DailySnapshot.on_date.desc())
        .limit(1)
    ).scalars().first()


def _first_snapshot_day(session: Session) -> date | None:
    return session.execute(
        select(DailySnapshot.on_date).order_by(DailySnapshot.on_date).limit(1)
    ).scalar_one_or_none()


def _series(snapshots: list[DailySnapshot], pick) -> list[tuple[date, Decimal]]:
    result = []
    for snapshot in snapshots:
        value = pick(snapshot)
        if value is not None:
            result.append((snapshot.on_date, Decimal(str(value))))
    return result


def _series_start(opening: DailySnapshot | None, pick) -> Decimal:
    """Стоимость периметра на начало периода. Ноль — периметра тогда не
    существовало, и это законное начало отсчёта, а не пропуск данных."""
    if opening is None:
        return Decimal("0")
    value = pick(opening)
    return Decimal(str(value)) if value is not None else Decimal("0")


def _incomplete_days(snapshots: list[DailySnapshot]) -> frozenset[date]:
    """Даты, оценка которых неполна: часть позиций осталась без цены.

    Считается здесь, а не в `twr()`: цепочка не знает про `DailySnapshot` и не
    должна — она работает с рядом «дата, стоимость». Покрытие `NULL` (снимки
    старше фазы 2c) тоже неполное: неизвестное — не полное, и записать такой
    день в оценённые значило бы поверить величине, которую никто не проверял.
    """
    return frozenset(
        row.on_date for row in snapshots
        if row.positions_total is None or row.valued_positions is None
        or row.valued_positions < row.positions_total
    )


def _metric(flows: list[CashFlow], value_start: Decimal, value_now: Decimal,
            series: list[tuple[date, Decimal]], period: Period,
            incomplete: frozenset[date] = frozenset()) -> tuple[Metric, Chain]:
    """Доходность одного периметра. Начальная стоимость входит вложением, а
    конечная — изъятием: за период владелец «вложил» то, что у него уже было, и
    «получил» то, что стало."""
    profit = money(value_now - value_start + sum((flow.amount for flow in flows), Decimal("0")))
    invested = money(-sum((flow.amount for flow in flows if flow.amount < 0), Decimal("0")))

    rate_flows = [Flow(on_date=flow.on_date, amount=flow.amount) for flow in flows]
    if value_start != 0 and period.since is not None:
        rate_flows.append(Flow(on_date=period.since, amount=-value_start))
    if value_now != 0:
        rate_flows.append(Flow(on_date=period.until, amount=value_now))

    rate = xirr(rate_flows)
    chain = twr(series, flows, incomplete)

    if rate is not None and not period.annualized:
        # За период, а не в годовых: XIRR вернул годовую ставку, и на коротком
        # периоде она врёт кратно — пересчитываем обратно.
        rate = _over_period(rate, _period_days(period))

    twr_rate = chain.rate
    if twr_rate is not None and chain.days >= DAYS_IN_YEAR:
        # В годовых — только если цепочка измерила год и больше, и приводится
        # она по ИЗМЕРЕННОМУ времени, а не по длине периода. Замер 14.08.2026:
        # измерено 444 дня, все до 04.05.2022, а ставка растягивалась на 2220
        # дней — доходность худшего куска истории выдавалась за доходность
        # шести лет. Длина периода (`period.annualized`) здесь ни при чём: она
        # решает судьбу XIRR, у которого своё время — всё окно потоков.
        twr_rate = annualize(twr_rate, chain.days)

    return Metric(xirr=rate, twr=twr_rate, profit=profit, invested=invested,
                  value=money(value_now),
                  reason=_reason(rate, twr_rate, flows, chain)), chain


def _reason(rate: Decimal | None, twr_rate: Decimal | None,
            flows: list[CashFlow], chain: Chain) -> str | None:
    """Почему числа нет. Молчаливый прочерк запрещён: у каждого пустого места на
    экране есть названная причина.

    Три случая — три разных ответа владельцу, и подменять их одним нельзя:
    потоков в периоде не было вовсе (ставки не существует); потоки были, а
    корня у уравнения нет — все одного знака, все одним днём, ставка за
    пределами разумных границ (дизайн, раздел 4.5: «недостаточно данных для
    расчёта»); ряда стоимостей нет, и цепочке TWR не из чего строиться. Раньше
    второй случай отвечал «истории нет» — счёт с одними пополнениями и нулевой
    стоимостью обвинял историю, которая на месте.

    Ещё два случая появились 14.08.2026, и они тоже разные. Ряд есть, но ни
    одного шага измерить не удалось: либо все дни оценены не полностью — «не
    хватает цен» (за последние 12 месяцев живой базы полной оценки нет ни у
    одного дня), либо ряд рваный, и соседние точки не соседние дни — «в ряду
    дыры» (так у класса, которого нет в части снимков). Ответ владельцу разный:
    в первом случае лечат котировки, во втором — история снимков.
    """
    if rate is None:
        return REASON_NO_FLOWS if not flows else REASON_NO_SOLUTION
    if twr_rate is None:
        if chain.unvalued:
            return REASON_NO_FULL_DAYS
        return REASON_SERIES_GAPS if chain.gaps else REASON_NO_HISTORY
    return None


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


def returns_report(session: Session, period_key: str, today: date | None = None,
                   value_now: Decimal | None = None,
                   by_account_now: dict[int, Decimal] | None = None,
                   by_class_now: dict[str, Decimal] | None = None,
                   cash_now: Decimal | None = None) -> ReturnsReport:
    """Отчёт о доходности за период.

    Сегодняшние стоимости приходят параметрами, а не считаются здесь: их уже
    посчитал `portfolio_overview`, и второй расчёт того же числа рядом с первым
    рано или поздно разойдётся с ним — экраны «Портфель» и «Аналитика» показали
    бы разный капитал в один и тот же момент. Значения по умолчанию берутся из
    него же — параметры существуют ради тестов и ради вызова из обработчика
    одним куском.

    `cash_now` — стоимость денежного периметра по источнику (`Overview.
    cash_value`: остатки и металлы, без единой бумаги). Сумма по ключам
    `by_asset_class` для этого не годится: те же имена классов возвращает
    `asset_class_of` для инструментов вида «валюта» и «металл», и появись такой
    в журнале — его стоимость посчиталась бы дважды.
    """
    today = today or moscow_today()
    if (value_now is None or by_account_now is None or by_class_now is None
            or cash_now is None):
        # Обзор считается один раз, но заполняет только то, чего не передали:
        # переданное значение не перетирается — тест, назвавший стоимость и
        # умолчавший об остатке, получал бы пустой портфель молча.
        overview = portfolio_overview(session)
        value_now = overview.total_value if value_now is None else value_now
        by_account_now = overview.by_account if by_account_now is None else by_account_now
        by_class_now = overview.by_asset_class if by_class_now is None else by_class_now
        cash_now = overview.cash_value if cash_now is None else cash_now

    period = period_bounds(period_key, today, _first_snapshot_day(session))
    book = RateBook.load(session)
    snapshots = _snapshots(session, period.since, period.until)
    # Ряд для цепочки начинается с точки отсчёта — той же, от которой считается
    # прибыль. Две разные «начальные стоимости» в одном отчёте разошлись бы
    # молча. Ряд по бумаге не строится вовсе: дневного ряда по бумаге в снимке
    # нет (дизайн, раздел 4.3).
    opening = _opening(session, period.since)
    chart = ([opening] if opening is not None else []) + snapshots

    # Неполнота оценки — свойство дня, а не периметра: цена, которой не нашлось,
    # занижает и общую стоимость, и разбивку по счетам и классам. Множество
    # считается один раз и достаётся всем цепочкам отчёта.
    incomplete = _incomplete_days(chart)

    total_series = _series(chart, lambda row: row.total_value)
    flows = portfolio_flows(session, book, period.since, period.until)
    portfolio, chain = _metric(flows, _series_start(opening, lambda row: row.total_value),
                               value_now, total_series, period, incomplete)

    accounts = list(session.execute(select(Account)).scalars())
    # Какие ключи разбивки считать идентификаторами счетов, знает сторона,
    # которая их пишет (app/snapshots/service.py) — здесь это правило не
    # повторяется. Разбор снимка делается один раз на снимок, а не по разу на
    # каждый счёт: снимков в окне «всё время» больше двух тысяч.
    chart_values = [(row.on_date, snapshot_account_values(row)) for row in chart]
    opening_values = snapshot_account_values(opening) if opening is not None else {}

    by_account = []
    for account in accounts:
        series = [(day, values[account.id]) for day, values in chart_values
                  if account.id in values]
        metric, _ = _metric(account_flows(session, book, account.id, period.since, period.until),
                            opening_values.get(account.id, Decimal("0")),
                            by_account_now.get(account.id, Decimal("0")), series, period,
                            incomplete)
        by_account.append(AccountRow(account_id=account.id, metric=metric))

    unattributed = unattributed_flows(session, book, period.since, period.until)
    instrument_rows, by_class = _instrument_and_class_rows(
        session, book, period, chart, opening,
        [ledger_entries(session, account) for account in accounts], by_class_now,
        incomplete, cash_movement(session, book, period.since, period.until), cash_now)

    # Полных дней — столько, сколько снимков периода не попало в неполные.
    # Правило «какой день полный» живёт в `_incomplete_days` и только там: две
    # его записи разъехались бы при первой же правке одной из них.
    valued = len(snapshots) - len(_incomplete_days(snapshots))
    last = snapshots[-1] if snapshots else None
    coverage = Coverage(
        days_total=len(snapshots),
        days_valued=valued,
        positions_total=last.positions_total if last else None,
        positions_valued=last.valued_positions if last else None,
        unpriced=list(last.unpriced or []) if last else [],
        chain_breaks=chain.breaks,
        chain_days=chain.days,
        currencies_without_rate=unconverted_flows(session, book),
    )

    return ReturnsReport(
        period=period, portfolio=portfolio, coverage=coverage,
        by_account=by_account, by_asset_class=by_class, by_instrument=instrument_rows,
        unattributed=unattributed,
    )


def _instrument_and_class_rows(session: Session, book: RateBook, period: Period,
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

        metric, _ = _metric(class_flows.get(klass, []), _series_start(opening, pick),
                            value_now, _series(chart, pick), period, incomplete)
        by_class.append(AssetClassRow(asset_class=klass, metric=metric))

    money_row = _money_row(cash_now, opening, movement)
    if money_row is not None:
        by_class.append(money_row)

    return rows, sorted(by_class, key=lambda row: row.asset_class)


def _money_row(value_now: Decimal, opening: DailySnapshot | None,
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
        (_series_start(opening, lambda row, key=klass: (row.by_asset_class or {}).get(key))
         for klass in MONEY_CLASSES), Decimal("0"))
    profit = money(value_now - value_start - movement)

    if not value_now and not value_start and not profit:
        # Денег в портфеле нет вовсе — строки тоже быть не должно: пустая строка
        # с нулями отвечает на вопрос, которого никто не задавал.
        return None
    return AssetClassRow(asset_class=MONEY_ROW_CLASS, metric=Metric(
        xirr=None, twr=None, profit=profit, invested=Decimal("0"),
        value=money(value_now), reason=REASON_CASH))


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
        rate = _over_period(rate, _period_days(period))
    return rate
