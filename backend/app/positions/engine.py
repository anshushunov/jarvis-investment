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
    """Fold a ledger of transactions into positions and realized sales using FIFO accounting.

    Processes transactions in chronological order. When timestamps match, buy (INCREASING)
    operations are processed before sells (DECREASING) to prevent accounting reversals within
    a single timestamp.

    Amounts are signed from the account perspective: purchases negative, sales and dividends
    positive. Fees are deducted separately and not included in amount.
    """
    lots: dict[int, list[OpenLot]] = {}
    bought_instruments: set[int] = set()  # Track instruments that were ever bought
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
            # Don't create a lot if quantity is zero
            if entry.quantity == 0:
                continue

            if entry.instrument_id not in lots:
                lots[entry.instrument_id] = []

            bought_instruments.add(entry.instrument_id)
            lots[entry.instrument_id].append(
                OpenLot(
                    instrument_id=entry.instrument_id,
                    opened_at=entry.executed_at,
                    price=money(entry.price),
                    quantity_left=q(entry.quantity),
                )
            )
        elif entry.op_type in DECREASING:
            # Only process if we have lots for this instrument
            if entry.instrument_id not in lots:
                continue

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
            quantity=q(sum((lot.quantity_left for lot in lots.get(instrument_id, [])), Decimal("0"))),
            average_price=_average(lots.get(instrument_id, [])),
            lots=lots.get(instrument_id, []),
        )
        for instrument_id in bought_instruments
    }
    return FoldResult(positions=positions, realized=realized, cash=dict(cash))
