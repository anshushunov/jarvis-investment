from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import asset_class_of, portfolio_overview
from app.marketdata.service import prices_as_of
from app.models import Account, DailySnapshot, Instrument
from app.money import money
from app.positions.engine import OpenLot, fold
from app.positions.service import ledger_entries
from app.returns.flows import (
    CashFlow,
    Unattributed,
    account_flows,
    instrument_flows,
    portfolio_flows,
    unattributed_flows,
    unconverted_flows,
)
from app.returns.fx_split import split_position
from app.returns.rates import RateBook
from app.returns.twr import PRECISION, Chain, annualize, twr
from app.returns.xirr import Flow, xirr
from app.timeutils import moscow_today

PERIOD_ALL = "all"
PERIOD_12M = "12m"
PERIOD_YTD = "ytd"
PERIODS = (PERIOD_ALL, PERIOD_12M, PERIOD_YTD)

# Порог аннуализации. Ставка XIRR по устройству годовая, и на периоде короче
# года она врёт кратно: два процента за полтора месяца превращаются в двадцать
# семь годовых. Короткий период показывается как есть, за период (дизайн,
# раздел 4.3), — годовая подпись под ним снимается вместе с пересчётом.
DAYS_IN_YEAR = 365

# Причины отсутствия числа. Каждая переводится в слова на экране.
REASON_NO_FLOWS = "no_flows"
REASON_NO_HISTORY = "no_history"
REASON_CASH = "cash"

CASH_CLASS = "cash"


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
    profit: Decimal
    value: Decimal
    closed: bool
    price_part: Decimal | None
    fx_part: Decimal | None
    reason: str | None


@dataclass(frozen=True)
class Coverage:
    days_total: int
    days_valued: int
    positions_total: int
    positions_valued: int
    unpriced: list[str]
    chain_breaks: int
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
    if period_key == PERIOD_12M:
        since = today - timedelta(days=DAYS_IN_YEAR)
    elif period_key == PERIOD_YTD:
        since = date(today.year, 1, 1)
    else:
        since = first_day

    # Период короче года аннуализировать нельзя — см. комментарий у DAYS_IN_YEAR.
    length = (today - since).days if since is not None else 0
    return Period(key=period_key, since=since, until=today, annualized=length >= DAYS_IN_YEAR)


def _period_days(period: Period) -> int:
    if period.since is None:
        return 0
    return (period.until - period.since).days


def _over_period(rate: Decimal, days: int) -> Decimal:
    """Годовая ставка, пересчитанная в доходность за период.

    Обратна `twr.annualize` и нужна XIRR: тот по устройству отвечает годовой
    ставкой, а на периоде короче года годовая величина врёт кратно. Прятать
    число вовсе нельзя — оно известно, врёт только годовая подпись под ним
    (дизайн, раздел 4.3).
    """
    if days <= 0:
        return rate.quantize(PRECISION)
    exponent = Decimal(days) / Decimal(DAYS_IN_YEAR)
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
    отсчёта, а не пропуск данных.
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


def _metric(flows: list[CashFlow], value_start: Decimal, value_now: Decimal,
            series: list[tuple[date, Decimal]], period: Period) -> tuple[Metric, Chain]:
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
    chain = twr(series, flows)

    if rate is not None and not period.annualized:
        # За период, а не в годовых: XIRR вернул годовую ставку, и на коротком
        # периоде она врёт кратно — пересчитываем обратно.
        rate = _over_period(rate, _period_days(period))

    twr_rate = chain.rate
    if twr_rate is not None and period.annualized:
        twr_rate = annualize(twr_rate, chain.days)

    # Причина именуется по главному числу экрана — ставке владельца. Молчаливый
    # прочерк вместо неё запрещён: у каждого пустого места есть названная
    # причина. Потоков в периоде не было вовсе — ставки не существует; потоки
    # были, а ставка не нашлась — считать её не из чего (одного знака, один
    # день, корень вне разумных границ).
    reason = None
    if rate is None:
        reason = REASON_NO_FLOWS if not flows else REASON_NO_HISTORY
    elif twr_rate is None:
        # Ряда стоимостей нет: цепочке не из чего строиться.
        reason = REASON_NO_HISTORY

    return Metric(xirr=rate, twr=twr_rate, profit=profit, invested=invested,
                  value=money(value_now), reason=reason), chain


def _lots_by_instrument(session: Session) -> dict[int, list[OpenLot]]:
    """Открытые партии по всем счетам, сведённые по бумаге.

    Партии считает движок позиций — тот же, что строит саму позицию. Второй
    свёртки журнала в проекте быть не должно: разъедется трактовка решений
    владельца.
    """
    result: dict[int, list[OpenLot]] = {}
    for account in session.execute(select(Account)).scalars():
        folded = fold(ledger_entries(session, account), currency=account.currency)
        for instrument_id, state in folded.positions.items():
            if state.quantity == 0:
                continue
            result.setdefault(instrument_id, []).extend(state.lots)
    return result


def returns_report(session: Session, period_key: str, today: date | None = None,
                   value_now: Decimal | None = None,
                   by_account_now: dict[int, Decimal] | None = None,
                   by_class_now: dict[str, Decimal] | None = None) -> ReturnsReport:
    """Отчёт о доходности за период.

    Сегодняшние стоимости приходят параметрами, а не считаются здесь: их уже
    посчитал `portfolio_overview`, и второй расчёт того же числа рядом с первым
    рано или поздно разойдётся с ним — экраны «Портфель» и «Аналитика» показали
    бы разный капитал в один и тот же момент. Значения по умолчанию берутся из
    него же — параметры существуют ради тестов и ради вызова из обработчика
    одним куском.
    """
    today = today or moscow_today()
    if value_now is None or by_account_now is None or by_class_now is None:
        overview = portfolio_overview(session)
        value_now = overview.total_value
        by_account_now = overview.by_account
        by_class_now = overview.by_asset_class

    period = period_bounds(period_key, today, _first_snapshot_day(session))
    book = RateBook.load(session)
    snapshots = _snapshots(session, period.since, period.until)
    # Ряд для цепочки начинается с точки отсчёта — той же, от которой считается
    # прибыль. Две разные «начальные стоимости» в одном отчёте разошлись бы
    # молча. Ряд по бумаге не строится вовсе: дневного ряда по бумаге в снимке
    # нет (дизайн, раздел 4.3).
    opening = _opening(session, period.since)
    chart = ([opening] if opening is not None else []) + snapshots

    total_series = _series(chart, lambda row: row.total_value)
    flows = portfolio_flows(session, book, period.since, period.until)
    portfolio, chain = _metric(flows, _series_start(opening, lambda row: row.total_value),
                               value_now, total_series, period)

    accounts = list(session.execute(select(Account)).scalars())
    by_account = []
    for account in accounts:
        def pick(row, key=str(account.id)):
            return (row.by_account or {}).get(key)

        metric, _ = _metric(account_flows(session, book, account.id, period.since, period.until),
                            _series_start(opening, pick),
                            by_account_now.get(account.id, Decimal("0")),
                            _series(chart, pick), period)
        by_account.append(AccountRow(account_id=account.id, metric=metric))

    instrument_rows, by_class = _instrument_and_class_rows(
        session, book, period, chart, opening, by_class_now)

    # Полнота оценки дня — только там, где её вообще считали: у снимков старше
    # фазы 2c покрытие NULL, и «NULL равен NULL» записало бы день с неизвестным
    # покрытием в полностью оценённые. Неизвестное — не полное.
    valued = sum(1 for row in snapshots
                 if row.positions_total is not None
                 and row.valued_positions == row.positions_total)
    last = snapshots[-1] if snapshots else None
    coverage = Coverage(
        days_total=len(snapshots),
        days_valued=valued,
        positions_total=(last.positions_total or 0) if last else 0,
        positions_valued=(last.valued_positions or 0) if last else 0,
        unpriced=list(last.unpriced or []) if last else [],
        chain_breaks=chain.breaks,
        currencies_without_rate=unconverted_flows(session, book),
    )

    return ReturnsReport(
        period=period, portfolio=portfolio, coverage=coverage,
        by_account=by_account, by_asset_class=by_class, by_instrument=instrument_rows,
        unattributed=unattributed_flows(session, book, period.since, period.until),
    )


def _series_start(opening: DailySnapshot | None, pick) -> Decimal:
    """Стоимость периметра на начало периода. Ноль — периметра тогда не
    существовало, и это законное начало отсчёта, а не пропуск данных."""
    if opening is None:
        return Decimal("0")
    value = pick(opening)
    return Decimal(str(value)) if value is not None else Decimal("0")


def _instrument_and_class_rows(session: Session, book: RateBook, period: Period,
                               chart: list[DailySnapshot], opening: DailySnapshot | None,
                               by_class_now: dict[str, Decimal]):
    """Строки по бумагам и по классам активов за один проход.

    Класс бумаги берётся сегодняшний: истории смены класса система не хранит, и
    выдумывать её здесь нельзя. Упрощение названо на экране.
    """
    flows_by_instrument = instrument_flows(session, book, period.since, period.until)
    lots = _lots_by_instrument(session)
    prices = prices_as_of(session, period.until)

    instruments = {
        row.id: row
        for row in session.execute(
            select(Instrument).where(Instrument.id.in_(
                set(flows_by_instrument) | set(lots)))
        ).scalars()
    }

    rows: list[InstrumentRow] = []
    class_flows: dict[str, list[CashFlow]] = {}

    for instrument_id, instrument in instruments.items():
        flows = flows_by_instrument.get(instrument_id, [])
        open_lots = lots.get(instrument_id, [])
        price = prices.get(instrument_id)

        value = Decimal("0")
        if open_lots and price is not None:
            quantity = sum((lot.quantity_left for lot in open_lots), Decimal("0"))
            in_base = book.to_base(quantity * price.close, price.currency, period.until)
            value = in_base if in_base is not None else Decimal("0")

        split = split_position(
            lots=open_lots, price=price,
            price_currency=(price.currency if price else instrument.currency),
            cost_currency=instrument.currency, book=book, on_date=period.until,
        ) if open_lots else None

        rate_flows = [Flow(on_date=flow.on_date, amount=flow.amount) for flow in flows]
        if value != 0:
            rate_flows.append(Flow(on_date=period.until, amount=value))
        rate = xirr(rate_flows)
        if rate is not None and not period.annualized:
            rate = _over_period(rate, _period_days(period))

        profit = money(value + sum((flow.amount for flow in flows), Decimal("0")))
        rows.append(InstrumentRow(
            instrument_id=instrument_id,
            ticker=instrument.ticker,
            name=instrument.issuer or instrument.ticker or instrument.isin or "—",
            xirr=rate,
            profit=profit,
            value=money(value),
            closed=not open_lots,
            price_part=split.price_part if split else None,
            fx_part=split.fx_part if split else None,
            reason=(split.reason if split else None),
        ))

        klass = asset_class_of(instrument)
        class_flows.setdefault(klass, []).extend(flows)

    by_class = []
    # Классы берутся объединением: сегодняшняя стоимость есть у одних, потоки
    # периода — у других. Класс, из которого всё продано, стоит сегодня ноль, но
    # прибыль за период принёс, и без его строки сумма по классам не сойдётся с
    # портфелем ровно на неё (то же решение, что и по проданным бумагам).
    for klass in sorted(set(by_class_now) | set(class_flows)):
        value_now = by_class_now.get(klass, Decimal("0"))
        if klass == CASH_CLASS:
            # Доходности у денежного остатка нет: он не растёт сам, а проценты
            # на него приходят записями без бумаги и уже посчитаны строкой
            # «Прочее». Показать тут ноль значило бы утверждать, что деньги
            # ничего не принесли, — а они не могли.
            by_class.append(AssetClassRow(asset_class=klass, metric=Metric(
                xirr=None, twr=None, profit=Decimal("0"), invested=Decimal("0"),
                value=money(value_now), reason=REASON_CASH)))
            continue

        def pick(row, key=klass):
            return (row.by_asset_class or {}).get(key)

        metric, _ = _metric(class_flows.get(klass, []), _series_start(opening, pick),
                            value_now, _series(chart, pick), period)
        by_class.append(AssetClassRow(asset_class=klass, metric=metric))

    return rows, by_class
