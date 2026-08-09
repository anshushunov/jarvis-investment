from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest

from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.models import OperationType


def make_op(**overrides) -> RawOperation:
    defaults = dict(
        external_id=None,
        op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc),
        isin="RU0009029540",
        ticker="SBER",
        quantity=Decimal("35"),
        price=Decimal("142.5"),
        amount=Decimal("-4987.5"),
        currency="RUB",
        fee=Decimal("1.4963"),
        payload={},
    )
    return RawOperation(**{**defaults, **overrides})


def test_same_operation_gives_same_key():
    assert natural_key("tbank", "acc-1", make_op()) == natural_key("tbank", "acc-1", make_op())


def test_payload_does_not_affect_key():
    assert natural_key("tbank", "acc-1", make_op(payload={"a": 1})) == natural_key(
        "tbank", "acc-1", make_op(payload={"b": 2})
    )


def test_different_quantity_gives_different_key():
    assert natural_key("tbank", "acc-1", make_op()) != natural_key(
        "tbank", "acc-1", make_op(quantity=Decimal("36"))
    )


def test_different_account_gives_different_key():
    assert natural_key("tbank", "acc-1", make_op()) != natural_key("tbank", "acc-2", make_op())


def test_trailing_zeros_in_decimal_do_not_change_key():
    assert natural_key("tbank", "acc-1", make_op(quantity=Decimal("35"))) == natural_key(
        "tbank", "acc-1", make_op(quantity=Decimal("35.00"))
    )


def test_same_moment_utc_and_plus3_give_same_key():
    """Операция в UTC и та же операция в +03:00 должны давать одинаковый ключ."""
    # 2026-03-12 10:30 UTC
    utc_time = datetime(2026, 3, 12, 10, 30, tzinfo=timezone.utc)
    # 2026-03-12 13:30 +03:00 (на 3 часа вперёд) — это то же самое время
    plus3_tz = timezone(timedelta(hours=3))
    plus3_time = datetime(2026, 3, 12, 13, 30, tzinfo=plus3_tz)

    assert natural_key("tbank", "acc-1", make_op(executed_at=utc_time)) == natural_key(
        "tbank", "acc-1", make_op(executed_at=plus3_time)
    )


def test_naive_datetime_is_rejected():
    """Наивный datetime без часового пояса отвергается."""
    naive_dt = datetime(2026, 3, 12, 10, 30)
    with pytest.raises(ValueError, match="timezone-aware"):
        make_op(executed_at=naive_dt)


def test_negative_zero_and_positive_zero_give_same_key():
    """Decimal(-0.00) и Decimal(0.00) в сумме дают одинаковый ключ."""
    assert natural_key("tbank", "acc-1", make_op(amount=Decimal("-0.00"))) == natural_key(
        "tbank", "acc-1", make_op(amount=Decimal("0.00"))
    )


def test_float_in_quantity_is_rejected():
    """float в quantity отвергается."""
    with pytest.raises(TypeError, match="float недопустим"):
        make_op(quantity=0.1)


def test_bool_in_price_is_rejected():
    """bool в price отвергается."""
    with pytest.raises(TypeError, match="bool недопустим"):
        make_op(price=True)
