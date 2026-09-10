import logging
from datetime import datetime, timezone
from decimal import Decimal

from app.accounts.cash import store_cash
from app.ai.errors import ToolRefusal
from app.ai.registry import INTERNAL_ERROR, ToolSpec, run_tool
from app.connectors.base import BrokerCash
from app.models import SyncRun
from tests.test_analytics import add_account, seed


def test_overview_answers_with_money_as_strings(session):
    seed(session)
    result = run_tool(session, "portfolio_overview", {})
    assert result["total_value_rub"] == "7350.00"
    assert result["by_account"][0]["title"] == "Брокерский (acc-1)"
    assert result["by_account"][0]["value_rub"] == "7350.00"
    assert result["coverage"] == {
        "positions_total": 3, "valued_positions": 3, "unpriced": [], "currencies_without_rate": [],
    }
    assert result["as_of"] is not None
    assert result["last_sync"] is None


def test_overview_reports_the_last_finished_sync(session):
    seed(session)
    session.add(SyncRun(broker="tbank", status="success", inserted=12,
                        finished_at=datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)))
    session.flush()
    result = run_tool(session, "portfolio_overview", {})
    assert result["last_sync"]["status"] == "success"
    assert result["last_sync"]["finished_at"].startswith("2026-09-08")


def test_refusal_becomes_an_answer(session, monkeypatch):
    def refusing(session):
        raise ToolRefusal("Нет такого счёта")
    monkeypatch.setattr("app.ai.registry.TOOLS", [ToolSpec("fake", "тест", refusing)])
    assert run_tool(session, "fake", {}) == {"error": "Нет такого счёта"}


def test_unexpected_failure_is_logged_and_answered_without_numbers(session, monkeypatch, caplog):
    def broken(session):
        raise RuntimeError("boom")
    monkeypatch.setattr("app.ai.registry.TOOLS", [ToolSpec("fake", "тест", broken)])
    with caplog.at_level(logging.ERROR, logger="app.ai.registry"):
        result = run_tool(session, "fake", {})
    assert result == {"error": INTERNAL_ERROR.format(name="fake")}
    assert "boom" in caplog.text


def test_unknown_tool_is_an_answer(session):
    result = run_tool(session, "nonexistent", {})
    assert "error" in result
    assert "nonexistent" in result["error"]
    assert "portfolio_overview" in result["error"]


def test_account_without_fx_rate_appears_with_null_value(session):
    seed(session)
    acc2 = add_account(session, external_id="acc-2")
    store_cash(session, acc2, [BrokerCash(currency="XAG", amount=Decimal("5"), blocked=Decimal("0"))])
    session.flush()
    result = run_tool(session, "portfolio_overview", {})
    # Ищем acc-2 в by_account: денег есть, курса нет — счёт всё равно должен быть виден.
    acc2_entry = next((entry for entry in result["by_account"] if entry["account_id"] == acc2.id), None)
    assert acc2_entry is not None
    assert acc2_entry["value_rub"] is None
    assert len(acc2_entry["cash"]) == 1
    assert acc2_entry["cash"][0]["currency"] == "XAG"
    assert acc2_entry["cash"][0]["amount"] == "5.00"
    assert "XAG" in result["coverage"]["currencies_without_rate"]
