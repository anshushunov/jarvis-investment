from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.ai.registry import run_tool
from app.models import DailySnapshot, Instrument, Reconciliation, SyncRun
from tests.test_analytics import seed


def test_data_quality_names_reconciliations_unpriced_days_and_sync(session):
    account = seed(session)
    sber = session.execute(select(Instrument).where(Instrument.ticker == "SBER")).scalar_one()
    session.add(Reconciliation(account_id=account.id, instrument_id=sber.id, isin=sber.isin,
                               ledger_quantity=Decimal("10"), broker_quantity=Decimal("12"),
                               status="quantity_mismatch"))
    for day in (date(2026, 1, 1), date(2026, 1, 2)):
        session.add(DailySnapshot(on_date=day, total_value=Decimal("1"), source="backfill",
                                  positions_total=2, valued_positions=1, unpriced=["HeadHunter"]))
    session.add_all([
        SyncRun(broker="tbank", account_id=account.id, status="failed", error="сеть",
                started_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                finished_at=datetime(2026, 9, 1, 0, 1, tzinfo=timezone.utc)),
        SyncRun(broker="tbank", account_id=account.id, status="success", inserted=3,
                started_at=datetime(2026, 9, 8, tzinfo=timezone.utc),
                finished_at=datetime(2026, 9, 8, 0, 1, tzinfo=timezone.utc)),
    ])
    session.flush()

    result = run_tool(session, "data_quality", {})
    mismatch = result["reconciliation"]["unresolved"][0]
    assert mismatch["account"]["title"] == "Брокерский (acc-1)"
    assert mismatch["name"] == "Сбербанк"
    assert mismatch["status"] == "quantity_mismatch"
    assert mismatch["ledger_quantity"] == "10"
    assert mismatch["broker_quantity"] == "12"
    assert result["history"]["instruments_without_price"] == [{"name": "HeadHunter", "days": 2}]
    assert result["history"]["days_fully_valued"] == 0
    assert result["history"]["share_fully_valued"] == "0.0000"
    assert result["sync"]["last_runs"] == [{
        **result["sync"]["last_runs"][0], "status": "success", "inserted": 3,
    }]
    assert "valuation_check" in result["broker_total_check"]


def test_data_quality_on_empty_database_answers_without_numbers_made_up(session):
    result = run_tool(session, "data_quality", {})
    assert result["reconciliation"]["count"] == 0
    assert result["history"]["snapshots"] == 0
    assert result["history"]["share_fully_valued"] is None
