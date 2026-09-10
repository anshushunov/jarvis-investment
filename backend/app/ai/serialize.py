"""Форма ответа инструментов (дизайн 5a, раздел 4.1): деньги строками, даты
ISO, имена — те же, что на экране.

Одно место на весь реестр: девять инструментов отдают суммы одинаково, и
второе правило форматирования рядом разъехалось бы с первым при первой правке.
"""

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import TypeVar

from app.accounts.labels import account_label
from app.models import Account, Instrument
from app.money import money

T = TypeVar("T")

# Шаги ряда. «auto» подбирает шаг по длине окна: полный ряд за шесть лет —
# 2220 точек, столько в ответе не нужно никому, а месячный шаг за две недели
# оставил бы одну точку.
GRANULARITIES = ("auto", "day", "week", "month")
DAY_LIMIT = 120
WEEK_LIMIT = 730


def amount(value: Decimal | None) -> str | None:
    """Сумма денег строкой с копейками: "846124.16". None остаётся None —
    величина, которой нет, нулём не заполняется."""
    if value is None:
        return None
    rounded = money(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:.2f}"


def rate(value: Decimal | None) -> str | None:
    """Доля строкой: "0.0331" — это 3,31 %."""
    return None if value is None else f"{value:.4f}"


def percent(value: Decimal | None) -> str | None:
    """Проценты строкой с двумя знаками: "50.00"."""
    return None if value is None else f"{value:.2f}"


def price(value: Decimal | None) -> str | None:
    """Цена — с четырьмя знаками: у облигаций и гонконгских бумаг копеек мало."""
    return None if value is None else f"{value:.4f}"


def qty(value: Decimal | None) -> str | None:
    """Количество без хвостовых нулей: "100", "0.5". Через format(…, "f"), а не
    str(): normalize() у сотни даёт "1E+2"."""
    return None if value is None else format(value.normalize(), "f")


def day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def moment(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def instrument_name(instrument: Instrument) -> str:
    """То же имя, каким бумага подписана на экране: эмитент, иначе тикер, иначе ISIN."""
    return instrument.issuer or instrument.ticker or instrument.isin or "—"


def instrument_ref(instrument: Instrument) -> dict:
    return {"instrument_id": instrument.id, "name": instrument_name(instrument),
            "ticker": instrument.ticker, "isin": instrument.isin}


def account_ref(account: Account) -> dict:
    return {"account_id": account.id, "title": account_label(account), "broker": account.broker}


def auto_granularity(days: int) -> str:
    if days <= DAY_LIMIT:
        return "day"
    return "week" if days <= WEEK_LIMIT else "month"


def thin(points: list[T], pick_date: Callable[[T], date], granularity: str) -> list[T]:
    """Прореживает ряд: последняя точка каждой недели или месяца. Последняя
    точка ряда остаётся всегда — ответ «как двигалась стоимость» без
    сегодняшней точки неполон."""
    if granularity == "day" or not points:
        return list(points)
    if granularity == "week":
        def bucket(value: date):
            return value.isocalendar()[:2]
    else:
        def bucket(value: date):
            return (value.year, value.month)
    kept: list[T] = []
    for index, current in enumerate(points):
        following = points[index + 1] if index + 1 < len(points) else None
        if following is None or bucket(pick_date(current)) != bucket(pick_date(following)):
            kept.append(current)
    return kept
