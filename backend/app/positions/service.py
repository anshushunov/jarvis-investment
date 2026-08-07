from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Account, Position, Transaction
from app.positions.engine import LedgerEntry, fold


def _entries(session: Session, account: Account) -> list[LedgerEntry]:
    transactions = session.execute(
        select(Transaction).where(Transaction.account_id == account.id)
    ).scalars().all()
    return [
        LedgerEntry(
            op_type=tx.op_type,
            executed_at=tx.executed_at,
            instrument_id=tx.instrument_id,
            quantity=tx.quantity,
            price=tx.price,
            amount=tx.amount,
            fee=tx.fee,
        )
        for tx in transactions
    ]


def rebuild_positions(session: Session, account: Account) -> int:
    result = fold(_entries(session, account), currency=account.currency)

    session.execute(delete(Position).where(Position.account_id == account.id))

    kept = 0
    for instrument_id, state in result.positions.items():
        if state.quantity == 0:
            continue
        session.add(
            Position(
                account_id=account.id,
                instrument_id=instrument_id,
                quantity=state.quantity,
                average_price=state.average_price,
            )
        )
        kept += 1

    session.flush()
    return kept
