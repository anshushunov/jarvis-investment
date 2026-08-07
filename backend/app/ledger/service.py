from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.instruments.service import resolve_instrument
from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.models import Account, Transaction


@dataclass(frozen=True)
class AppendResult:
    inserted: int
    skipped: int


def append_operations(
    session: Session, account: Account, source: str, operations: list[RawOperation]
) -> AppendResult:
    if not operations:
        return AppendResult(inserted=0, skipped=0)

    # RawOperation несёт поле payload: dict, поэтому сам объект не hashable —
    # держим ключи в списке, параллельном operations, а не в словаре с op как ключом.
    keys = [natural_key(source, account.external_id, op) for op in operations]
    known = set(
        session.execute(
            select(Transaction.dedup_key).where(Transaction.dedup_key.in_(keys))
        ).scalars()
    )

    inserted = 0
    skipped = 0
    seen_in_batch: set[str] = set()

    for op, key in zip(operations, keys):
        if key in known or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)

        instrument = resolve_instrument(session, op)
        session.add(
            Transaction(
                account_id=account.id,
                instrument_id=instrument.id if instrument else None,
                op_type=op.op_type,
                executed_at=op.executed_at,
                quantity=op.quantity,
                price=op.price,
                amount=op.amount,
                currency=op.currency,
                fee=op.fee,
                external_id=op.external_id,
                source=source,
                payload=op.payload,
                dedup_key=key,
            )
        )
        inserted += 1

    session.flush()
    return AppendResult(inserted=inserted, skipped=skipped)
