from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.marketdata.service import LatestPrice
from app.money import money
from app.positions.engine import OpenLot
from app.returns.rates import RateBook
from app.timeutils import moscow_date

# Причины, по которым прибыль неизвестна. Каждая называется на экране словами:
# пустая ячейка без объяснения — это вопрос, на который система не отвечает.
REASON_NO_COST_BASIS = "no_cost_basis"
REASON_NO_PRICE = "no_price"
REASON_NO_RATE = "no_rate"
REASON_CURRENCY_MISMATCH = "currency_mismatch"


@dataclass(frozen=True)
class Split:
    """Прибыль открытой позиции и её разложение.

    `price_part` — что дала сама бумага, по курсу на дату покупки.
    `fx_part` — что дало движение рубля. Их сумма тождественно равна `total`:
    перекрёстный член отнесён к валютной части целиком (дизайн, раздел 4.4).
    """

    price_part: Decimal | None
    fx_part: Decimal | None
    total: Decimal | None
    reason: str | None


def _unknown(reason: str) -> Split:
    return Split(price_part=None, fx_part=None, total=None, reason=reason)


def split_position(lots: list[OpenLot], price: LatestPrice | None, price_currency: str,
                   cost_currency: str, book: RateBook, on_date: date) -> Split:
    """Разложение прибыли позиции по её открытым партиям.

    Партии считаются по отдельности и складываются: у позиции, набранной за три
    года, единой даты покупки не существует, а курс на дату покупки — половина
    ответа.
    """
    if price is None:
        return _unknown(REASON_NO_PRICE)
    if any(not lot.cost_known for lot in lots):
        return _unknown(REASON_NO_COST_BASIS)
    if price_currency.upper() != cost_currency.upper():
        # Средняя цена в одной валюте, котировка в другой: вычитание даст курс,
        # а не доходность. Пересчёт тут возможен, но требует курса на дату
        # каждой операции ПО НОМИНАЛУ бумаги — это уже другой расчёт.
        return _unknown(REASON_CURRENCY_MISMATCH)

    rate_now = book.rate(price_currency, on_date)
    if rate_now is None:
        return _unknown(REASON_NO_RATE)

    price_part = Decimal("0")
    fx_part = Decimal("0")
    for lot in lots:
        opened = moscow_date(lot.opened_at)
        rate_then = book.rate(cost_currency, opened)
        if rate_then is None:
            return _unknown(REASON_NO_RATE)

        quantity = lot.quantity_left
        price_part += quantity * (price.close - lot.price) * rate_then
        fx_part += quantity * price.close * (rate_now - rate_then)

    return Split(price_part=money(price_part), fx_part=money(fx_part),
                 total=money(price_part + fx_part), reason=None)
