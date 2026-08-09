from datetime import datetime, timezone
from decimal import Decimal

from app.positions.engine import LedgerEntry, fold
from app.models import OperationType

D = Decimal


def at(day: int) -> datetime:
    return datetime(2026, 3, day, 10, 0, tzinfo=timezone.utc)


def entry(op_type, day, qty="0", price="0", amount="0", fee="0", instrument_id=1):
    return LedgerEntry(
        op_type=op_type, executed_at=at(day), instrument_id=instrument_id,
        quantity=D(qty), price=D(price), amount=D(amount), fee=D(fee),
    )


def test_single_buy_creates_position():
    result = fold([entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000")])
    position = result.positions[1]
    assert position.quantity == D("10")
    assert position.average_price == D("100.0000")


def test_average_price_is_weighted():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="30", price="200", amount="-6000"),
    ])
    assert result.positions[1].average_price == D("175.0000")


def test_partial_sale_consumes_oldest_lot_first():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="10", price="200", amount="-2000"),
        entry(OperationType.SELL, 3, qty="10", price="300", amount="3000"),
    ])
    position = result.positions[1]
    assert position.quantity == D("10")
    assert position.average_price == D("200.0000")

    sale = result.realized[0]
    assert sale.cost == D("1000.0000")
    assert sale.proceeds == D("3000.0000")
    assert sale.opened_at == at(1)


def test_sale_splitting_a_lot_leaves_remainder():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.SELL, 2, qty="4", price="150", amount="600"),
    ])
    position = result.positions[1]
    assert position.quantity == D("6")
    assert position.lots[0].quantity_left == D("6")
    assert result.realized[0].cost == D("400.0000")


def test_full_exit_leaves_zero_position():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.SELL, 2, qty="10", price="120", amount="1200"),
    ])
    assert result.positions[1].quantity == D("0")
    assert result.positions[1].lots == []


def test_dividend_does_not_change_quantity_but_changes_cash():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.DIVIDEND, 5, amount="340.50"),
    ])
    assert result.positions[1].quantity == D("10")
    assert result.cash["RUB"] == D("-659.5000")


def test_redemption_closes_bond_position():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="1000", amount="-10000"),
        entry(OperationType.REDEMPTION, 9, qty="10", price="1000", amount="10000"),
    ])
    assert result.positions[1].quantity == D("0")


def test_redemption_without_quantity_closes_the_whole_position():
    """Брокер по погашению облигации присылает сумму, но не количество
    (quantity=0 — проверено на живом ответе T-Invest API). Полное погашение по
    смыслу закрывает выпуск целиком, поэтому количество тут и не нужно: без
    этого погашенные бумаги висят в портфеле вечно — так на живом счёте
    остались ОФЗ 25083 (124 штуки) и РУСАЛ БО-001Р-06 (10 штук)."""
    result = fold([
        entry(OperationType.BUY, 1, qty="100", price="1000", amount="-100000"),
        entry(OperationType.BUY, 2, qty="24", price="1000", amount="-24000"),
        entry(OperationType.REDEMPTION, 9, qty="0", price="0", amount="124000"),
    ])
    assert result.positions[1].quantity == D("0")
    assert result.positions[1].lots == []
    # Выплата распределяется по партиям — их себестоимость остаётся своей.
    assert sum(sale.proceeds for sale in result.realized) == D("124000.0000")
    assert len(result.realized) == 2


def test_redemption_without_quantity_and_without_position_does_nothing():
    result = fold([entry(OperationType.REDEMPTION, 9, qty="0", price="0", amount="5000")])
    assert result.positions == {}
    assert result.realized == []
    assert result.cash["RUB"] == D("5000.0000")


def test_amortization_pays_cash_without_touching_quantity():
    result = fold([
        entry(OperationType.BUY, 1, qty="45", price="750", amount="-33750"),
        entry(OperationType.AMORTIZATION, 5, qty="0", price="0", amount="11250"),
    ])
    assert result.positions[1].quantity == D("45")
    assert result.cash["RUB"] == D("-22500.0000")


def test_deposit_only_affects_cash():
    result = fold([entry(OperationType.DEPOSIT, 1, amount="50000", instrument_id=None)])
    assert result.positions == {}
    assert result.cash["RUB"] == D("50000.0000")


def test_fee_reduces_cash():
    result = fold([entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000", fee="5")])
    assert result.cash["RUB"] == D("-1005.0000")


def test_selling_more_than_owned_opens_a_short_for_the_excess():
    """Продажа сверх остатка — не ошибка данных, а короткая позиция: на живом
    счёте владельца так торговали (13.11.2020 продано 10000 АФК «Система» при
    нулевом остатке). Прежний движок излишек молча отбрасывал, и последующая
    закрывающая покупка оседала в портфеле бумагой, которой у владельца нет."""
    result = fold([
        entry(OperationType.BUY, 1, qty="5", price="100", amount="-500"),
        entry(OperationType.SELL, 2, qty="8", price="150", amount="1200"),
    ])
    position = result.positions[1]
    assert position.quantity == D("-3")
    # Средняя цена короткой позиции — цена, по которой её открыли.
    assert position.average_price == D("150.0000")
    assert result.realized[0].quantity == D("5")


def test_short_closed_by_buyback_leaves_no_position():
    """Главный сценарий ради которого всё: продать без остатка и выкупить
    обратно. Итог обязан быть нулём и исчезнуть из портфеля — именно так по
    живым данным устроены SBER, TSLA, DSKY и ещё одиннадцать бумаг."""
    result = fold([
        entry(OperationType.SELL, 1, qty="10", price="200", amount="2000"),
        entry(OperationType.BUY, 2, qty="10", price="180", amount="-1800"),
    ])
    assert result.positions[1].quantity == D("0")
    assert result.positions[1].lots == []


def test_buyback_of_a_short_realizes_profit_of_the_short():
    """Прибыль шорта считается наоборот: выручка — цена открытия (продажи),
    себестоимость — цена закрытия (выкупа)."""
    result = fold([
        entry(OperationType.SELL, 1, qty="10", price="200", amount="2000"),
        entry(OperationType.BUY, 2, qty="10", price="180", amount="-1800"),
    ])
    sale = result.realized[0]
    assert sale.quantity == D("10")
    assert sale.proceeds == D("2000.0000")
    assert sale.cost == D("1800.0000")
    assert sale.opened_at == at(1)
    assert sale.sold_at == at(2)


def test_buying_more_than_the_short_flips_into_a_long():
    result = fold([
        entry(OperationType.SELL, 1, qty="10", price="200", amount="2000"),
        entry(OperationType.BUY, 2, qty="15", price="180", amount="-2700"),
    ])
    position = result.positions[1]
    assert position.quantity == D("5")
    assert position.average_price == D("180.0000")


def test_short_grows_across_several_sales_and_covers_oldest_first():
    result = fold([
        entry(OperationType.SELL, 1, qty="10", price="200", amount="2000"),
        entry(OperationType.SELL, 2, qty="10", price="300", amount="3000"),
        entry(OperationType.BUY, 3, qty="10", price="180", amount="-1800"),
    ])
    position = result.positions[1]
    assert position.quantity == D("-10")
    # Закрыт старший шорт (по 200), остался открытым тот, что по 300.
    assert position.average_price == D("300.0000")
    assert result.realized[0].proceeds == D("2000.0000")


def test_operations_are_sorted_by_time_regardless_of_input_order():
    unsorted_entries = [
        entry(OperationType.SELL, 3, qty="10", price="300", amount="3000"),
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="10", price="200", amount="-2000"),
    ]
    result = fold(unsorted_entries)
    assert result.realized[0].cost == D("1000.0000")


def test_sale_spanning_multiple_lots():
    result = fold([
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
        entry(OperationType.BUY, 2, qty="20", price="200", amount="-4000"),
        entry(OperationType.SELL, 3, qty="15", price="300", amount="4500"),
    ])
    position = result.positions[1]
    assert position.quantity == D("15")
    assert position.average_price == D("200.0000")

    assert len(result.realized) == 2
    assert result.realized[0].quantity == D("10")
    assert result.realized[0].cost == D("1000.0000")
    assert result.realized[0].proceeds == D("3000.0000")
    assert result.realized[0].opened_at == at(1)

    assert result.realized[1].quantity == D("5")
    assert result.realized[1].cost == D("1000.0000")
    assert result.realized[1].proceeds == D("1500.0000")
    assert result.realized[1].opened_at == at(2)


def test_sale_of_never_bought_instrument_opens_a_short():
    """Продажа бумаги, которой в журнале не покупали, — это короткая позиция, а
    не пустое место. Спрятать её значит потерять расхождение: именно так на
    живом счёте видны NVDA и KD, где брокер не прислал операцию по дроблению
    акций и выделению компании, и продано больше, чем куплено."""
    result = fold([
        entry(OperationType.SELL, 1, qty="10", price="300", amount="3000", instrument_id=99),
    ])
    assert result.positions[99].quantity == D("-10")
    assert result.realized == []
    assert result.cash["RUB"] == D("3000.0000")


def test_zero_quantity_buy_does_not_create_lot():
    result = fold([
        entry(OperationType.BUY, 1, qty="0", price="100", amount="-0"),
        entry(OperationType.BUY, 2, qty="10", price="200", amount="-2000"),
    ])
    assert result.positions[1].quantity == D("10")
    assert len(result.positions[1].lots) == 1
    assert result.positions[1].average_price == D("200.0000")


def test_buy_and_sell_same_time_buy_first():
    entries = [
        entry(OperationType.SELL, 1, qty="10", price="300", amount="3000"),
        entry(OperationType.BUY, 1, qty="10", price="100", amount="-1000"),
    ]
    result = fold(entries)
    # After sorting, BUY should be processed first despite being later in input
    # This allows the SELL to match the newly bought shares
    assert result.positions[1].quantity == D("0")
    assert len(result.realized) == 1
    assert result.realized[0].cost == D("1000.0000")
