from decimal import Decimal

import pytest

from app.allocation.rebalance import Group, minimal_contribution, rebalance


def groups(*items):
    return [Group(key=key, target=Decimal(target), value=Decimal(value))
            for key, target, value in items]


def test_minimal_contribution_leaves_no_surplus():
    """Акции 60 при цели 50 %, облигации 40 при цели 50 %: докинуть 20 в
    облигации — и обе группы ровно на цели, ни одна не выше."""
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "40")))
    assert result.minimal_contribution == Decimal("20.0000")
    assert result.deficits == {"equity": Decimal("0.0000"), "bonds": Decimal("20.0000")}
    assert result.not_closed == []
    assert result.short_by == Decimal("0")


def test_sum_of_deficits_equals_minimal_contribution_on_uneven_numbers():
    """Тождество дизайна (раздел 4.4): Σ max(0, t_i·(V+X) − v_i) = X при
    минимальном X. Числа нарочно не делятся нацело — проверяется тождество, а
    не совпадение чисел."""
    items = groups(("equity", "0.6", "70"), ("bonds", "0.4", "30"))
    result = rebalance(items)
    assert abs(sum(result.deficits.values()) - result.minimal_contribution) <= Decimal("0.0001")
    assert result.minimal_contribution == minimal_contribution(items)


def test_zero_target_group_is_unfixable_and_named_with_its_value():
    """Группа с целью «ноль», в которой что-то лежит, пополнением не
    выправляется никогда: v_i / t_i не определено. Она названа отдельно, с
    суммой, которую пришлось бы продать."""
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "30"),
                              ("derivatives", "0", "10")))
    assert result.minimal_contribution == Decimal("20.0000")
    assert result.unfixable == {"derivatives": Decimal("10.0000")}
    # Дефициты закрывают и то, что лежит в невыправляемой группе: 30 = 20 + 10.
    assert sum(result.deficits.values()) == Decimal("30.0000")
    assert result.buy_total == result.contribution + sum(result.unfixable.values())


def test_contribution_below_minimal_names_groups_left_above_target():
    """Своя сумма меньше минимальной: расчёт так и говорит и называет группы,
    чей перекос этой суммой не закрывается. Молча распределить меньшее и сделать
    вид, что доли выровнены, он не имеет права."""
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "40")), Decimal("5"))
    assert result.short_by == Decimal("15.0000")
    assert result.not_closed == ["equity"]
    assert result.deficits == {"equity": Decimal("0.0000"), "bonds": Decimal("12.5000")}


def test_contribution_above_minimal_is_spread_by_deficits():
    result = rebalance(groups(("equity", "0.5", "60"), ("bonds", "0.5", "40")), Decimal("50"))
    assert result.deficits == {"equity": Decimal("15.0000"), "bonds": Decimal("35.0000")}
    assert sum(result.deficits.values()) == result.contribution
    assert result.not_closed == []
    assert result.short_by == Decimal("0")


def test_empty_portfolio_needs_nothing_but_spreads_a_given_sum_by_targets():
    empty = groups(("equity", "0.7", "0"), ("bonds", "0.3", "0"))
    assert rebalance(empty).minimal_contribution == Decimal("0.0000")
    assert rebalance(empty, Decimal("100")).deficits == {
        "equity": Decimal("70.0000"), "bonds": Decimal("30.0000"),
    }


def test_negative_contribution_is_refused():
    with pytest.raises(ValueError, match="отрицательной"):
        rebalance(groups(("equity", "1", "10")), Decimal("-1"))
