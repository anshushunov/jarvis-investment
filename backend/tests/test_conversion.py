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
from app.positions.engine import ConversionError, LedgerEntry, ReversalError, fold

OLD, NEW = 1, 2
WHEN = datetime(2026, 3, 1, tzinfo=timezone.utc)


def _buy(instrument_id: int, quantity: str, price: str, day: int) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.BUY,
        executed_at=datetime(2024, 1, day, tzinfo=timezone.utc),
        instrument_id=instrument_id, quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal("0"), fee=Decimal("0"),
    )


def _out(quantity: str, link_id: int = 7, row_id: int | None = None) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.CONVERSION_OUT, executed_at=WHEN,
        instrument_id=OLD, quantity=Decimal(quantity), price=Decimal("0"),
        amount=Decimal("0"), fee=Decimal("0"), link_id=link_id, row_id=row_id,
    )


def _in(quantity: str, link_id: int = 7, row_id: int | None = None) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.CONVERSION_IN, executed_at=WHEN,
        instrument_id=NEW, quantity=Decimal(quantity), price=Decimal("0"),
        amount=Decimal("0"), fee=Decimal("0"), link_id=link_id, row_id=row_id,
    )


def _revert(op_type: OperationType, instrument_id: int, quantity: str,
            reverts: int, row_id: int) -> LedgerEntry:
    """Сторона зеркального решения: она называет отменяемое решение, а её
    собственные количество и цена описательные — книгу восстанавливает движок
    по следу названного решения."""
    return LedgerEntry(
        op_type=op_type, executed_at=WHEN, instrument_id=instrument_id,
        quantity=Decimal(quantity), price=Decimal("0"), amount=Decimal("0"),
        fee=Decimal("0"), link_id=99, reverts_link_id=reverts, row_id=row_id,
    )


def _sell(instrument_id: int, quantity: str, price: str) -> LedgerEntry:
    return LedgerEntry(
        op_type=OperationType.SELL, executed_at=WHEN, instrument_id=instrument_id,
        quantity=Decimal(quantity), price=Decimal(price),
        amount=Decimal(quantity) * Decimal(price), fee=Decimal("0"),
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


def test_reverting_conversion_at_the_same_instant_runs_after_the_one_it_reverts():
    """Отмена решения несёт ту же дату события, что и отменяемая конвертация.

    Общий порядок «сначала все OUT одного мгновения, потом все IN» снимал бы
    бумагу у зеркальной стороны раньше, чем исходная её зачислит: конвертация
    падала бы с «списывает больше, чем открыто». Решения разбираются по одному
    целиком, в порядке появления их записей в журнале, поэтому партия проходит
    круг и возвращается той же — с прежней ценой и прежней датой открытия.
    """
    result = fold([
        _buy(OLD, "79", "120", day=1),
        _out("79", row_id=1), _in("79", row_id=2),
        _revert(OperationType.CONVERSION_OUT, NEW, "79", reverts=7, row_id=3),
        _revert(OperationType.CONVERSION_IN, OLD, "79", reverts=7, row_id=4),
    ])

    assert result.positions[NEW].quantity == 0
    assert result.positions[OLD].quantity == Decimal("79")
    assert result.positions[OLD].lots[0].opened_at.day == 1
    assert result.positions[OLD].lots[0].price == Decimal("120")


def test_reverting_a_conversion_puts_back_the_very_same_lots():
    """Отмена возвращает те самые партии, а не просто те же количества.

    Целевая бумага уже была в портфеле — 79 штук по 10 от 2020 года. Отмена,
    выраженная встречной конвертацией, сняла бы с неё по FIFO именно их:
    количества сходятся, а себестоимость и даты открытия меняются бумагами
    местами, и трёхлетняя льгота приписывается не той бумаге.
    """
    older = LedgerEntry(
        op_type=OperationType.BUY,
        executed_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        instrument_id=NEW, quantity=Decimal("79"), price=Decimal("10"),
        amount=Decimal("0"), fee=Decimal("0"),
    )

    result = fold([
        _buy(OLD, "79", "120", day=10), older,
        _out("79", row_id=1), _in("79", row_id=2),
        _revert(OperationType.CONVERSION_OUT, NEW, "79", reverts=7, row_id=3),
        _revert(OperationType.CONVERSION_IN, OLD, "79", reverts=7, row_id=4),
    ])

    assert [(lot.quantity_left, lot.price, lot.opened_at.year)
            for lot in result.positions[OLD].lots] == [(Decimal("79"), Decimal("120"), 2024)]
    assert [(lot.quantity_left, lot.price, lot.opened_at.year)
            for lot in result.positions[NEW].lots] == [(Decimal("79"), Decimal("10"), 2020)]


def test_reverting_a_conversion_whose_lots_are_already_sold_is_an_error():
    """Партии, открытые решением, успели уйти в продажу — отменять поздно.

    Промолчать значит снять чужие партии: с чужой себестоимостью и чужой датой
    открытия.
    """
    later_sale = LedgerEntry(
        op_type=OperationType.SELL,
        executed_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
        instrument_id=NEW, quantity=Decimal("40"), price=Decimal("200"),
        amount=Decimal("8000"), fee=Decimal("0"),
    )

    with pytest.raises(ReversalError, match="уже израсходованы"):
        fold([
            _buy(OLD, "79", "120", day=10),
            _out("79", row_id=1), _in("79", row_id=2),
            later_sale,
            LedgerEntry(op_type=OperationType.CONVERSION_OUT,
                        executed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                        instrument_id=NEW, quantity=Decimal("79"),
                        price=Decimal("0"), amount=Decimal("0"), fee=Decimal("0"),
                        link_id=99, reverts_link_id=7, row_id=4),
        ])


def test_conversion_in_with_zero_quantity_is_an_error():
    """Ноль на приходящей стороне — потеря молчаливая и оттого худшая.

    Снятые партии разложились бы на ноль бумаг: 79 бумаг исчезают,
    себестоимость уничтожена, а признак «себестоимость известна» остаётся
    истинным — портфель выглядит достоверным и при этом неверен.
    """
    with pytest.raises(ConversionError, match="перенести нулевое"):
        fold([_buy(OLD, "79", "120", day=1), _out("79"), _in("0")])


def test_conversion_in_closes_a_short_position():
    """Приходящая партия сначала гасит короткую позицию целевой бумаги.

    Иначе в книге лежат партии разного знака сразу (+79 по 120 и −79 по 200):
    инвариант «разнонаправленных партий в одной книге не бывает» нарушен,
    6320 прибыли в налоговую базу не попадают вовсе, а средняя цена считается
    по модулю количества и выходит 160 — число правдоподобное и неверное.
    """
    result = fold([
        _buy(OLD, "79", "120", day=10),
        _sell(NEW, "79", "200"),
        _out("79", row_id=1), _in("79", row_id=2),
    ])

    assert result.positions[NEW].lots == []
    assert result.positions[NEW].quantity == 0
    assert len(result.realized) == 1
    sale = result.realized[0]
    assert (sale.proceeds, sale.cost) == (Decimal("15800"), Decimal("9480"))


def test_reverting_a_conversion_takes_back_its_realized_sale():
    """Отмена убирает и финансовый результат, порождённый конвертацией.

    Сделки, которой больше нет, в налоговой базе быть не должно, а короткая
    позиция обязана вернуться в книгу такой, какой была.
    """
    result = fold([
        _buy(OLD, "79", "120", day=10),
        _sell(NEW, "79", "200"),
        _out("79", row_id=1), _in("79", row_id=2),
        _revert(OperationType.CONVERSION_OUT, NEW, "79", reverts=7, row_id=3),
        _revert(OperationType.CONVERSION_IN, OLD, "79", reverts=7, row_id=4),
    ])

    assert result.realized == []
    assert result.positions[OLD].quantity == Decimal("79")
    assert [(lot.quantity_left, lot.price) for lot in result.positions[NEW].lots] == [
        (Decimal("-79"), Decimal("200"))
    ]


def test_reverting_a_decision_without_a_trace_is_an_error():
    """Отменять нечего: записей отменяемого решения в журнале нет."""
    with pytest.raises(ReversalError, match="не нашла его следа"):
        fold([
            _buy(OLD, "79", "120", day=1),
            _revert(OperationType.CONVERSION_OUT, OLD, "79", reverts=7, row_id=1),
        ])


def test_conversion_into_an_existing_position_keeps_fifo_order():
    """Целевая бумага уже лежит в портфеле — перенесённая партия старше её.

    Движок повсюду считает `open_lots[0]` самой старой партией: на этом стоит
    и закрытие встречных партий, и `RealizedSale.opened_at`. Если положить
    перенесённую партию в хвост, продажа закроет не ту: себестоимость окажется
    завышенной, а трёхлетняя льгота по бумаге 2021 года не будет видна вовсе.
    """
    result = fold([
        LedgerEntry(op_type=OperationType.BUY,
                    executed_at=datetime(2021, 1, 10, tzinfo=timezone.utc),
                    instrument_id=OLD, quantity=Decimal("10"),
                    price=Decimal("100"), amount=Decimal("0"), fee=Decimal("0")),
        LedgerEntry(op_type=OperationType.BUY,
                    executed_at=datetime(2025, 2, 5, tzinfo=timezone.utc),
                    instrument_id=NEW, quantity=Decimal("10"),
                    price=Decimal("500"), amount=Decimal("0"), fee=Decimal("0")),
        _out("10"), _in("10"),
        LedgerEntry(op_type=OperationType.SELL,
                    executed_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
                    instrument_id=NEW, quantity=Decimal("10"),
                    price=Decimal("600"), amount=Decimal("0"), fee=Decimal("0")),
    ])

    assert len(result.realized) == 1
    sale = result.realized[0]
    # Закрылась партия 2021 года, пришедшая конвертацией, а не покупка 2025-го.
    assert sale.opened_at == datetime(2021, 1, 10, tzinfo=timezone.utc)
    assert sale.cost == Decimal("1000")
    assert sale.proceeds == Decimal("6000")
    # В книге осталась покупка 2025 года целиком.
    left = result.positions[NEW].lots
    assert [(lot.opened_at.year, lot.quantity_left) for lot in left] == [
        (2025, Decimal("10"))
    ]


def test_conversion_keeps_the_order_of_transferred_lots_on_equal_dates():
    """Партии с равными датами не перескакивают друг через друга.

    Перенесённые партии сохраняют свой порядок между собой, а уже лежавшая в
    книге партия той же даты остаётся впереди: она попала в книгу раньше.
    """
    same_day = datetime(2024, 5, 1, tzinfo=timezone.utc)
    result = fold([
        LedgerEntry(op_type=OperationType.BUY, executed_at=same_day,
                    instrument_id=NEW, quantity=Decimal("1"), price=Decimal("7"),
                    amount=Decimal("0"), fee=Decimal("0")),
        LedgerEntry(op_type=OperationType.BUY, executed_at=same_day,
                    instrument_id=OLD, quantity=Decimal("1"), price=Decimal("11"),
                    amount=Decimal("0"), fee=Decimal("0")),
        LedgerEntry(op_type=OperationType.BUY, executed_at=same_day,
                    instrument_id=OLD, quantity=Decimal("1"), price=Decimal("13"),
                    amount=Decimal("0"), fee=Decimal("0")),
        _out("2"), _in("2"),
    ])

    assert [lot.price for lot in result.positions[NEW].lots] == [
        Decimal("7"), Decimal("11"), Decimal("13")
    ]


def test_conversion_without_link_id_is_an_error():
    """Без link_id связать стороны нечем: карман достался бы чужому решению."""
    orphan = LedgerEntry(
        op_type=OperationType.CONVERSION_OUT, executed_at=WHEN,
        instrument_id=OLD, quantity=Decimal("10"), price=Decimal("0"),
        amount=Decimal("0"), fee=Decimal("0"),
    )

    with pytest.raises(ConversionError, match="нет link_id"):
        fold([_buy(OLD, "10", "100", day=1), orphan])


def test_conversion_out_without_in_does_not_lose_the_shares():
    """Карман, оставшийся невостребованным, — это пропавшие бумаги.

    Промолчать значит вычесть бумаги из старой позиции и не добавить ни в
    какую другую: портфель молча похудеет на всю конвертированную бумагу.
    """
    with pytest.raises(ConversionError, match="невостребованными"):
        fold([_buy(OLD, "10", "100", day=1), _out("10")])


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
