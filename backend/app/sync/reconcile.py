from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPosition
from app.models import Account, Instrument, Position, Reconciliation

TOLERANCE = Decimal("0.000001")


def reconcile_account(
    session: Session, account: Account, broker_positions: list[BrokerPosition]
) -> list[Reconciliation]:
    session.execute(delete(Reconciliation).where(Reconciliation.account_id == account.id))

    rows = session.execute(
        select(Position, Instrument)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .where(Position.account_id == account.id)
    ).all()

    ledger: dict[str, tuple[Position, Instrument]] = {
        instrument.isin: (position, instrument)
        for position, instrument in rows
        if instrument.isin
    }
    broker: dict[str, BrokerPosition] = {item.isin: item for item in broker_positions}

    findings: list[Reconciliation] = []

    for isin in sorted(ledger.keys() | broker.keys()):
        position_pair = ledger.get(isin)
        broker_position = broker.get(isin)

        ledger_qty = position_pair[0].quantity if position_pair else Decimal("0")
        broker_qty = broker_position.quantity if broker_position else Decimal("0")

        if abs(ledger_qty - broker_qty) <= TOLERANCE:
            continue

        if position_pair is None:
            status = "missing_in_ledger"
        elif broker_position is None:
            status = "missing_at_broker"
        else:
            status = "quantity_mismatch"

        finding = Reconciliation(
            account_id=account.id,
            instrument_id=position_pair[1].id if position_pair else None,
            isin=isin,
            ledger_quantity=ledger_qty,
            broker_quantity=broker_qty,
            status=status,
        )
        session.add(finding)
        findings.append(finding)

    session.flush()
    return findings
