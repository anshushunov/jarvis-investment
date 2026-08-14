"""Сборка отчёта о доходности: период, портфель, счета, покрытие.

Пакет разделён по ответственности, когда файл перевалил за шестьсот строк и
перестал держаться в голове целиком:

- `metrics.py` — периметр и его арифметика: границы периода, прибыль, ставки,
  причины отсутствия числа. Общий низ, у него нет зависимостей от базы;
- `breakdown.py` — три разреза (бумаги, классы, деньги) за один проход;
- `service.py` — этот файл: что читается из базы, в каком порядке считается и
  как складывается в отчёт.

Имена периодов, причин и строк отчёта остаются доступны отсюда: на них
опираются обработчик, прогон и тесты, и переезд файлов не их забота.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import portfolio_overview
from app.models import Account, DailySnapshot
from app.returns.breakdown import (  # noqa: F401 — часть публичного лица пакета
    MONEY_CLASSES,
    MONEY_ROW_CLASS,
    AssetClassRow,
    InstrumentRow,
    instrument_and_class_rows,
)
from app.returns.flows import (
    Unattributed,
    account_flows,
    cash_movement,
    portfolio_flows,
    unattributed_flows,
    unconverted_flows,
)
from app.returns.metrics import (  # noqa: F401 — часть публичного лица пакета
    PERIOD_12M,
    PERIOD_ALL,
    PERIOD_YTD,
    PERIODS,
    REASON_CASH,
    REASON_EMPTY_PERIOD,
    REASON_NO_FLOWS,
    REASON_NO_FULL_DAYS,
    REASON_NO_HISTORY,
    REASON_NO_SOLUTION,
    REASON_SERIES_GAPS,
    Metric,
    Period,
    incomplete_days,
    metric,
    period_bounds,
    series,
    series_start,
)
from app.positions.service import ledger_entries
from app.returns.rates import RateBook
from app.snapshots.service import snapshot_account_values
from app.timeutils import moscow_today


@dataclass(frozen=True)
class AccountRow:
    account_id: int
    metric: Metric


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


def _snapshots(session: Session, since: date | None, until: date) -> list[DailySnapshot]:
    """Снимки внутри периода. Именно они, а не более широкий набор, отвечают за
    покрытие: «на скольких датах периода оценка была полна»."""
    query = select(DailySnapshot).where(DailySnapshot.on_date <= until)
    if since is not None:
        query = query.where(DailySnapshot.on_date >= since)
    return list(session.execute(query.order_by(DailySnapshot.on_date)).scalars().all())


def opening_snapshot(session: Session, since: date | None) -> DailySnapshot | None:
    """Последний снимок ДО периода — точка отсчёта.

    Публичная: этой же точкой отсчёта пользуется прогон (`check.py`), когда
    восстанавливает потоки портфеля, чтобы дисконтировать их по найденной
    ставке. Своя копия правила «что считать началом» разошлась бы с этой при
    первой же правке — а тогда прогон проверял бы не ту ставку, что на экране.

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
    opening = opening_snapshot(session, period.since)
    chart = ([opening] if opening is not None else []) + snapshots

    # Неполнота оценки — свойство дня, а не периметра: цена, которой не нашлось,
    # занижает и общую стоимость, и разбивку по счетам и классам. Множество
    # считается один раз и достаётся всем цепочкам отчёта.
    incomplete = incomplete_days(chart)

    total_series = series(chart, lambda row: row.total_value)
    flows = portfolio_flows(session, book, period.since, period.until)
    portfolio, chain = metric(flows, series_start(opening, lambda row: row.total_value),
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
        account_series = [(day, values[account.id]) for day, values in chart_values
                          if account.id in values]
        account_metric, _ = metric(
            account_flows(session, book, account.id, period.since, period.until),
            opening_values.get(account.id, Decimal("0")),
            by_account_now.get(account.id, Decimal("0")), account_series, period,
            incomplete)
        by_account.append(AccountRow(account_id=account.id, metric=account_metric))

    unattributed = unattributed_flows(session, book, period.since, period.until)
    instrument_rows, by_class = instrument_and_class_rows(
        session, book, period, chart, opening,
        [ledger_entries(session, account) for account in accounts], by_class_now,
        incomplete, cash_movement(session, book, period.since, period.until), cash_now)

    # Полных дней — столько, сколько снимков периода не попало в неполные.
    # Правило «какой день полный» живёт в `incomplete_days` и только там: две
    # его записи разъехались бы при первой же правке одной из них.
    valued = len(snapshots) - len(incomplete_days(snapshots))
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
