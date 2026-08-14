"""Периметр и его арифметика: границы периода, прибыль, ставки, причины.

Общий низ пакета: и сборка отчёта (`service.py`), и разрезы (`breakdown.py`)
считают периметр одним и тем же способом. Двух способов посчитать прибыль в
одном отчёте быть не может — они разойдутся молча.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.models import DailySnapshot
from app.money import money
from app.returns.flows import CashFlow
from app.returns.twr import PRECISION, Chain, annualize, twr
from app.returns.xirr import DAYS_IN_YEAR, Flow, xirr

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


def period_bounds(period_key: str, today: date, first_day: date | None) -> Period:
    """Границы периода и признак «показывать в годовых».

    Порог аннуализации — годовая база XIRR (`app.returns.xirr.DAYS_IN_YEAR`),
    общая с ним и с `twr.annualize`: две константы «365» в двух модулях
    расходятся ровно тогда, когда одну из них поправят, а `over_period` и
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


def period_days(period: Period) -> int:
    if period.since is None:
        return 0
    return (period.until - period.since).days


def over_period(rate: Decimal, days: int) -> Decimal | None:
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


def series(snapshots: list[DailySnapshot], pick) -> list[tuple[date, Decimal]]:
    result = []
    for snapshot in snapshots:
        value = pick(snapshot)
        if value is not None:
            result.append((snapshot.on_date, Decimal(str(value))))
    return result


def series_start(opening: DailySnapshot | None, pick) -> Decimal:
    """Стоимость периметра на начало периода. Ноль — периметра тогда не
    существовало, и это законное начало отсчёта, а не пропуск данных."""
    if opening is None:
        return Decimal("0")
    value = pick(opening)
    return Decimal(str(value)) if value is not None else Decimal("0")


def incomplete_days(snapshots: list[DailySnapshot]) -> frozenset[date]:
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


def metric(flows: list[CashFlow], value_start: Decimal, value_now: Decimal,
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
        rate = over_period(rate, period_days(period))

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
                  reason=reason(rate, twr_rate, flows, chain)), chain


def reason(rate: Decimal | None, twr_rate: Decimal | None,
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
