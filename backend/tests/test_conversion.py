"""Конвертация переносит открытые партии, не теряя дат открытия.

Дата важна не для красоты: трёхлетняя льгота по НДФЛ считается от неё, и
свернуть партии в одну на дату события значит сжечь льготу. Суммарная
себестоимость при переносе сохраняется, а цена пересчитывается на новое
количество.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models import OperationType
from app.positions.engine import ConversionError, LedgerEntry, fold

OLD, NEW = 1, 2
WHEN = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _buy(instrument_id: int, quantity: str, price: str, day: int) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.BUY,
        executed_at=datetime(2024, 1, day, tzinfo=timezone.utc),
        instrument_id=instrument_id, quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal("0"), fee=Decimal("0"),
    )


def _out(quantity: str, link_id: int = 7) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.CONVERSION_OUT, executed_at=WHEN,
        instrument_id=OLD, quantity=Decimal(quantity), price=Decimal("0"),
        amount=Decimal("0"), fee=Decimal("0"), link_id=link_id,
    )


def _in(quantity: str, link_id: int = 7) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.CONVERSION_IN, executed_at=WHEN,
        instrument_id=NEW, quantity=Decimal(quantity), price=Decimal("0"),
        amount=Decimal("0"), fee=Decimal("0"), link_id=link_id,
    )


def test_one_to_one_conversion_keeps_lots_and_dates():
    """Живой случай: 79 iShares HK0000310034 → 79 HK0000051877."""
    result = fold([
        _buy(OLD, "40", "100", day=10),
        _buy(OLD, "39", "150", day=20),
        _out("79"), _in("79"),
    ])

    assert OLD not in result.positions or result.positions[OLD].quantity == 0
    new = result.positions[NEW]
    assert new.quantity == Decimal("79")
    assert len(new.lots) == 2
    # Даты открытия обеих партий переехали как есть.
    assert [lot.opened_at.day for lot in new.lots] == [10, 20]
    # Цены при один-к-одному не изменились.
    assert [lot.price for lot in new.lots] == [Decimal("100"), Decimal("150")]
    # Конвертация не создаёт закрытой сделки: финансового результата нет.
    assert result.realized == []


def test_conversion_preserves_total_cost_when_quantity_changes():
    """40 бумаг по 1000 превращаются в 1012 — суммарная себестоимость та же.

    «Та же» с точностью до последнего знака цены, и иначе быть не может:
    цена — величина на одну бумагу с четырьмя знаками, а 40000 / 1012 — это
    10000 / 253, где 253 = 11 × 23, и конечной десятичной дробью такое
    частное не записывается ни при каком числе знаков. Сохраняется то, что
    сохранимо: цена — правильно округлённое частное, а суммарное расхождение
    не больше половины последнего знака цены, помноженной на количество.
    """
    result = fold([_buy(OLD, "40", "1000", day=5), _out("40"), _in("1012")])

    new = result.positions[NEW]
    assert new.quantity == Decimal("1012")
    assert new.lots[0].price == Decimal("39.5257")  # 40000 / 1012
    total_cost = sum(lot.quantity_left * lot.price for lot in new.lots)
    assert abs(total_cost - Decimal("40000")) <= new.quantity * Decimal("0.00005")
    assert new.lots[0].opened_at.day == 5


def test_conversion_gives_the_rounding_remainder_to_the_last_lot():
    """Три партии по одной бумаге превращаются в десять.

    Доля каждой — 3.33333333…, и округление долей до восьми знаков потеряло бы
    сотую долю бумаги. Количество позиции обязано совпасть с количеством в
    записи CONVERSION_IN, иначе сверка со снимком брокера навсегда покажет
    расхождение, которого на самом деле нет.
    """
    result = fold([
        _buy(OLD, "1", "300", day=1),
        _buy(OLD, "1", "300", day=2),
        _buy(OLD, "1", "300", day=3),
        _out("3"), _in("10"),
    ])

    new = result.positions[NEW]
    assert new.quantity == Decimal("10")
    assert len(new.lots) == 3
    assert [lot.opened_at.day for lot in new.lots] == [1, 2, 3]
    total_cost = sum(lot.quantity_left * lot.price for lot in new.lots)
    assert abs(total_cost - Decimal("900")) <= new.quantity * Decimal("0.00005")


def test_partial_conversion_leaves_the_rest_in_place():
    result = fold([_buy(OLD, "100", "10", day=1), _out("40"), _in("40")])

    assert result.positions[OLD].quantity == Decimal("60")
    assert result.positions[NEW].quantity == Decimal("40")


def test_conversion_in_without_out_is_an_error():
    """Пустой карман — порча данных. Молча открыть партию с нулевой ценой
    значит подарить владельцу выдуманную доходность в сотни процентов."""
    with pytest.raises(ConversionError, match="CONVERSION_IN"):
        fold([_in("79")])


def test_conversion_out_beyond_available_quantity_is_an_error():
    with pytest.raises(ConversionError, match="больше, чем открыто"):
        fold([_buy(OLD, "10", "100", day=1), _out("79"), _in("79")])


def test_unknown_cost_survives_the_conversion():
    result = fold([
        LedgerEntry(op_type=OperationType.TRANSFER_IN,
                    executed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
                    instrument_id=OLD, quantity=Decimal("50"),
                    price=Decimal("0"), amount=Decimal("0"), fee=Decimal("0")),
        _out("50"), _in("50"),
    ])

    assert result.positions[NEW].cost_basis_known is False


def test_two_conversions_at_the_same_instant_do_not_mix():
    """Два решения на одну дату различаются по link_id: карманы не общие."""
    result = fold([
        _buy(OLD, "10", "100", day=1),
        _buy(3, "20", "5", day=2),
        _out("10", link_id=1), _in("10", link_id=1),
        LedgerEntry(op_type=OperationType.CONVERSION_OUT, executed_at=WHEN,
                    instrument_id=3, quantity=Decimal("20"), price=Decimal("0"),
                    amount=Decimal("0"), fee=Decimal("0"), link_id=2),
        LedgerEntry(op_type=OperationType.CONVERSION_IN, executed_at=WHEN,
                    instrument_id=4, quantity=Decimal("20"), price=Decimal("0"),
                    amount=Decimal("0"), fee=Decimal("0"), link_id=2),
    ])

    assert result.positions[NEW].lots[0].price == Decimal("100")
    assert result.positions[4].lots[0].price == Decimal("5")


def test_adjustment_adds_quantity_with_unknown_cost():
    entry = LedgerEntry(
        op_type=OperationType.ADJUSTMENT, executed_at=WHEN, instrument_id=OLD,
        quantity=Decimal("1012"), price=Decimal("0"), amount=Decimal("0"),
        fee=Decimal("0"),
    )

    result = fold([entry])

    assert result.positions[OLD].quantity == Decimal("1012")
    assert result.positions[OLD].cost_basis_known is False
    assert result.realized == []


def test_adjustment_with_price_keeps_cost_known():
    entry = LedgerEntry(
        op_type=OperationType.ADJUSTMENT, executed_at=WHEN, instrument_id=OLD,
        quantity=Decimal("10"), price=Decimal("250"), amount=Decimal("0"),
        fee=Decimal("0"),
    )

    result = fold([entry])

    assert result.positions[OLD].cost_basis_known is True
    assert result.positions[OLD].average_price == Decimal("250")


def test_negative_adjustment_closes_lots_without_realized_sale():
    result = fold([
        _buy(OLD, "10", "100", day=1),
        LedgerEntry(op_type=OperationType.ADJUSTMENT, executed_at=WHEN,
                    instrument_id=OLD, quantity=Decimal("-2"), price=Decimal("0"),
                    amount=Decimal("0"), fee=Decimal("0")),
    ])

    assert result.positions[OLD].quantity == Decimal("8")
    assert result.realized == []
