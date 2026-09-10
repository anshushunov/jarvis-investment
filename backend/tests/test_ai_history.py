from datetime import date, timedelta
from decimal import Decimal

from app.ai.registry import run_tool
from app.models import Price
from tests.test_returns_instrument_flows import add_instrument
from tests.test_returns_service import add_price, add_snapshot


def test_value_history_thins_long_series_and_counts_incomplete_days(session):
    start = date(2024, 1, 1)
    for offset in range(400):
        add_snapshot(session, start + timedelta(days=offset), str(100000 + offset),
                     valued=1 if offset % 2 else 0)
    result = run_tool(session, "value_history", {})
    assert result["granularity"] == "week"
    assert result["points_total"] == 400
    assert result["points_returned"] < 70
    assert result["points"][-1]["date"] == (start + timedelta(days=399)).isoformat()
    assert result["points"][-1]["complete"] is True
    assert result["days_incomplete"] == 200


def test_value_history_window_and_refusal(session):
    add_snapshot(session, date(2026, 1, 1), "1")
    result = run_tool(session, "value_history", {"since": date(2026, 1, 1), "until": date(2026, 1, 31)})
    assert result["points_total"] == 1
    assert result["granularity"] == "day"
    assert result["points"][0]["value_rub"] == "1.00"
    empty = run_tool(session, "value_history", {"since": date(2025, 1, 1), "until": date(2025, 1, 31)})
    assert "нет" in empty["error"]


def test_instrument_prices_names_gaps_and_prefers_exchange_price(session):
    instrument = add_instrument(session)
    add_price(session, instrument.id, date(2026, 1, 1), "100")
    add_price(session, instrument.id, date(2026, 1, 2), "101")
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 1, 2), close=Decimal("999"),
                      currency="RUB", source="tbank"))
    add_price(session, instrument.id, date(2026, 1, 22), "105")
    result = run_tool(session, "instrument_prices", {"instrument_id": instrument.id})
    assert [point["close"] for point in result["points"]] == ["100.0000", "101.0000", "105.0000"]
    assert result["gaps"] == [{"from": "2026-01-02", "to": "2026-01-22", "days": 20}]
    assert result["instrument"]["ticker"] == "AGRO"


def test_instrument_prices_refuses_unknown_instrument(session):
    assert "find_instrument" in run_tool(session, "instrument_prices", {"instrument_id": 12345})["error"]
