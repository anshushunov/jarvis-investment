import hashlib
from decimal import Decimal
from datetime import timezone

from app.ledger.schemas import RawOperation


def _norm(value: Decimal) -> str:
    normalized = value.normalize()
    return f"{normalized:f}"


def natural_key(source: str, account_external_id: str, op: RawOperation) -> str:
    parts = [
        source,
        account_external_id,
        op.op_type.value,
        op.executed_at.astimezone(timezone.utc).isoformat(),
        op.isin or "",
        _norm(op.quantity),
        _norm(op.price),
        _norm(op.amount),
        op.currency,
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()
