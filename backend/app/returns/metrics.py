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

# Причины отсутствия числа. Каждая переводится в слова на экране.
REASON_NO_FLOWS = "no_flows"
REASON_NO_HISTORY = "no_history"
REASON_NO_FULL_DAYS = "no_full_days"
REASON_SERIES_GAPS = "series_gaps"
REASON_NO_SOLUTION = "no_solution"
REASON_CASH = "cash"
# Период нулевой длины — «с начала года» первого января: доходности за него не
# существует, потому что не прошло ни дня, а не потому, что данных не хватает.
REASON_EMPTY_PERIOD = "empty_period"

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
    # Сколько дней цепочка TWR ДЕЙСТВИТЕЛЬНО измерила для ЭТОГО периметра —
    # `Chain.days`, донесённый до строки. Не размах ряда и не длина периода:
    # строка счёта, строка класса и строка портфеля стоят в одной колонке
    # таблицы, но измерены на разных отрезках истории (счёт 7 — на своём,
    # класс `equity` — на своём), и без этого числа они выглядят сравнимыми,
    # хотя не сравнимы. Общее число дней периода здесь нарочно не хранится:
    # оно одно на весь отчёт, не зависит от периметра строки и уже едет в
    # `ReturnsOut.period` (`from`/`to`) — повторять его в каждой строке
    # значило бы писать одно и то же число сотни раз.
    #
    # None и 0 — разные утверждения, и подменять одно другим нельзя: 0 значит
    # «цепочка построена, но не измерила ни одного шага» (истории не хватает
    # или в ней сплошные дыры — см. REASON_NO_FULL_DAYS, REASON_SERIES_GAPS,
    # REASON_NO_HISTORY в `reason()`), а None значит «для этого периметра TWR
    # не считается вовсе» — так у строки «Деньги» (`money_row`): решение
    # владельца № 3, цепочки для неё не строят, и 0 соврал бы, что попытка
    # была и не удалась.
    chain_days: int | None = None
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


def rate_flows(flows: list[CashFlow], value_start: Decimal, value_now: Decimal,
                period: Period) -> list[Flow]:
    """Потоки в том виде, в каком их видит XIRR: денежные движения периметра
    плюс два края.

    Начальная стоимость входит вложением, конечная — изъятием: за период
    владелец «вложил» то, что у него уже было, и «получил» то, что стало.

    Собирается одной функцией на весь пакет: по этому же списку прогон
    (`app/returns/check.py`) проверяет сходимость XIRR по определению —
    дисконтирует его по найденной ставке. Собери прогон свой список рядом — он
    проверял бы не ту ставку, которую показывает экран.
    """
    result = [Flow(on_date=flow.on_date, amount=flow.amount) for flow in flows]
    if value_start != 0 and period.since is not None:
        result.append(Flow(on_date=period.since, amount=-value_start))
    if value_now != 0:
        result.append(Flow(on_date=period.until, amount=value_now))
    return result


def flow_span_days(flows: list[Flow]) -> int:
    """Сколько дней прожили потоки, по которым посчитана ставка.

    Именно это время XIRR и аннуализировал: год он отсчитывает от первого
    потока, а не от границы периода. Разаннуализировать по длине периода
    значило бы делить и умножать на разные числа — замер на тесте: 44 дня
    периода против 40 дней потоков давали 2,20 % вместо настоящих 2,00 %.
    """
    if not flows:
        return 0
    return (max(flow.on_date for flow in flows) - min(flow.on_date for flow in flows)).days


def metric(flows: list[CashFlow], value_start: Decimal, value_now: Decimal,
            values: list[tuple[date, Decimal]], period: Period,
            incomplete: frozenset[date] = frozenset()) -> tuple[Metric, Chain]:
    """Доходность одного периметра. Начальная стоимость входит вложением, а
    конечная — изъятием: за период владелец «вложил» то, что у него уже было, и
    «получил» то, что стало.

    `values` — ряд «дата, стоимость» для цепочки TWR. Параметр назван не
    `series`, хотя приходит он ровно из одноимённой функции этого модуля:
    имя параметра перекрывало бы её внутри тела, и вызвать её здесь стало бы
    нельзя, не заметив почему.
    """
    profit = money(value_now - value_start + sum((flow.amount for flow in flows), Decimal("0")))
    invested = money(-sum((flow.amount for flow in flows if flow.amount < 0), Decimal("0")))

    discounted = rate_flows(flows, value_start, value_now, period)
    rate = xirr(discounted)
    chain = twr(values, flows, incomplete)

    if rate is not None and not period.annualized:
        # За период, а не в годовых: XIRR вернул годовую ставку, и на коротком
        # периоде она врёт кратно — пересчитываем обратно по ТОМУ ЖЕ времени, по
        # которому она аннуализирована (окно потоков), а не по длине периода.
        rate = over_period(rate, flow_span_days(discounted))

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
                  value=money(value_now), chain_days=chain.days,
                  reason=reason(rate, twr_rate, flows, chain,
                                empty_period=_is_empty_period(period))), chain


def _is_empty_period(period: Period) -> bool:
    """Период нулевой длины: начало и конец — один и тот же день.

    Так выглядит «с начала года» первого января: измерять нечего не потому, что
    данных не хватает, а потому, что времени ещё не прошло. Случай, когда
    границы периода нет вовсе (`since is None`, снимков в базе нет), — не этот:
    там нет истории, и об этом говорит своя причина.
    """
    return period.since is not None and period.since == period.until


def reason(rate: Decimal | None, twr_rate: Decimal | None,
            flows: list[CashFlow], chain: Chain,
            empty_period: bool = False) -> str | None:
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

    Шестой случай — период нулевой длины (первое января для «с начала года»):
    ставки нет, потому что не прошло ни дня. Прежний ответ «потоков
    недостаточно» обвинял данные там, где не хватает времени: пополнения этого
    дня могут быть на месте все до единого, а доходности всё равно ещё нет.
    """
    if rate is None:
        if empty_period:
            return REASON_EMPTY_PERIOD
        return REASON_NO_FLOWS if not flows else REASON_NO_SOLUTION
    if twr_rate is None:
        if chain.unvalued:
            return REASON_NO_FULL_DAYS
        return REASON_SERIES_GAPS if chain.gaps else REASON_NO_HISTORY
    return None
