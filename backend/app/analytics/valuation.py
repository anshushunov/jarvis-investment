from dataclasses import dataclass
from decimal import Decimal

from app.marketdata.fx import to_base
from app.marketdata.service import LatestPrice
from app.money import money


@dataclass(frozen=True)
class ValuedPosition:
    """Оценка позиции в двух валютах сразу.

    `value` — в валюте самой бумаги: столько стоит позиция там, где она
    торгуется. `value_base` — то же в рублях, и оно может отсутствовать, когда
    `value` есть: цена известна, а курса на дату нет. Различать эти два случая
    обязательно — иначе валютная позиция без курса тихо выпадет из капитала и
    ничем себя не обнаружит.
    """

    value: Decimal | None
    value_base: Decimal | None
    currency: str | None
    price: Decimal | None
    price_source: str | None


def value_position(
    quantity: Decimal, price: LatestPrice | None, rates: dict[str, Decimal]
) -> ValuedPosition:
    """Стоимость позиции по последней цене и курсам на дату оценки.

    Знак количества сохраняется: короткая позиция стоит отрицательных денег,
    это обязательство, а не ноль.
    """
    if price is None:
        return ValuedPosition(value=None, value_base=None, currency=None,
                              price=None, price_source=None)

    value = money(quantity * price.close)
    return ValuedPosition(
        value=value,
        value_base=to_base(value, price.currency, rates),
        currency=price.currency,
        price=price.close,
        price_source=price.source,
    )
