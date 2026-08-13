from datetime import date
from decimal import Decimal

from app.models import OperationType
from app.returns.check import check_returns
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument
from tests.test_returns_service import add_snapshot


def test_check_prints_reconciliation_of_parts(session, account):
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 8, 13), amount="100000")
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 8, 14), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 8, 14), amount="-450")
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    lines = check_returns(session)
    text = "\n".join(lines)
    assert "Прибыль портфеля" in text
    assert "Прочее" in text
    # Разбор сходимости разрезов с целым — главное, ради чего прогон существует.
    assert "Расхождение" in text


def test_check_survives_empty_database(session):
    """Пустая база — законное состояние (первый запуск). Прогон обязан сказать
    это словами, а не упасть с исключением."""
    lines = check_returns(session)
    assert any("нет" in line.lower() for line in lines)
