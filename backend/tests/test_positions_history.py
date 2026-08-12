from datetime import date, datetime, timezone
from decimal import Decimal

from app.models import OperationType
from app.positions.engine import LedgerEntry
from app.positions.history import holdings_at


def entry(day: str, op_type: OperationType, quantity: str, price: str = "100") -> LedgerEntry:
    return LedgerEntry(
        op_type=op_type,
        executed_at=datetime.fromisoformat(day),
        instrument_id=1,
        quantity=Decimal(quantity),
        price=Decimal(price),
        amount=Decimal("0"),
        fee=Decimal("0"),
    )


ENTRIES = [
    entry("2024-06-03T10:00:00+00:00", OperationType.BUY, "10"),
    entry("2024-06-05T10:00:00+00:00", OperationType.BUY, "5"),
    entry("2024-06-07T10:00:00+00:00", OperationType.SELL, "12"),
]


def test_holdings_include_operations_of_the_day_itself():
    assert holdings_at(ENTRIES, date(2024, 6, 3))[1].quantity == Decimal("10.00000000")


def test_holdings_ignore_the_future():
    assert holdings_at(ENTRIES, date(2024, 6, 4))[1].quantity == Decimal("10.00000000")
    assert holdings_at(ENTRIES, date(2024, 6, 6))[1].quantity == Decimal("15.00000000")
    assert holdings_at(ENTRIES, date(2024, 6, 7))[1].quantity == Decimal("3.00000000")


def test_before_the_first_operation_the_portfolio_is_empty():
    assert holdings_at(ENTRIES, date(2024, 6, 2)) == {}


def test_the_day_ends_by_moscow_not_by_utc():
    """Операция 21:30 UTC — это уже 00:30 следующих суток по Москве, и в
    сегодняшний снимок она попасть не должна: снимки живут в московской
    календарной дате, и вечерняя сделка иначе оказалась бы вчерашней."""
    late = [entry("2024-06-03T21:30:00+00:00", OperationType.BUY, "10")]

    assert holdings_at(late, date(2024, 6, 3)) == {}
    assert holdings_at(late, date(2024, 6, 4))[1].quantity == Decimal("10.00000000")


def test_closed_position_is_not_returned():
    """Позиция, закрытая к дате, — это отсутствие позиции, а не ноль штук:
    иначе оценка считала бы её неоценённой и портила покрытие."""
    closed = ENTRIES + [entry("2024-06-08T10:00:00+00:00", OperationType.SELL, "3")]
    assert holdings_at(closed, date(2024, 6, 8)) == {}
