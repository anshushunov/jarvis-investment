from datetime import date
from decimal import Decimal

from app.ai import serialize as s


def test_money_is_a_string_with_kopecks_and_none_stays_none():
    assert s.amount(Decimal("846124.1600")) == "846124.16"
    assert s.amount(Decimal("-0.005")) == "-0.01"
    assert s.amount(None) is None


def test_quantity_drops_trailing_zeros_without_exponent():
    assert s.qty(Decimal("100.00000000")) == "100"
    assert s.qty(Decimal("0.50000000")) == "0.5"


def test_rate_is_a_fraction_with_four_digits():
    assert s.rate(Decimal("0.03311")) == "0.0331"


def test_auto_granularity_by_window_length():
    assert s.auto_granularity(30) == "day"
    assert s.auto_granularity(400) == "week"
    assert s.auto_granularity(2220) == "month"


def test_thin_keeps_last_point_of_each_bucket_and_the_last_point():
    days = [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 5), date(2026, 2, 3), date(2026, 2, 4)]
    assert s.thin(days, lambda d: d, "month") == [date(2026, 1, 5), date(2026, 2, 4)]
    # ISO-неделя: 1–4 января 2026 — одна неделя, 5 января — следующая; 3 и 4 февраля — одна неделя, из неё остаётся последняя точка.
    assert s.thin(days, lambda d: d, "week") == [
        date(2026, 1, 2), date(2026, 1, 5), date(2026, 2, 4),
    ]
    assert s.thin(days, lambda d: d, "day") == days
