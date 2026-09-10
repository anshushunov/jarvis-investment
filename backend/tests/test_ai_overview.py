import logging
from datetime import datetime, timezone

from app.ai.errors import ToolRefusal
from app.ai.registry import INTERNAL_ERROR, ToolSpec, run_tool
from app.models import SyncRun
from tests.test_analytics import seed


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
