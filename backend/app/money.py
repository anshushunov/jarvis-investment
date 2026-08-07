from decimal import Decimal, ROUND_HALF_UP

MONEY_EXP = Decimal("0.0001")
QUANTITY_EXP = Decimal("0.00000001")
NANO = Decimal("1000000000")


def _to_decimal(value: str | int | Decimal) -> Decimal:
    if isinstance(value, float):
        raise TypeError("float недопустим для денежных величин, используйте str или Decimal")
    return Decimal(value)


def money(value: str | int | Decimal) -> Decimal:
    return _to_decimal(value).quantize(MONEY_EXP, rounding=ROUND_HALF_UP)


def quantity(value: str | int | Decimal) -> Decimal:
    return _to_decimal(value).quantize(QUANTITY_EXP, rounding=ROUND_HALF_UP)


def quotation_to_decimal(units: int, nano: int) -> Decimal:
    return money(Decimal(units) + Decimal(nano) / NANO)
