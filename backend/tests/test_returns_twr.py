from datetime import date
from decimal import Decimal

from app.returns.flows import CashFlow
from app.returns.twr import annualize, twr


def flow(day: date, amount: str) -> CashFlow:
    return CashFlow(on_date=day, amount=Decimal(amount), account_id=1, transaction_id=1)


def test_growth_without_flows_is_plain_growth():
    values = [(date(2024, 1, 1), Decimal("100")), (date(2024, 1, 2), Decimal("110"))]
    chain = twr(values, [])
    assert chain.rate == Decimal("0.1000")
    assert chain.breaks == 0


def test_deposit_does_not_count_as_return():
    """Главное, ради чего TWR вообще нужен: сто рублей стали двумястами не
    потому, что портфель вырос, а потому, что владелец занёс ещё сотню."""
    values = [(date(2024, 1, 1), Decimal("100")), (date(2024, 1, 2), Decimal("200"))]
    chain = twr(values, [flow(date(2024, 1, 2), "-100")])
    assert chain.rate == Decimal("0.0000")


def test_withdrawal_does_not_count_as_loss():
    values = [(date(2024, 1, 1), Decimal("200")), (date(2024, 1, 2), Decimal("100"))]
    chain = twr(values, [flow(date(2024, 1, 2), "100")])
    assert chain.rate == Decimal("0.0000")


def test_chain_multiplies_daily_returns():
    values = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("110")),
        (date(2024, 1, 3), Decimal("121")),
    ]
    chain = twr(values, [])
    assert chain.rate == Decimal("0.2100")


def test_zero_base_breaks_the_chain_and_is_counted():
    """Портфель обнулился и был заведён заново: делить на ноль нельзя, а
    промолчать об этом — значит выдать неполную цепочку за полную."""
    values = [
        (date(2024, 1, 1), Decimal("0")),
        (date(2024, 1, 2), Decimal("50")),
        (date(2024, 1, 3), Decimal("55")),
    ]
    chain = twr(values, [])
    assert chain.breaks == 1
    assert chain.rate == Decimal("0.1000")


def test_single_point_has_no_chain():
    chain = twr([(date(2024, 1, 1), Decimal("100"))], [])
    assert chain.rate is None
    assert chain.days == 0


def test_empty_series_has_no_chain():
    assert twr([], []).rate is None


def test_days_counts_calendar_span():
    values = [(date(2024, 1, 1), Decimal("100")), (date(2024, 12, 31), Decimal("120"))]
    assert twr(values, []).days == 365


def test_annualize_shrinks_a_short_period():
    """Два процента за месяц — это не двадцать четыре процента годовых, а
    двадцать семь: рост складывается сам с собой."""
    assert abs(annualize(Decimal("0.02"), 30) - Decimal("0.2724")) < Decimal("0.0001")


def test_annualize_leaves_a_year_alone():
    assert annualize(Decimal("0.15"), 365) == Decimal("0.1500")
