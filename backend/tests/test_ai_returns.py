from datetime import date

from app.ai.registry import run_tool
from app.models import OperationType
from tests.test_returns_flows import add_tx
from tests.test_returns_instrument_flows import add_instrument
from tests.test_returns_service import add_snapshot


def test_returns_shape_and_all_breakdowns(session, account):
    add_tx(session, account_id=account.id, op_type=OperationType.DEPOSIT,
           day=date(2024, 1, 10), amount="100000")
    add_snapshot(session, date(2024, 1, 10), "100000")
    result = run_tool(session, "returns", {"period": "all", "breakdown": "all"})
    assert result["period"]["from"] == "2024-01-10"
    assert isinstance(result["portfolio"]["profit_rub"], str)
    assert result["twr_coverage"]["days_total"] == 1
    assert "by_account" in result
    assert "by_asset_class" in result
    assert "by_instrument" in result
    assert result["unattributed"]["profit_rub"] == "0.00"


def test_returns_default_breakdown_is_by_asset_class_only(session, account):
    add_snapshot(session, date(2024, 1, 10), "100000")
    result = run_tool(session, "returns", {})
    assert "by_asset_class" in result
    assert "by_account" not in result
    assert "by_instrument" not in result


def test_returns_without_history_is_a_refusal(session):
    assert "снимков" in run_tool(session, "returns", {})["error"]


def test_returns_custom_period_needs_bounds_and_refuses_gently(session, account):
    add_snapshot(session, date(2024, 1, 10), "100000")
    assert "custom" in run_tool(session, "returns", {"period": "all", "since": date(2024, 1, 1)})["error"]
    assert "хотя бы началом" in run_tool(session, "returns", {"period": "custom"})["error"]


def test_instruments_breakdown_is_limited_and_says_so(session, account):
    for number in range(3):
        instrument = add_instrument(session, isin=f"RU00000000{number:02d}", ticker=f"T{number}")
        add_tx(session, account_id=account.id, op_type=OperationType.BUY, day=date(2024, 1, 11),
               amount="-1000", quantity="1", price="1000", instrument_id=instrument.id)
    add_snapshot(session, date(2024, 1, 10), "3000")
    result = run_tool(session, "returns", {"breakdown": "instruments", "instruments_limit": 2})
    assert len(result["by_instrument"]) == 2
    assert result["by_instrument_total"] == 3
    assert result["by_instrument_truncated"] is True
    # Причина названа словами, а не кодом.
    assert result["by_instrument"][0]["reason"] == "нет цены на конец периода"
