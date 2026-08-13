from datetime import date, datetime, timezone
from decimal import Decimal

from app.marketdata.service import LatestPrice
from app.positions.engine import OpenLot
from app.returns.fx_split import (
    REASON_CURRENCY_MISMATCH,
    REASON_NO_COST_BASIS,
    REASON_NO_PRICE,
    REASON_NO_RATE,
    split_position,
)
from app.returns.rates import RateBook


def lot(price: str, quantity: str, opened: date, cost_known: bool = True) -> OpenLot:
    return OpenLot(instrument_id=1,
                   opened_at=datetime.combine(opened, datetime.min.time(), tzinfo=timezone.utc),
                   price=Decimal(price), quantity_left=Decimal(quantity),
                   cost_known=cost_known)


def price_at(close: str, currency: str = "RUB") -> LatestPrice:
    return LatestPrice(close=Decimal(close), on_date=date(2026, 8, 13),
                       currency=currency, source="moex")


def book_with(rates: dict[tuple[str, date], str]) -> RateBook:
    series: dict[str, tuple[list, list]] = {}
    for (currency, on_date), value in sorted(rates.items(), key=lambda item: item[0][1]):
        dates, values = series.setdefault(currency, ([], []))
        dates.append(on_date)
        values.append(Decimal(value))
    return RateBook(series)


def test_rouble_position_has_no_currency_part():
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=price_at("150"), price_currency="RUB",
                           cost_currency="RUB", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.price_part == Decimal("500.0000")
    assert split.fx_part == Decimal("0.0000")
    assert split.total == Decimal("500.0000")


def test_currency_position_splits_into_two_parts():
    """Десять акций по 100 $ куплены при курсе 70, стоят 120 $ при курсе 80.
    Ценовая часть: 10·(120−100)·70 = 14 000 ₽. Валютная: 10·120·(80−70) =
    12 000 ₽. Вместе 26 000 ₽ — ровно 10·(120·80 − 100·70)."""
    book = book_with({("USD", date(2024, 1, 10)): "70", ("USD", date(2026, 8, 13)): "80"})
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=price_at("120", "USD"), price_currency="USD",
                           cost_currency="USD", book=book, on_date=date(2026, 8, 13))
    assert split.price_part == Decimal("14000.0000")
    assert split.fx_part == Decimal("12000.0000")
    assert split.total == Decimal("26000.0000")


def test_parts_always_sum_to_total():
    """Признак готовности фазы, пункт 2. Партии с разными датами и курсами —
    самый вероятный случай разъезда."""
    book = book_with({
        ("USD", date(2021, 3, 1)): "74.2",
        ("USD", date(2023, 9, 15)): "96.5",
        ("USD", date(2026, 8, 13)): "81.3",
    })
    split = split_position(
        lots=[lot("125.5", "8", date(2021, 3, 1)), lot("210.75", "3", date(2023, 9, 15))],
        price=price_at("187.4", "USD"), price_currency="USD", cost_currency="USD",
        book=book, on_date=date(2026, 8, 13))
    assert split.price_part + split.fx_part == split.total


def test_short_position_keeps_its_sign():
    """У короткой позиции количество отрицательное: рост цены — убыток."""
    split = split_position(lots=[lot("100", "-10", date(2024, 1, 10))],
                           price=price_at("150"), price_currency="RUB",
                           cost_currency="RUB", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.total == Decimal("-500.0000")


def test_lot_without_cost_basis_blocks_the_split():
    """351 бумага РусАгро введена переводом: себестоимости нет, и прибыль по
    позиции неизвестна. Ноль тут был бы враньём."""
    split = split_position(lots=[lot("0", "351", date(2024, 12, 19), cost_known=False)],
                           price=price_at("150"), price_currency="RUB",
                           cost_currency="RUB", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_NO_COST_BASIS


def test_missing_price_is_named():
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=None, price_currency="RUB", cost_currency="RUB",
                           book=book_with({}), on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_NO_PRICE


def test_missing_rate_is_named():
    split = split_position(lots=[lot("100", "10", date(2024, 1, 10))],
                           price=price_at("120", "USD"), price_currency="USD",
                           cost_currency="USD", book=book_with({}),
                           on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_NO_RATE


def test_currency_mismatch_is_named():
    """Замещающая облигация: расчёты рублёвые, котировка юаневая. Вычитать одно
    из другого — получить курс, а не доходность (живой RU000A10CRC4 давал так
    −98,8 %)."""
    book = book_with({("CNY", date(2024, 1, 10)): "12.5",
                      ("CNY", date(2026, 8, 13)): "11.2"})
    split = split_position(lots=[lot("8138.62", "10", date(2024, 1, 10))],
                           price=price_at("96.5", "CNY"), price_currency="CNY",
                           cost_currency="RUB", book=book, on_date=date(2026, 8, 13))
    assert split.total is None
    assert split.reason == REASON_CURRENCY_MISMATCH
