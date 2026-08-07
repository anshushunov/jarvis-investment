from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ledger.schemas import RawOperation
from app.models import Instrument

KIND_BY_PREFIX = {"share": "share", "bond": "bond", "etf": "etf", "currency": "currency"}

# Уникальный индекс на Instrument.isin (Instrument.isin = mapped_column(..., unique=True)).
# Имя определено автогенерацией Alembic в 0001_initial.py: op.f('ix_instrument_isin').
_ISIN_UNIQUE_INDEX = "ix_instrument_isin"


def _is_unique_violation(exc: IntegrityError, constraint_name: str) -> bool:
    diag = getattr(exc.orig, "diag", None)
    return diag is not None and diag.constraint_name == constraint_name


def resolve_instrument(session: Session, op: RawOperation) -> Instrument | None:
    if op.isin is None:
        return None

    existing = session.execute(
        select(Instrument).where(Instrument.isin == op.isin)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    return _insert_instrument(session, op)


def _insert_instrument(session: Session, op: RawOperation) -> Instrument:
    """Вставляет новый инструмент по ISIN операции `op`.

    Отделена от `resolve_instrument`, чтобы обе части гонки были явными: вызов этой
    функции напрямую (в обход предварительного select в `resolve_instrument`) — это
    именно то, что происходит при двух параллельных пачках, впервые увидевших один и
    тот же ISIN одновременно. Побеждает вставка, успевшая раньше; проигравшая ловит
    нарушение уникального индекса и переиспользует уже вставленную запись — без
    падения всей пачки операций.
    """
    instrument = Instrument(
        isin=op.isin,
        ticker=op.ticker,
        secid=op.ticker,
        kind=str(op.payload.get("instrument_kind", "share")),
        currency=op.currency,
        issuer=op.payload.get("issuer"),
    )
    try:
        with session.begin_nested():
            session.add(instrument)
            session.flush()
    except IntegrityError as exc:
        if not _is_unique_violation(exc, _ISIN_UNIQUE_INDEX):
            raise
        # SQLAlchemy сам изгоняет instrument из сессии при откате SAVEPOINT — повторный
        # explicit expunge здесь лишний и падает с InvalidRequestError.
        return session.execute(
            select(Instrument).where(Instrument.isin == op.isin)
        ).scalar_one()
    return instrument
