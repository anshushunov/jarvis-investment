from decimal import Decimal
from typing import Callable

from app.money import money, quotation_to_decimal, quotation_to_quantity

# REST-шлюз T-Invest API отдаёт и деньги, и количества в одной и той же форме:
# {"currency": ..., "units": "142", "nano": 500000000} (units — строка, nano —
# число). Это единственное место, которое учит остальной код терпеть
# отсутствующий или битый объект такой формы, не роняя вызов целиком.


def _parse(value: dict | None, convert: Callable[[int, int], Decimal]) -> Decimal | None:
    if not value:
        return None
    try:
        return convert(int(value["units"]), int(value["nano"]))
    except (KeyError, TypeError, ValueError):
        return None


def to_money(value: dict | None) -> Decimal:
    """Денежная величина (4 знака). Отсутствующий или битый объект → 0 —
    это безопасное значение по умолчанию для сумм."""
    result = _parse(value, quotation_to_decimal)
    return result if result is not None else money("0")


def to_quantity(value: dict | None) -> Decimal | None:
    """Величина количества с полной точностью (8 знаков). Отсутствующий или
    битый объект → None: в отличие от денег, ноль здесь не безопасное значение
    по умолчанию (позиция с нулевым количеством — это не то же самое, что
    позиция, для которой количество не удалось прочитать), поэтому решение —
    подставить ноль или пропустить запись — остаётся за вызывающим кодом."""
    return _parse(value, quotation_to_quantity)
