from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_errors import is_unique_violation
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


def _build_transaction(
    account: Account, source: str, op: RawOperation, key: str, instrument_id: int | None
) -> Transaction:
    return Transaction(
        account_id=account.id,
        instrument_id=instrument_id,
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


def _insert_one(session: Session, account: Account, source: str, op: RawOperation, key: str) -> bool:
    """Вставляет одну операцию под собственным SAVEPOINT. Возвращает False, если это
    дубль по dedup_key, обнаруженный только на вставке — гонка с параллельным вызовом
    append_operations по тому же счёту (плановая синхронизация и ручная синхронизация
    через API могут пересечься по времени). Это медленный, но безопасный путь на
    единичную строку — append_operations прибегает к нему только тогда, когда быстрый
    пакетный flush всего батча уже столкнулся с конфликтом (см. append_operations)."""
    instrument = resolve_instrument(session, op)
    transaction = _build_transaction(account, source, op, key, instrument.id if instrument else None)
    try:
        with session.begin_nested():
            session.add(transaction)
            session.flush()
    except IntegrityError as exc:
        if not is_unique_violation(exc, _DEDUP_KEY_UNIQUE_CONSTRAINT):
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

    to_insert: list[tuple[RawOperation, str]] = []
    skipped = 0
    seen_in_batch: set[str] = set()

    for op, key in zip(operations, keys):
        if key in known or key in seen_in_batch:
            skipped += 1
            continue
        seen_in_batch.add(key)
        to_insert.append((op, key))

    if not to_insert:
        return AppendResult(inserted=0, skipped=skipped)

    # Быстрый путь: один общий flush на весь батч (SQLAlchemy сам батчирует вставку
    # через insertmanyvalues). Замер на 5000 операциях показал, что SAVEPOINT на каждую
    # строку даёт +46% времени против одного flush на батч (task-5-report.md, раунд 2) —
    # при первой полной синхронизации истории счёта (тысячи операций, синхронный вызов
    # из POST /api/sync/tbank) это ощутимо, поэтому конфликт по dedup_key обрабатывается
    # не построчным SAVEPOINT сразу, а как редкое исключение из быстрого пути.
    transactions = []
    for op, key in to_insert:
        instrument = resolve_instrument(session, op)
        transactions.append(_build_transaction(account, source, op, key, instrument.id if instrument else None))

    try:
        with session.begin_nested():
            session.add_all(transactions)
            session.flush()
    except IntegrityError as exc:
        if not is_unique_violation(exc, _DEDUP_KEY_UNIQUE_CONSTRAINT):
            raise
        # Гонка: кто-то другой вставил дубль между нашим SELECT known и этим flush.
        # SQLAlchemy откатил SAVEPOINT и изгнал весь transactions из сессии. Медленный,
        # но надёжный путь — вставить по одной операции под своим SAVEPOINT, чтобы
        # отделить реально столкнувшуюся строку (или несколько) от легитимных новых.
        inserted = 0
        conflict_skipped = 0
        for op, key in to_insert:
            if _insert_one(session, account, source, op, key):
                inserted += 1
            else:
                conflict_skipped += 1
        session.flush()
        return AppendResult(inserted=inserted, skipped=skipped + conflict_skipped)

    session.flush()
    return AppendResult(inserted=len(transactions), skipped=skipped)
