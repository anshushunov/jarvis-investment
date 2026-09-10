from datetime import date, timezone

from app.ai.registry import run_tool
from app.models import OperationType
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument


def test_ledger_aggregates_whole_selection_but_pages_rows(session, account):
    """Журнал — двенадцать тысяч операций: страница — сотня, а итог считается
    по всей выборке. Без агрегатов модель посчитала бы итог по первой странице
    и не заметила бы подмены."""
    instrument = add_instrument(session)
    for day_no in (1, 2, 3):
        add_tx(session, account_id=account.id, op_type=OperationType.BUY,
               day=date(2024, 3, day_no), amount="-1000", quantity="1", price="1000",
               instrument_id=instrument.id, fee="-5")
    add_tx(session, account_id=account.id, op_type=OperationType.DIVIDEND,
           day=date(2024, 4, 1), amount="300", instrument_id=instrument.id)

    result = run_tool(session, "ledger", {"instrument_id": instrument.id, "limit": 2})
    assert result["total"] == 4
    assert result["returned"] == 2
    assert result["truncated"] is True
    assert result["rows"][0]["date"] == "2024-04-01"
    assert result["rows"][0]["instrument"]["ticker"] == "AGRO"
    assert {(row["op_type"], row["count"], row["amount"]) for row in result["sums"]} == {
        ("BUY", 3, "-3000.00"), ("DIVIDEND", 1, "300.00"),
    }
    assert result["date_range"] == {"from": "2024-03-01", "to": "2024-04-01"}


def test_ledger_offset_beyond_end_is_not_truncated(session, account):
    """Страница за пределами выборки — не то же самое, что усечённая: строк
    больше нет вообще, а не «есть, но не показаны»."""
    instrument = add_instrument(session)
    for day_no in (1, 2, 3):
        add_tx(session, account_id=account.id, op_type=OperationType.BUY,
               day=date(2024, 3, day_no), amount="-1000", quantity="1", price="1000",
               instrument_id=instrument.id, fee="-5")
    add_tx(session, account_id=account.id, op_type=OperationType.DIVIDEND,
           day=date(2024, 4, 1), amount="300", instrument_id=instrument.id)

    result = run_tool(session, "ledger", {"instrument_id": instrument.id, "offset": 10})
    assert result["total"] == 4
    assert result["returned"] == 0
    assert result["beyond_end"] is True
    assert result["truncated"] is False


def test_ledger_day_bounds_are_moscow_days(session, account):
    """21:00 UTC 1 марта — это уже полночь 2 марта по Москве: календарная дата
    операции обязана совпадать с той, в которой живут снимки."""
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="100", at_hour=21, tz=timezone.utc)
    assert run_tool(session, "ledger", {"since": date(2024, 3, 2), "until": date(2024, 3, 2)})["total"] == 1
    assert run_tool(session, "ledger", {"until": date(2024, 3, 1)})["total"] == 0


def test_ledger_refuses_unknown_op_type_listing_known(session):
    error = run_tool(session, "ledger", {"op_types": ["PURCHASE"]})["error"]
    assert "PURCHASE" in error
    assert "BUY" in error


def test_ledger_filters_by_op_type_case_insensitively(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 3, 1), amount="100")
    add_tx(session, account_id=account.id, op_type=OperationType.FEE,
           day=date(2024, 3, 1), amount="-1")
    assert run_tool(session, "ledger", {"op_types": ["deposit"]})["total"] == 1


def test_ledger_refuses_unknown_instrument_and_account(session):
    assert "find_instrument" in run_tool(session, "ledger", {"instrument_id": 999})["error"]
    assert "Счёта 999 нет" in run_tool(session, "ledger", {"account_id": 999})["error"]
