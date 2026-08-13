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

    Позиция без открытых партий (`lots` пуст) даёт нули, а не `None`: у неё
    нет нереализованной прибыли, но это не тот же случай, что «прибыль
    неизвестна» — `reason` в этом случае тоже `None`.
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

    raw_price_part = Decimal("0")
    raw_fx_part = Decimal("0")
    for lot in lots:
        opened = moscow_date(lot.opened_at)
        rate_then = book.rate(cost_currency, opened)
        if rate_then is None:
            return _unknown(REASON_NO_RATE)

        quantity = lot.quantity_left
        raw_price_part += quantity * (price.close - lot.price) * rate_then
        raw_fx_part += quantity * price.close * (rate_now - rate_then)

    total = money(raw_price_part + raw_fx_part)
    price_part = money(raw_price_part)
    # Валютная часть получается вычитанием, а не собственным округлением:
    # только так «части = целое» держится копейка в копейку при любых числах,
    # а не на удачных. Остаток округления достаётся ей же — туда уже отнесён
    # перекрёстный член (дизайн, раздел 4.4), и второе такое решение сюда не
    # добавляется.
    return Split(price_part=price_part, fx_part=total - price_part,
                 total=total, reason=None)
