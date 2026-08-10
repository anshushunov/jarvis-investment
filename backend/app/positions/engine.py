from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models import OperationType
from app.money import money, quantity as q

INCREASING = {OperationType.BUY, OperationType.TRANSFER_IN}
DECREASING = {OperationType.SELL, OperationType.REDEMPTION, OperationType.TRANSFER_OUT}

# Операции, которые двигают количество, но не создают закрытой сделки: перевод
# бумаги наружу — не продажа, выручки у него нет. Считать его продажей значило
# бы выдумать финансовый результат и испортить налоговую базу.
WITHOUT_REALIZED = {OperationType.TRANSFER_OUT}

# Операции, приносящие количество без себестоимости: брокер её при переводе не
# сообщает, а выдумывать нельзя.
WITHOUT_COST = {OperationType.TRANSFER_IN}


@dataclass(frozen=True)
class LedgerEntry:
    op_type: OperationType
    executed_at: datetime
    instrument_id: int | None
    quantity: Decimal
    price: Decimal
    amount: Decimal
    fee: Decimal


@dataclass
class OpenLot:
    """Открытая партия. `quantity_left` знаковое: положительное — длинная
    позиция (куплено и ещё не продано), отрицательное — короткая (продано без
    остатка и ещё не выкуплено). `price` — цена, по которой партию открыли:
    для длинной это цена покупки, для короткой — цена продажи."""

    instrument_id: int
    opened_at: datetime
    price: Decimal
    quantity_left: Decimal
    # Известна ли себестоимость партии. Ложь у партии, пришедшей переводом:
    # цена там ноль не потому, что бумага досталась даром, а потому, что
    # брокер себестоимости не прислал.
    cost_known: bool = True


@dataclass(frozen=True)
class RealizedSale:
    instrument_id: int
    sold_at: datetime
    quantity: Decimal
    proceeds: Decimal
    cost: Decimal
    opened_at: datetime


@dataclass
class PositionState:
    instrument_id: int
    quantity: Decimal
    average_price: Decimal
    lots: list[OpenLot] = field(default_factory=list)
    # Истина, когда себестоимость известна по всем партиям. Ложь — средняя цена
    # и доходность по позиции не показываются вовсе: усреднение с нулём даёт
    # правдоподобное, но неверное число, которое владелец примет за настоящее.
    cost_basis_known: bool = True


@dataclass(frozen=True)
class FoldResult:
    positions: dict[int, PositionState]
    realized: list[RealizedSale]
    cash: dict[str, Decimal]


def _sign(value: Decimal) -> int:
    return (value > 0) - (value < 0)


def _average(lots: list[OpenLot]) -> Decimal:
    """Средняя цена открытых партий. По модулю количества: у короткой позиции
    партии отрицательные, а средняя цена — величина положительная (цена, по
    которой позицию открыли). Разнонаправленных партий в одной книге не
    бывает — встречная операция сначала закрывает противоположные (см. fold)."""
    total_qty = sum((abs(lot.quantity_left) for lot in lots), Decimal("0"))
    if total_qty == 0:
        return money("0")
    total_cost = sum((abs(lot.quantity_left) * lot.price for lot in lots), Decimal("0"))
    return money(total_cost / total_qty)


def _close_whole_position(
    lots: dict[int, list[OpenLot]],
    touched: set[int],
    realized: list[RealizedSale],
    entry: LedgerEntry,
) -> None:
    """Погашение облигации без количества закрывает выпуск целиком.

    Брокер по полному погашению присылает сумму выплаты, но не количество
    (quantity=0 — проверено на живом ответе T-Invest API), а номинала домен не
    знает. Опереться можно на смысл самой операции: выпуск погашен, держать
    больше нечего. Без этого погашенные бумаги остаются в портфеле навсегда —
    так на живом счёте висели ОФЗ 25083 и РУСАЛ БО-001Р-06.

    Выплата распределяется по открытым партиям пропорционально количеству:
    себестоимость у каждой своя, а общая выручка известна только целиком."""
    open_lots = lots.get(entry.instrument_id)
    if not open_lots:
        return

    total = q(sum((lot.quantity_left for lot in open_lots), Decimal("0")))
    if total <= 0:
        # Короткая позиция на момент погашения — случай, которого в живых
        # данных нет и смысл которого неочевиден; молча ничего не делаем,
        # чтобы не выдумать движение количества.
        return

    for lot in open_lots:
        realized.append(
            RealizedSale(
                instrument_id=entry.instrument_id,
                sold_at=entry.executed_at,
                quantity=lot.quantity_left,
                proceeds=money(entry.amount * lot.quantity_left / total),
                cost=money(lot.quantity_left * lot.price),
                opened_at=lot.opened_at,
            )
        )
    lots[entry.instrument_id] = []
    touched.add(entry.instrument_id)


def fold(entries: list[LedgerEntry], currency: str = "RUB") -> FoldResult:
    """Сворачивает журнал в позиции и закрытые сделки по FIFO.

    Операции обрабатываются в хронологическом порядке; при совпадающей метке
    времени покупка идёт раньше продажи, чтобы внутри одного мгновения не
    возникало мнимого разворота позиции.

    Позиция знаковая: положительная — длинная, отрицательная — короткая.
    Раньше движок не давал остатку уйти в минус и молча отбрасывал излишек
    продажи. Это не безобидная защита: продажа без остатка — обычная короткая
    сделка (на живом счёте владельца 13.11.2020 продано 10000 АФК «Система»
    при нулевом остатке), и закрывающая её покупка оседала в портфеле
    бумагой, которой у владельца нет. Так набралось 14 фантомных позиций,
    каждая ровно в размер шорта — SBER, TSLA, DSKY и другие.

    Встречная операция сначала закрывает противоположные партии по FIFO и
    только остатком открывает новые, поэтому в книге одного инструмента
    никогда не лежат разнонаправленные партии.

    Суммы знаковые с точки зрения счёта: покупки отрицательные, продажи и
    дивиденды положительные. Комиссия вычитается отдельно и в amount не входит.
    """
    lots: dict[int, list[OpenLot]] = {}
    touched: set[int] = set()  # инструменты, по которым вообще двигалось количество
    realized: list[RealizedSale] = []
    cash: dict[str, Decimal] = defaultdict(lambda: money("0"))

    # Sort by timestamp, then by operation type (INCREASING before DECREASING)
    def sort_key(entry):
        # Lower value for INCREASING (processed first), higher for others
        priority = 0 if entry.op_type in INCREASING else 1
        return (entry.executed_at, priority)

    for entry in sorted(entries, key=sort_key):
        cash[currency] = money(cash[currency] + entry.amount - entry.fee)

        if entry.instrument_id is None:
            continue

        if entry.op_type in INCREASING:
            direction = 1
        elif entry.op_type in DECREASING:
            direction = -1
        else:
            continue

        if entry.quantity == 0:
            if entry.op_type is OperationType.REDEMPTION:
                _close_whole_position(lots, touched, realized, entry)
            continue

        open_lots = lots.setdefault(entry.instrument_id, [])
        touched.add(entry.instrument_id)

        remaining = q(entry.quantity)
        unit_price = money(entry.price)

        # Сначала гасим встречные партии: продажа закрывает длинные, покупка
        # выкупает короткие. Условие — знак партии противоположен направлению
        # операции.
        while remaining > 0 and open_lots and _sign(open_lots[0].quantity_left) == -direction:
            lot = open_lots[0]
            taken = min(abs(lot.quantity_left), remaining)
            # У длинной позиции выручка — цена продажи, себестоимость — цена
            # покупки. У короткой ровно наоборот: заработок в том, что выкупили
            # дешевле, чем продали, поэтому выручка берётся из цены открытия
            # партии, а себестоимость — из цены текущего выкупа.
            if direction < 0:
                proceeds, cost = unit_price, lot.price
            else:
                proceeds, cost = lot.price, unit_price
            if entry.op_type not in WITHOUT_REALIZED:
                realized.append(
                    RealizedSale(
                        instrument_id=entry.instrument_id,
                        sold_at=entry.executed_at,
                        quantity=taken,
                        proceeds=money(taken * proceeds),
                        cost=money(taken * cost),
                        opened_at=lot.opened_at,
                    )
                )
            lot.quantity_left = q(lot.quantity_left + direction * taken)
            remaining = q(remaining - taken)
            if lot.quantity_left == 0:
                open_lots.pop(0)

        # Что не пошло на закрытие встречных партий — открывает новую в
        # направлении самой операции.
        if remaining > 0:
            open_lots.append(
                OpenLot(
                    instrument_id=entry.instrument_id,
                    opened_at=entry.executed_at,
                    price=unit_price,
                    quantity_left=q(direction * remaining),
                    cost_known=entry.op_type not in WITHOUT_COST,
                )
            )

    positions = {}
    for instrument_id in touched:
        open_lots = lots.get(instrument_id, [])
        positions[instrument_id] = PositionState(
            instrument_id=instrument_id,
            quantity=q(sum((lot.quantity_left for lot in open_lots), Decimal("0"))),
            average_price=_average(open_lots),
            lots=open_lots,
            cost_basis_known=all(lot.cost_known for lot in open_lots),
        )
    return FoldResult(positions=positions, realized=realized, cash=dict(cash))
