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


def test_day_with_partial_valuation_leaves_the_chain():
    """Замер 14.08.2026: 11.11.2020 стоимость «падает» с 660 802 ₽ до 282 663 ₽
    за сутки — не рынок обвалился, а не удалось оценить две позиции из
    двенадцати. Такой день не входит в цепочку ни измеряемой величиной, ни
    базой для следующего дня: занижённая стоимость врёт дважды — сначала
    провалом, потом мнимым отскоком."""
    values = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("43")),
        (date(2024, 1, 3), Decimal("105")),
        (date(2024, 1, 4), Decimal("110")),
    ]
    chain = twr(values, [], incomplete={date(2024, 1, 2)})
    assert chain.rate == Decimal("0.0476")
    assert chain.breaks == 2


def test_gap_in_the_series_breaks_the_chain():
    """Замер 14.08.2026 по классу `mixed`: соседние точки ряда — 17.02.2021
    (213 494,51 ₽) и 28.06.2021 (8,90 ₽), между ними четыре месяца снимков без
    этого класса. Фонды продали внутри дыры, и продажа выпала из ряда вместе со
    своим потоком — цепочка приняла её за падение в ноль и дала −100 %. Шаг
    берётся только между соседними календарными днями."""
    values = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("110")),
        (date(2024, 5, 2), Decimal("1")),
    ]
    chain = twr(values, [])
    assert chain.rate == Decimal("0.1000")
    assert chain.breaks == 1


def test_chain_without_a_single_measured_step_has_no_rate():
    """Все дни неполны — цепочка не «дала ноль», а не построилась. Ноль был бы
    утверждением «портфель ничего не заработал», и на живой базе оно ложно: с
    августа 2025 полной оценки нет ни у одного дня."""
    values = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("43")),
        (date(2024, 1, 3), Decimal("105")),
    ]
    chain = twr(values, [], incomplete={date(2024, 1, 1), date(2024, 1, 2),
                                        date(2024, 1, 3)})
    assert chain.rate is None
    assert chain.breaks == 2


def test_chain_of_full_days_is_counted_as_before():
    """Пометка неполных дней не меняет ничего там, где оценка полна."""
    values = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("110")),
        (date(2024, 1, 3), Decimal("121")),
    ]
    chain = twr(values, [], incomplete={date(2024, 5, 5)})
    assert chain.rate == Decimal("0.2100")
    assert chain.breaks == 0


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
