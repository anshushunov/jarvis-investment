from datetime import date
from decimal import Decimal

from app.returns.xirr import Flow, npv, xirr


def test_year_of_ten_percent():
    """Тысяча рублей, вложенная на ровно 365 дней и вернувшаяся 1100, — это
    десять процентов годовых, и никакого метода тут не нужно, чтобы это знать."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("1100")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert abs(rate - Decimal("0.1")) < Decimal("0.0001")


def test_loss_gives_negative_rate():
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("500")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert abs(rate - Decimal("-0.5")) < Decimal("0.0001")


def test_same_sign_flows_have_no_rate():
    """Ставки не существует: деньги только вносились. None — это ответ, а не
    сбой, и вызывающий обязан назвать причину словами."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("-500")),
    ]
    assert xirr(flows) is None


def test_empty_and_single_flow():
    assert xirr([]) is None
    assert xirr([Flow(date(2021, 1, 1), Decimal("-1000"))]) is None


def test_zero_result_is_minus_one_hundred_percent():
    """Вложил и почти ничего не вернул: ставка у нижней границы поиска."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("1")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert rate < Decimal("-0.99")


def test_root_outside_search_range_has_no_rate():
    """Убыток настолько полный, что ставка уходит ниже границы поиска
    (−1000 → +0,01 за год даёт −99,999 %). Вернуть край отрезка значило бы
    выдать границу поиска за результат расчёта — поэтому None."""
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("0.01")),
    ]
    assert xirr(flows) is None


def test_result_satisfies_its_own_definition():
    """Признак готовности фазы, пункт 1: дисконтирование потоков по найденной
    ставке даёт ноль в пределах копейки. Набор нарочно неровный — семь лет,
    разные знаки, суммы от сотен рублей до миллионов."""
    flows = [
        Flow(date(2020, 7, 16), Decimal("-1500000")),
        Flow(date(2021, 3, 2), Decimal("-250000")),
        Flow(date(2022, 9, 12), Decimal("340")),
        Flow(date(2023, 11, 30), Decimal("-780000")),
        Flow(date(2025, 5, 5), Decimal("120000")),
        Flow(date(2026, 8, 13), Decimal("3100000")),
    ]
    rate = xirr(flows)
    assert rate is not None
    assert abs(npv(flows, rate)) < Decimal("0.01")


def test_npv_at_zero_rate_is_plain_sum():
    flows = [
        Flow(date(2021, 1, 1), Decimal("-1000")),
        Flow(date(2022, 1, 1), Decimal("1100")),
    ]
    assert npv(flows, Decimal("0")) == Decimal("100")
