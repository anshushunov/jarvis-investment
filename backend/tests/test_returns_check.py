from datetime import date
from decimal import Decimal

from app.models import OperationType
from app.returns.check import check_returns
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument
from tests.test_returns_service import add_price, add_snapshot


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


def test_check_names_instruments_without_profit(session, account):
    """Расхождение обязано объясняться поимённо. Бумага без цены выпадает из
    суммы по бумагам целиком, и прогон называет её вместе с причиной — иначе
    остаток читается как невязка, а не как список причин (дизайн, раздел 7)."""
    instrument = add_instrument(session, isin="HK0001000123", ticker="0001",
                                currency="HKD")
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 8, 14), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "130000")

    text = "\n".join(check_returns(session))
    assert "Прибыль не посчитана у бумаг" in text
    assert "0001" in text
    assert "no_price" in text
    # Вклад бумаги в расхождение — число, а не только имя: без него остаток
    # по-прежнему читался бы невязкой.
    assert "вклад" in text
    assert "остаётся" in text


def test_check_compares_parts_with_unrealized_profit(session, account):
    """Части сверяются с нереализованной прибылью, а не с прибылью за период:
    у бумаги с частичной продажей это разные величины, и прежняя проверка
    тревожила там, где всё верно."""
    instrument = add_instrument(session)
    add_tx(session, account_id=account.id, op_type=OperationType.BUY,
           day=date(2024, 8, 14), amount="-100000", quantity="100", price="1000",
           instrument_id=instrument.id)
    add_tx(session, account_id=account.id, op_type=OperationType.SELL,
           day=date(2025, 8, 14), amount="60000", quantity="50", price="1200",
           instrument_id=instrument.id)
    add_price(session, instrument.id, date(2026, 8, 13), "1300")
    add_snapshot(session, date(2024, 8, 13), "100000")
    add_snapshot(session, date(2026, 8, 13), "65000")

    text = "\n".join(check_returns(session))
    assert "Нереализованная прибыль открытых позиций: 15000.0000 ₽" in text
    assert "Части сходятся с нереализованной прибылью" in text


def test_check_survives_empty_database(session):
    """Пустая база — законное состояние (первый запуск). Прогон обязан сказать
    это словами, а не упасть с исключением."""
    lines = check_returns(session)
    assert any("нет" in line.lower() for line in lines)
