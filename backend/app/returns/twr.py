from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.returns.flows import CashFlow
from app.returns.xirr import DAYS_IN_YEAR

# Четыре знака — как у всех долей в проекте. Проценты и округление до десятых —
# дело интерфейса, здесь хранится величина.
PRECISION = Decimal("0.0001")


@dataclass(frozen=True)
class Chain:
    """Результат цепочки. `breaks` — сколько дней выпало из неё: у них не было
    базы для сравнения (нулевая или отрицательная стоимость накануне). Число
    важнее самой ставки: цепочка с разрывами отвечает на вопрос лишь частично, и
    молчать об этом нельзя."""

    rate: Decimal | None
    days: int
    breaks: int


def twr(values: list[tuple[date, Decimal]], flows: list[CashFlow]) -> Chain:
    """Доходность, очищенная от влияния пополнений и изъятий.

    За каждый день стоимость сравнивается с предыдущей, увеличенной на вложения
    этого дня. Знак потока — владельческий (вложение отрицательно), поэтому
    вложение прибавляется к базе вычитанием: `V_prev - flow.amount`.
    """
    if len(values) < 2:
        return Chain(rate=None, days=0, breaks=0)

    ordered = sorted(values)
    by_day: dict[date, Decimal] = {}
    for flow in flows:
        by_day[flow.on_date] = by_day.get(flow.on_date, Decimal("0")) + flow.amount

    product = Decimal("1")
    breaks = 0
    for (_, previous), (day, current) in zip(ordered, ordered[1:]):
        base = previous - by_day.get(day, Decimal("0"))
        if base <= 0:
            # Ни роста, ни падения измерить нельзя: сравнивать не с чем.
            # Множитель нейтральный, а факт разрыва уезжает наверх числом.
            breaks += 1
            continue
        product *= current / base

    days = (ordered[-1][0] - ordered[0][0]).days
    return Chain(rate=(product - Decimal("1")).quantize(PRECISION), days=days,
                 breaks=breaks)


def annualize(rate: Decimal, days: int) -> Decimal:
    """Пересчёт доходности за период в годовую.

    Применяется только к периодам от года: на более коротких результат врёт
    кратно (два процента за месяц превращаются в двадцать семь годовых), и
    служба показывает такую доходность как есть, с подписью «за период».
    """
    if days <= 0:
        return rate.quantize(PRECISION)
    exponent = DAYS_IN_YEAR / Decimal(days)
    return ((Decimal("1") + rate) ** exponent - Decimal("1")).quantize(PRECISION)
