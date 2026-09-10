from decimal import Decimal

import pytest

from app.allocation.service import (
    UNASSIGNED_KEY,
    AllocationError,
    TargetInput,
    allocation_report,
    list_targets,
    replace_targets,
)
from tests.test_analytics import add_account, add_priced_position


def two_class_portfolio(session):
    """Акции 60 000 ₽ и облигации 40 000 ₽ — перекос, который видно глазами."""
    account = add_account(session)
    add_priced_position(session, account, "RU0009029540", Decimal("100"), Decimal("600"))
    add_priced_position(session, account, "RU000A101234", Decimal("40"), Decimal("1000"), kind="bond")
    return account


def test_targets_are_replaced_as_a_whole(session):
    replace_targets(session, [TargetInput(share=Decimal("0.6"), asset_class="equity")])
    stored = replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="bonds")])
    assert [(row.asset_class, row.share) for row in stored] == [("bonds", Decimal("0.5000"))]
    assert [row.asset_class for row in list_targets(session)] == ["bonds"]


def test_sum_over_one_is_refused(session):
    with pytest.raises(AllocationError, match="превышает 100"):
        replace_targets(session, [TargetInput(share=Decimal("0.7"), asset_class="equity"),
                                  TargetInput(share=Decimal("0.4"), asset_class="bonds")])


def test_unknown_class_is_refused(session):
    with pytest.raises(AllocationError, match="Неизвестный класс"):
        replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equities")])


def test_instrument_inside_targeted_class_is_refused(session):
    """Одно пространство целей: если у акций цель 60 %, у Сбера собственной
    цели быть не может — один рубль посчитался бы дважды."""
    two_class_portfolio(session)
    with pytest.raises(AllocationError, match="уже задана цель"):
        replace_targets(session, [TargetInput(share=Decimal("0.6"), asset_class="equity"),
                                  TargetInput(share=Decimal("0.1"), isin="RU0009029540")])


def test_instrument_target_resolves_by_isin(session):
    two_class_portfolio(session)
    stored = replace_targets(session, [TargetInput(share=Decimal("0.1"), isin="RU0009029540")])
    assert stored[0].instrument_id is not None
    assert stored[0].asset_class is None


def test_unknown_isin_is_refused(session):
    with pytest.raises(AllocationError, match="не найдена"):
        replace_targets(session, [TargetInput(share=Decimal("0.1"), isin="XX0000000000")])


def test_report_measures_deviation_and_minimal_contribution(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equity"),
                              TargetInput(share=Decimal("0.5"), asset_class="bonds")])
    report = allocation_report(session)
    rows = {row.key: row for row in report.rows}
    assert report.total_value == Decimal("100000.0000")
    assert rows["equity"].actual == Decimal("0.6000")
    assert rows["equity"].deviation_points == Decimal("10.00")
    assert rows["equity"].deviation_rub == Decimal("10000.0000")
    assert UNASSIGNED_KEY not in rows
    assert report.rebalance.minimal_contribution == Decimal("20000.0000")
    assert report.rebalance.deficits == {"equity": Decimal("0.0000"), "bonds": Decimal("20000.0000")}
    # Тождество дизайна: сумма дефицитов равна минимальному пополнению.
    assert sum(report.rebalance.deficits.values()) == report.rebalance.minimal_contribution


def test_unassigned_group_takes_the_rest(session):
    """Сумма целей не обязана быть сотней: остаток — группа «не задано» с
    фактом, равным всему, что не покрыто целями."""
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), asset_class="equity")])
    rows = {row.key: row for row in allocation_report(session).rows}
    assert rows[UNASSIGNED_KEY].target == Decimal("0.5000")
    assert rows[UNASSIGNED_KEY].value == Decimal("40000.0000")


def test_value_outside_full_targets_is_unfixable_by_contribution(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("1"), asset_class="equity")])
    report = allocation_report(session)
    assert report.rebalance.unfixable == {UNASSIGNED_KEY: Decimal("40000.0000")}
    # Цель равна 100 % на «equity», дефицит 40 000 финансируется продажей
    # неразмеченной группы — deficits считает и его.
    assert report.rebalance.buy_total == Decimal("40000.0000")


def test_instrument_target_is_measured_by_its_position(session):
    two_class_portfolio(session)
    replace_targets(session, [TargetInput(share=Decimal("0.5"), isin="RU000A101234")])
    rows = {row.key: row for row in allocation_report(session).rows}
    assert rows["RU000A101234"].value == Decimal("40000.0000")
    assert rows["RU000A101234"].actual == Decimal("0.4000")


def test_report_without_targets_says_so(session):
    two_class_portfolio(session)
    report = allocation_report(session)
    assert report.rows[0].key == UNASSIGNED_KEY
    assert report.rows[0].target == Decimal("1.0000")
    assert any("не заданы" in note for note in report.notes)
