"""Инструменты value_history и instrument_prices: как двигалась стоимость и
цена, с пометкой дней неполной оценки и дыр в ряду."""

from datetime import date
from typing import Annotated, Literal

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.marketdata.service import PRICE_MAX_AGE, SOURCE_PRIORITY
from app.models import DailySnapshot, Instrument, Price
from app.returns.metrics import incomplete_days

Granularity = Literal["auto", "day", "week", "month"]
_UNKNOWN_PRIORITY = 99


def _granularity(requested: str, first: date, last: date) -> str:
    return s.auto_granularity((last - first).days) if requested == "auto" else requested


def value_history(
    session: Session,
    since: Annotated[date | None, Field(description="С даты, ГГГГ-ММ-ДД; по умолчанию с первой точки")] = None,
    until: Annotated[date | None, Field(description="По дату; по умолчанию до последней")] = None,
    granularity: Annotated[Granularity, Field(description=(
        "Шаг ряда: auto подбирает по длине окна — день до 120 дней, неделя до двух лет, дальше месяц"))] = "auto",
) -> dict:
    if since is not None and until is not None and since > until:
        raise ToolRefusal(f"Начало {since} позже конца {until}")
    query = select(DailySnapshot).order_by(DailySnapshot.on_date)
    if since is not None:
        query = query.where(DailySnapshot.on_date >= since)
    if until is not None:
        query = query.where(DailySnapshot.on_date <= until)
    rows = list(session.execute(query).scalars().all())
    if not rows:
        raise ToolRefusal("Снимков стоимости за это окно нет")

    used = _granularity(granularity, rows[0].on_date, rows[-1].on_date)
    kept = s.thin(rows, lambda row: row.on_date, used)
    # Правило «какой день полный» — одно на проект (app/returns/metrics.py):
    # неизвестное покрытие считается неполным там же, где рвётся цепочка TWR.
    incomplete = incomplete_days(rows)
    return {
        "from": s.day(rows[0].on_date), "to": s.day(rows[-1].on_date),
        "granularity": used, "points_total": len(rows), "points_returned": len(kept),
        "days_incomplete": len(incomplete),
        "points": [
            {"date": s.day(row.on_date), "value_rub": s.amount(row.total_value),
             "source": row.source, "complete": row.on_date not in incomplete,
             "unpriced": list(row.unpriced or [])}
            for row in kept
        ],
        "note": ("complete=false — в этот день часть позиций без цены, стоимость занижена (у "
                 "снимков без посчитанного покрытия — тоже false). Прореженный ряд оставляет "
                 "последнюю точку каждого шага; source=backfill — точка достроена задним числом."),
    }


def instrument_prices(
    session: Session,
    instrument_id: Annotated[int, Field(description="Идентификатор бумаги из find_instrument или positions")],
    since: Annotated[date | None, Field(description="С даты, ГГГГ-ММ-ДД")] = None,
    until: Annotated[date | None, Field(description="По дату")] = None,
    granularity: Annotated[Granularity, Field(description="Шаг ряда, как у value_history")] = "auto",
) -> dict:
    instrument = session.get(Instrument, instrument_id)
    if instrument is None:
        raise ToolRefusal(f"Бумаги с идентификатором {instrument_id} нет — найди её через find_instrument")
    if since is not None and until is not None and since > until:
        raise ToolRefusal(f"Начало {since} позже конца {until}")
    query = select(Price).where(Price.instrument_id == instrument_id).order_by(Price.on_date)
    if since is not None:
        query = query.where(Price.on_date >= since)
    if until is not None:
        query = query.where(Price.on_date <= until)

    # Одна цена на дату: при двух источниках приоритет тот же, что у оценки
    # (биржа, затем независимый источник, затем брокер).
    best: dict[date, Price] = {}
    for row in session.execute(query).scalars():
        current = best.get(row.on_date)
        if (current is None or SOURCE_PRIORITY.get(row.source, _UNKNOWN_PRIORITY)
                < SOURCE_PRIORITY.get(current.source, _UNKNOWN_PRIORITY)):
            best[row.on_date] = row
    series = [best[on_date] for on_date in sorted(best)]
    if not series:
        raise ToolRefusal(f"Котировок по {s.instrument_name(instrument)} за это окно нет")

    gaps = [
        {"from": s.day(earlier.on_date), "to": s.day(later.on_date),
         "days": (later.on_date - earlier.on_date).days}
        for earlier, later in zip(series, series[1:])
        if later.on_date - earlier.on_date > PRICE_MAX_AGE
    ]
    used = _granularity(granularity, series[0].on_date, series[-1].on_date)
    kept = s.thin(series, lambda row: row.on_date, used)
    return {
        "instrument": s.instrument_ref(instrument),
        "from": s.day(series[0].on_date), "to": s.day(series[-1].on_date),
        "granularity": used, "points_total": len(series), "points_returned": len(kept),
        "points": [{"date": s.day(row.on_date), "close": s.price(row.close),
                    "currency": row.currency, "source": row.source} for row in kept],
        "gaps": gaps,
        "note": (f"Дыра — разрыв больше {PRICE_MAX_AGE.days} дней между соседними котировками: в "
                 "такие дни бумага не оценивалась. Цена облигации — в деньгах за бумагу, не в "
                 "процентах номинала."),
    }
