from datetime import date
from decimal import Decimal

from app.analytics.valuation import value_position
from app.marketdata.service import LatestPrice, TBANK_SOURCE

RATES = {"RUB": Decimal("1"), "HKD": Decimal("10.4724"), "CNY": Decimal("12.1655")}


def test_rouble_position_needs_no_conversion():
    valued = value_position(
        quantity=Decimal("10"),
        price=LatestPrice(close=Decimal("300"), on_date=date(2026, 8, 9),
                          currency="RUB", source="moex"),
        rates=RATES,
    )

    assert valued.value == Decimal("3000.0000")
    assert valued.value_base == Decimal("3000.0000")
    assert valued.currency == "RUB"


def test_foreign_position_is_converted_by_rate():
    """Сорок акций по 36,90 HKD — это 1476 HKD, и по курсу 10,4724 они дают
    15 457,26 ₽. Раньше такая позиция вовсе не попадала в капитал."""
    valued = value_position(
        quantity=Decimal("40"),
        price=LatestPrice(close=Decimal("36.90"), on_date=date(2026, 8, 9),
                          currency="HKD", source=TBANK_SOURCE),
        rates=RATES,
    )

    assert valued.value == Decimal("1476.0000")
    assert valued.value_base == Decimal("15457.2624")


def test_missing_price_gives_no_value():
    valued = value_position(quantity=Decimal("10"), price=None, rates=RATES)

    assert valued.value is None and valued.value_base is None


def test_missing_rate_gives_value_in_own_currency_but_not_in_roubles():
    """Цена есть, курса нет: сумму в валюте показать можно и нужно, а в рублёвый
    итог такая позиция войти не может. Ноль вместо неё занизил бы капитал молча."""
    valued = value_position(
        quantity=Decimal("3"),
        price=LatestPrice(close=Decimal("79.20"), on_date=date(2026, 8, 9),
                          currency="USD", source=TBANK_SOURCE),
        rates=RATES,
    )

    assert valued.value == Decimal("237.6000")
    assert valued.value_base is None


def test_short_position_keeps_negative_value():
    """Короткая позиция стоит отрицательных денег — это обязательство, а не
    ноль. Движок позиций умеет шорты, и оценка обязана их не терять."""
    valued = value_position(
        quantity=Decimal("-15000"),
        price=LatestPrice(close=Decimal("2"), on_date=date(2026, 8, 9),
                          currency="RUB", source="moex"),
        rates=RATES,
    )

    assert valued.value_base == Decimal("-30000.0000")
