"""Выравнивание долей пополнением — чистая арифметика (дизайн 5a, раздел 4.4).

Ни базы, ни целей как сущностей: на входе группы с целевой долей и фактом, на
выходе — сколько докинуть и куда. Модуль зовёт инструмент `allocation` (фаза
5a), позовут экран 4d и панель чата 5b, поэтому он лежит рядом с остальным
расчётным слоем, а не внутри инструмента.

Обозначения: V — стоимость портфеля, v_i — стоимость группы, t_i — её цель,
Σt_i = 1 (группа «не задано» входит в список с остатком цели). Пополнение
тратится только на покупки — продаж расчёт не предлагает.
"""

from dataclasses import dataclass
from decimal import Decimal

from app.money import money


@dataclass(frozen=True)
class Group:
    key: str
    # Целевая доля от всего портфеля, от 0 до 1. Ноль — законная цель: «этого
    # в портфеле быть не должно».
    target: Decimal
    # Факт в рублях. У группы, которую оценить нечем, сюда приходит ноль, а
    # оговорка живёт у вызывающего — он знает, чего именно не хватило.
    value: Decimal


@dataclass(frozen=True)
class Rebalance:
    total_value: Decimal
    # Минимальная сумма, после которой ни одна группа не превышает цель:
    # X = max_i(v_i / t_i) − V.
    minimal_contribution: Decimal
    # Сумма, по которой посчитана раскладка: минимальная либо переданная.
    contribution: Decimal
    # Раскладка пополнения по группам: дефицит каждой при V + X.
    deficits: dict[str, Decimal]
    # Группы с целью «ноль», в которых что-то лежит: пополнением не
    # выправляются никогда и названы вместе с суммой, которую пришлось бы
    # продать.
    unfixable: dict[str, Decimal]
    # Группы, чей перекос переданной суммой не закрывается (она меньше
    # минимальной). Пусто, когда суммы достаточно.
    not_closed: list[str]
    # На сколько переданная сумма меньше минимальной. Ноль — достаточна.
    short_by: Decimal


def minimal_contribution(groups: list[Group]) -> Decimal:
    """X = max_i(v_i / t_i) − V, не меньше нуля.

    При таком X у группы с наибольшим перекосом факт ровно равен цели, у
    остальных — ниже, и сумма дефицитов равна X: это тождество, и проверяется
    оно тестом, а не совпадением чисел. Группы с целью ноль в максимум не
    входят: v_i / 0 не определено, такая группа выправляется только продажей
    (см. Rebalance.unfixable).
    """
    total = sum((group.value for group in groups), Decimal("0"))
    needed = max((group.value / group.target for group in groups if group.target > 0),
                 default=Decimal("0"))
    return money(max(Decimal("0"), needed - total))


def deficits_at(groups: list[Group], contribution: Decimal) -> dict[str, Decimal]:
    """Сколько не хватает каждой группе до цели после пополнения на `contribution`."""
    total = sum((group.value for group in groups), Decimal("0")) + contribution
    return {
        group.key: money(max(Decimal("0"), group.target * total - group.value))
        for group in groups if group.target > 0
    }


def rebalance(groups: list[Group], contribution: Decimal | None = None) -> Rebalance:
    if contribution is not None and contribution < 0:
        raise ValueError("Сумма пополнения не может быть отрицательной: продаж расчёт не предлагает")

    total = money(sum((group.value for group in groups), Decimal("0")))
    minimal = minimal_contribution(groups)
    applied = minimal if contribution is None else money(contribution)
    deficits = deficits_at(groups, applied)

    unfixable = {group.key: money(group.value) for group in groups
                 if group.target == 0 and group.value > 0}
    short = applied < minimal
    not_closed = [group.key for group in groups
                  if short and group.target > 0 and group.target * (total + applied) < group.value]

    return Rebalance(
        total_value=total, minimal_contribution=minimal, contribution=applied,
        deficits=deficits, unfixable=unfixable, not_closed=not_closed,
        short_by=money(minimal - applied) if short else Decimal("0"),
    )
