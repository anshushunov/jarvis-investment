from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.instruments.service import resolve_instrument
from app.ledger.dedup import natural_key
from app.ledger.schemas import RawOperation
from app.models import Account, Transaction

# UniqueConstraint("dedup_key", name="uq_transaction_dedup_key") в app/models/transaction.py.
_DEDUP_KEY_UNIQUE_CONSTRAINT = "uq_transaction_dedup_key"


@dataclass(frozen=True)
class AppendResult:
    inserted: int
    skipped: int


def _is_unique_violation(exc: IntegrityError, constraint_name: str) -> bool:
    diag = getattr(exc.orig, "diag", None)
    return diag is not None and diag.constraint_name == constraint_name


def _insert_one(session: Session, account: Account, source: str, op: RawOperation, key: str) -> bool:
    """Вставляет одну операцию. Возвращает False, если это дубль по dedup_key,
    обнаруженный только на вставке — гонка с параллельным вызовом append_operations
    по тому же счёту (плановая синхронизация и ручная синхронизация через API могут
    пересечься по времени). В этом случае конфликт — штатный исход дедупликации,
    а не ошибка: одна SAVEPOINT-транзакция откатывается, остальные операции пачки
    не затрагиваются."""
    instrument = resolve_instrument(session, op)
    transaction = Transaction(
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
    try:
        with session.begin_nested():
            session.add(transaction)
            session.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(exc, _DEDUP_KEY_UNIQUE_CONSTRAINT):
            raise
        # SQLAlchemy сам изгоняет transaction из сессии при откате SAVEPOINT — повторный
        # explicit expunge здесь лишний и падает с InvalidRequestError.
        return False
    return True


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

        if _insert_one(session, account, source, op, key):
            inserted += 1
        else:
            skipped += 1

    session.flush()
    return AppendResult(inserted=inserted, skipped=skipped)
