from datetime import date, datetime, timezone
from decimal import Decimal

from app.accounts.cash_history import cash_history
from app.models import CashBalance, OperationType, Transaction


def _tx(session, account, *, day: str, op_type: OperationType, amount: str,
        currency: str = "RUB", quantity: str = "0", fee: str = "0",
        payload: dict | None = None, external_id: str = "x") -> Transaction:
    tx = Transaction(
        account_id=account.id, instrument_id=None, op_type=op_type,
        executed_at=datetime.fromisoformat(day), quantity=Decimal(quantity),
        price=Decimal("0"), amount=Decimal(amount), currency=currency,
        fee=Decimal(fee), external_id=external_id, source="tbank",
        dedup_key=f"k-{external_id}", payload=payload or {},
    )
    session.add(tx)
    session.flush()
    return tx


def _balance(session, account, currency: str, amount: str) -> None:
    session.add(CashBalance(account_id=account.id, currency=currency,
                            amount=Decimal(amount), blocked=Decimal("0")))
    session.flush()


def test_yesterday_is_today_minus_todays_flows(session, account):
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00",
        op_type=OperationType.DEPOSIT, amount="400", external_id="a")

    history = cash_history(session, date(2024, 6, 3), date(2024, 6, 5))

    assert history[date(2024, 6, 5)][account.id]["RUB"] == Decimal("1000.0000")
    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("600.0000")
    assert history[date(2024, 6, 3)][account.id]["RUB"] == Decimal("600.0000")


def test_fee_is_subtracted_together_with_the_amount(session, account):
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00",
        op_type=OperationType.BUY, amount="-400", fee="10", external_id="a")

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("1410.0000")


def test_currency_purchase_moves_both_legs(session, account):
    """Покупка юаня — двуногая операция: рубли уходят суммой, юани приходят
    количеством. Без второй ноги история валютных остатков не сходится ни на
    одном счёте: живой замер давал −43 338 HKD при нуле у брокера."""
    _balance(session, account, "RUB", "1000")
    _balance(session, account, "CNY", "200")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.BUY,
        amount="-2145.80", quantity="200", external_id="a",
        payload={"instrument_kind": "currency", "figi": "BBG0013HRTL0"})

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("3145.8000")
    assert history[date(2024, 6, 4)][account.id]["CNY"] == Decimal("0.0000")


def test_currency_sale_moves_both_legs_the_other_way(session, account):
    _balance(session, account, "RUB", "1000")
    _balance(session, account, "USD", "50")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.SELL,
        amount="4000", quantity="50", external_id="a",
        payload={"instrument_kind": "currency", "figi": "BBG0013HGFT4"})

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("-3000.0000")
    assert history[date(2024, 6, 4)][account.id]["USD"] == Decimal("100.0000")


def test_unknown_currency_figi_moves_only_the_rouble_leg(session, account, caplog):
    """Незнакомый валютный псевдоинструмент не угадывается: угаданная валюта
    молча испортила бы историю остатков, а запись в логе даёт починить
    сопоставление."""
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.BUY,
        amount="-500", quantity="7", external_id="a",
        payload={"instrument_kind": "currency", "figi": "BBG00НЕИЗВЕСТНО"})

    with caplog.at_level("WARNING"):
        history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id]["RUB"] == Decimal("1500.0000")
    assert "BBG00НЕИЗВЕСТНО" in caplog.text


def test_ordinary_share_purchase_has_no_second_leg(session, account):
    """У покупки акции количество — это бумаги, а не деньги: вторая нога тут
    была бы выдумкой."""
    _balance(session, account, "RUB", "1000")
    _tx(session, account, day="2024-06-05T10:00:00+00:00", op_type=OperationType.BUY,
        amount="-500", quantity="7", external_id="a",
        payload={"instrument_kind": "share", "figi": "BBG004730N88"})

    history = cash_history(session, date(2024, 6, 4), date(2024, 6, 5))

    assert history[date(2024, 6, 4)][account.id] == {"RUB": Decimal("1500.0000")}
