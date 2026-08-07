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
# UniqueConstraint("account_id", "source", "external_id", name="uq_transaction_source_external")
# там же. Тот же внешний идентификатор брокера на этом же счёте, но с иным dedup_key —
# например, брокер повторно отдал операцию с чуть изменившимся содержанием при
# пересекающемся окне повторной синхронизации (см. SYNC_OVERLAP_DAYS в app/sync/service.py).
# По смыслу задачи это тоже «уже записано», а не ошибка — живое подтверждение и разбор
# в fix-ledger-unique-report.md.
_SOURCE_EXTERNAL_UNIQUE_CONSTRAINT = "uq_transaction_source_external"


def _is_duplicate_conflict(exc: IntegrityError) -> bool:
    """True, если exc — конфликт по одному из двух уникальных ограничений журнала,
    которые по смыслу задачи означают «дубль, пропустить», а не ошибку. Любой другой
    IntegrityError (внешний ключ, NOT NULL) — ошибка вызывающего кода и обязан
    всплыть наружу, а не быть проглоченным."""
    return is_unique_violation(exc, _DEDUP_KEY_UNIQUE_CONSTRAINT) or is_unique_violation(
        exc, _SOURCE_EXTERNAL_UNIQUE_CONSTRAINT
    )


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
    дубль — конфликт по dedup_key (гонка с параллельным вызовом append_operations по
    тому же счёту) или по (account_id, source, external_id) (тот же внешний
    идентификатор брокера уже записан для этого счёта, см. _is_duplicate_conflict) —
    обнаруженный только на вставке. Это медленный, но безопасный путь на единичную
    строку — append_operations прибегает к нему только тогда, когда быстрый пакетный
    flush всего батча уже столкнулся с конфликтом (см. append_operations)."""
    instrument = resolve_instrument(session, op)
    transaction = _build_transaction(account, source, op, key, instrument.id if instrument else None)
    try:
        with session.begin_nested():
            session.add(transaction)
            session.flush()
    except IntegrityError as exc:
        if not _is_duplicate_conflict(exc):
            raise
        # SQLAlchemy сам изгоняет transaction из сессии при откате SAVEPOINT — повторный
        # explicit expunge здесь лишний и падает с InvalidRequestError.
        return False
    return True


def _load_known_keys(session: Session, keys: list[str]) -> set[str]:
    """Читает уже занятые dedup_key из БД. Вынесена в отдельную функцию модуля, а не
    инлайн в append_operations, только ради тестируемости: тесты подменяют её через
    monkeypatch, чтобы вернуть пустое множество и тем самым честно воспроизвести
    fallback-ветку append_operations на настоящем PostgreSQL (см.
    test_append_operations_falls_back_to_row_by_row_on_bulk_conflict) — сама вставка,
    конфликт уникальности и откат при этом остаются настоящими, подменяется только
    чтение известных ключей."""
    return set(
        session.execute(
            select(Transaction.dedup_key).where(Transaction.dedup_key.in_(keys))
        ).scalars()
    )


def append_operations(
    session: Session, account: Account, source: str, operations: list[RawOperation]
) -> AppendResult:
    if not operations:
        return AppendResult(inserted=0, skipped=0)

    # RawOperation несёт поле payload: dict, поэтому сам объект не hashable —
    # держим ключи в списке, параллельном operations, а не в словаре с op как ключом.
    keys = [natural_key(source, account.external_id, op) for op in operations]
    known = _load_known_keys(session, keys)

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
    # через insertmanyvalues). Замер на 5000 операциях (3 прогона) показал SAVEPOINT на
    # каждую строку медленнее одного flush на батч на 63-95% — методика и полные цифры
    # в task-5-report.md, раунд 2. При первой полной синхронизации истории счёта (тысячи
    # операций, синхронный вызов из POST /api/sync/tbank) это ощутимо, поэтому конфликт
    # по любому из двух уникальных ограничений журнала обрабатывается не построчным
    # SAVEPOINT сразу, а как редкое исключение из быстрого пути.
    transactions = []
    for op, key in to_insert:
        instrument = resolve_instrument(session, op)
        transactions.append(_build_transaction(account, source, op, key, instrument.id if instrument else None))

    try:
        with session.begin_nested():
            session.add_all(transactions)
            session.flush()
    except IntegrityError as exc:
        if not _is_duplicate_conflict(exc):
            raise
        # Гонка/дубль: либо кто-то другой вставил такой же dedup_key между нашим SELECT
        # known и этим flush, либо в батче нашлась операция с уже занятым на этом счёте
        # (account_id, source, external_id), но другим содержанием (см.
        # _is_duplicate_conflict и fix-ledger-unique-report.md). SQLAlchemy откатил
        # SAVEPOINT и изгнал весь transactions из сессии. Медленный, но надёжный путь —
        # вставить по одной операции под своим SAVEPOINT, чтобы отделить реально
        # столкнувшуюся строку (или несколько) от легитимных новых.
        inserted = 0
        conflict_skipped = 0
        for op, key in to_insert:
            if _insert_one(session, account, source, op, key):
                inserted += 1
            else:
                conflict_skipped += 1
        session.flush()
        return AppendResult(inserted=inserted, skipped=skipped + conflict_skipped)

    # Второй flush() здесь не нужен: он уже случился внутри блока with session.begin_nested()
    # выше — к этому моменту нечего сбрасывать, добавление было бы чистым no-op.
    return AppendResult(inserted=len(transactions), skipped=skipped)
