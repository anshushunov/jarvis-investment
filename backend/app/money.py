from decimal import Decimal, ROUND_HALF_UP

MONEY_EXP = Decimal("0.0001")
QUANTITY_EXP = Decimal("0.00000001")
NANO = Decimal("1000000000")


def _to_decimal(value: str | int | Decimal) -> Decimal:
    if isinstance(value, bool):
        raise TypeError("bool недопустим для денежных величин, используйте str, int или Decimal")
    if isinstance(value, float):
        raise TypeError("float недопустим для денежных величин, используйте str или Decimal")

    decimal_value = Decimal(value)

    if not decimal_value.is_finite():
        raise ValueError("денежная величина должна быть конечным числом (не NaN и не Infinity)")

    return decimal_value


def money(value: str | int | Decimal) -> Decimal:
    return _to_decimal(value).quantize(MONEY_EXP, rounding=ROUND_HALF_UP)


def quantity(value: str | int | Decimal) -> Decimal:
    return _to_decimal(value).quantize(QUANTITY_EXP, rounding=ROUND_HALF_UP)


def quotation_to_decimal(units: int, nano: int) -> Decimal:
    return money(Decimal(units) + Decimal(nano) / NANO)


def quotation_to_quantity(units: int, nano: int) -> Decimal:
    """Как quotation_to_decimal, но сохраняет полную точность количества (8
    знаков вместо денежных 4). quotation_to_decimal здесь не подходит: если
    сначала округлить до 4 знаков через money(), а потом расширить до 8 через
    quantity(), то `units=10, nano=123456789` превратится в 10.1235 вместо
    10.12345679 — точность будет потеряна необратимо ещё на первом шаге."""
    return quantity(Decimal(units) + Decimal(nano) / NANO)
