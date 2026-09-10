from decimal import Decimal

from app.ai.registry import run_tool
from app.allocation.service import TargetInput, replace_targets
from tests.test_allocation_service import two_class_portfolio


def half_and_half(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equity"),
                              TargetInput(share=Decimal("0.5"), asset_class="bonds")])


def test_allocation_reports_gap_and_minimal_contribution(session):
    half_and_half(session)
    result = run_tool(session, "allocation", {})
    rows = {row["key"]: row for row in result["targets"]}
    assert rows["equity"]["actual_share"] == "0.6000"
    assert rows["equity"]["deviation_points"] == "10.00"
    assert rows["equity"]["deviation_rub"] == "10000.00"
    assert result["rebalance"]["minimal_contribution_rub"] == "20000.00"
    assert result["rebalance"]["buy_by_group"] == {"equity": "0.00", "bonds": "20000.00"}
    assert result["rebalance"]["contribution_is_custom"] is False
    assert any("лотность" in note for note in result["notes"])


def test_allocation_with_custom_sum_below_minimal_says_so(session):
    half_and_half(session)
    result = run_tool(session, "allocation", {"contribution_rub": "5 000"})
    assert result["rebalance"]["contribution_is_custom"] is True
    assert result["rebalance"]["short_by_rub"] == "15000.00"
    assert result["rebalance"]["not_closed_by_contribution"] == ["equity"]


def test_allocation_without_targets_points_to_settings(session):
    two_class_portfolio(session)
    result = run_tool(session, "allocation", {})
    assert result["targets"][0]["key"] == "unassigned"
    assert any("не заданы" in note for note in result["notes"])


def test_allocation_refuses_unreadable_or_negative_sum(session):
    assert "не читается" in run_tool(session, "allocation", {"contribution_rub": "много"})["error"]
    assert "отрицательной" in run_tool(session, "allocation", {"contribution_rub": "-1"})["error"]
