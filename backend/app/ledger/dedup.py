import hashlib
from decimal import Decimal
from datetime import timezone

from app.ledger.schemas import RawOperation


def _norm(value: Decimal) -> str:
    normalized = value.normalize()
    # Нормализуем знак нуля: -0 и +0 оба должны быть "0"
    if normalized == 0:
        return "0"
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
