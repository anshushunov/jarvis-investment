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
    assert "не читается" in run_tool(session, "allocation", {"contribution_rub": "nan"})["error"]
    assert "не читается" in run_tool(session, "allocation", {"contribution_rub": "Infinity"})["error"]


def test_zero_target_group_buy_total_explains_surplus_over_contribution(session):
    """Цель 100 % на equity: неразмеченные облигации не выправляются
    пополнением — их пришлось бы продать. buy_total больше пополнения на их
    стоимость, и notes называет источник разницы словами."""
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("1"), asset_class="equity")])
    result = run_tool(session, "allocation", {})
    assert result["rebalance"]["buy_total_rub"] == "40000.00"
    assert result["rebalance"]["contribution_rub"] == "0.00"
    assert any("продажа" in note for note in result["notes"])


def test_note_names_both_unfixable_sale_and_over_target_surplus(session):
    """Пополнение ниже минимальной суммы, да ещё и с невыправляемой группой:
    equity(0.5) и other(0.5) — цели на 50/50, но other пуст, а equity уже
    выше цели. Разница между покупками и пополнением объясняется двумя
    слагаемыми: продажей unfixable и перекосом not_closed, а не одним из них."""
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equity"),
                              TargetInput(share=Decimal("0.5"), asset_class="other")])
    result = run_tool(session, "allocation", {"contribution_rub": "1000"})
    assert result["rebalance"]["over_target_rub"] == {"equity": "9500.00"}
    assert result["rebalance"]["unfixable_without_selling"] == {"unassigned": "40000.00"}
    note = next(n for n in result["notes"] if "Покупки на" in n)
    assert "продажа" in note
    assert "перекос" in note
    assert note == (
        "Покупки на 50500.00 ₽ больше пополнения на 49500.00 ₽: "
        "из них 40000.00 ₽ — продажа групп из unfixable_without_selling "
        "(пополнением их не выправить), а 9500.00 ₽ — перекос групп из "
        "not_closed_by_contribution, который этим пополнением не закрывается"
    )
