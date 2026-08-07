from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models import OperationType
from app.money import money, quantity as q

INCREASING = {OperationType.BUY}
DECREASING = {OperationType.SELL, OperationType.REDEMPTION}


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
    instrument_id: int
    opened_at: datetime
    price: Decimal
    quantity_left: Decimal


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


@dataclass(frozen=True)
class FoldResult:
    positions: dict[int, PositionState]
    realized: list[RealizedSale]
    cash: dict[str, Decimal]


def _average(lots: list[OpenLot]) -> Decimal:
    total_qty = sum((lot.quantity_left for lot in lots), Decimal("0"))
    if total_qty == 0:
        return money("0")
    total_cost = sum((lot.quantity_left * lot.price for lot in lots), Decimal("0"))
    return money(total_cost / total_qty)


def fold(entries: list[LedgerEntry], currency: str = "RUB") -> FoldResult:
    lots: dict[int, list[OpenLot]] = defaultdict(list)
    realized: list[RealizedSale] = []
    cash: dict[str, Decimal] = defaultdict(lambda: money("0"))

    for entry in sorted(entries, key=lambda e: e.executed_at):
        cash[currency] = money(cash[currency] + entry.amount - entry.fee)

        if entry.instrument_id is None:
            continue

        if entry.op_type in INCREASING:
            lots[entry.instrument_id].append(
                OpenLot(
                    instrument_id=entry.instrument_id,
                    opened_at=entry.executed_at,
                    price=money(entry.price),
                    quantity_left=q(entry.quantity),
                )
            )
        elif entry.op_type in DECREASING:
            remaining = q(entry.quantity)
            unit_proceeds = money(entry.price)
            open_lots = lots[entry.instrument_id]

            while remaining > 0 and open_lots:
                lot = open_lots[0]
                taken = min(lot.quantity_left, remaining)
                realized.append(
                    RealizedSale(
                        instrument_id=entry.instrument_id,
                        sold_at=entry.executed_at,
                        quantity=taken,
                        proceeds=money(taken * unit_proceeds),
                        cost=money(taken * lot.price),
                        opened_at=lot.opened_at,
                    )
                )
                lot.quantity_left = q(lot.quantity_left - taken)
                remaining = q(remaining - taken)
                if lot.quantity_left == 0:
                    open_lots.pop(0)

    positions = {
        instrument_id: PositionState(
            instrument_id=instrument_id,
            quantity=q(sum((lot.quantity_left for lot in open_lots), Decimal("0"))),
            average_price=_average(open_lots),
            lots=open_lots,
        )
        for instrument_id, open_lots in lots.items()
    }
    return FoldResult(positions=positions, realized=realized, cash=dict(cash))
