from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db_errors import is_unique_violation
from app.instruments import kinds
from app.ledger.schemas import RawOperation
from app.models import Instrument

# Уникальный индекс на Instrument.isin (Instrument.isin = mapped_column(..., unique=True)).
# Имя определено автогенерацией Alembic в 0001_initial.py: op.f('ix_instrument_isin').
_ISIN_UNIQUE_INDEX = "ix_instrument_isin"


def resolve_instrument(session: Session, op: RawOperation) -> Instrument | None:
    if op.isin is None:
        return None

    existing = session.execute(
        select(Instrument).where(Instrument.isin == op.isin)
    ).scalar_one_or_none()
    if existing is not None:
        # Уже известный инструмент не просто возвращается как есть: справочные
        # сведения (вид, название) обновляются из свежего ответа брокера.
        # Раньше запись создавалась один раз и больше не менялась никогда —
        # инструменты, заведённые до того, как вид начал доезжать через
        # границу коннектора, так и остались бы поголовно акциями. Таблица
        # инструментов не append-only: append-only только журнал операций.
        apply_reference(existing, *_reference_from(op))
        return existing

    return _insert_instrument(session, op)


def apply_reference(instrument: Instrument, kind: str | None, name: str | None) -> bool:
    """Дозаполняет справочные сведения инструмента. Возвращает True, если
    что-то реально изменилось.

    Справочник брокера здесь — источник истины: вид перезаписывается, а не
    только заполняется на пустом месте. Иначе 149 уже записанных инструментов
    навсегда останутся акциями — «пусто» в колонке `kind` не бывает, там лежит
    неверное значение, а не NULL. Неизвестный вид (kinds.OTHER) при этом
    ничего не затирает: поштучный запасной путь справочника может не знать
    экзотический инструмент, и терять из-за этого уже установленный вид
    незачем."""
    changed = False

    if kind and kind != kinds.OTHER and instrument.kind != kind:
        instrument.kind = kind
        changed = True

    if name and instrument.issuer != name:
        instrument.issuer = name
        changed = True

    return changed


def _reference_from(op: RawOperation) -> tuple[str | None, str | None]:
    """Справочные сведения, положенные коннектором в payload операции (см.
    app/connectors/tbank/mapper.py). Ключей может не быть вовсе — например, у
    операции, записанной в журнал до того, как коннектор научился их класть."""
    kind = op.payload.get("instrument_kind")
    name = op.payload.get("instrument_name")
    return (str(kind) if kind else None, str(name) if name else None)


def _insert_instrument(session: Session, op: RawOperation) -> Instrument:
    """Вставляет новый инструмент по ISIN операции `op`.

    Отделена от `resolve_instrument`, чтобы обе части гонки были явными: вызов этой
    функции напрямую (в обход предварительного select в `resolve_instrument`) — это
    именно то, что происходит при двух параллельных пачках, впервые увидевших один и
    тот же ISIN одновременно. Побеждает вставка, успевшая раньше; проигравшая ловит
    нарушение уникального индекса и переиспользует уже вставленную запись — без
    падения всей пачки операций.
    """
    kind, name = _reference_from(op)
    instrument = Instrument(
        isin=op.isin,
        ticker=op.ticker,
        secid=op.ticker,
        # Вида нет только если справочник брокера сам его не дал — записываем
        # честное "неизвестно", а не подразумеваемую акцию.
        kind=kind or kinds.OTHER,
        currency=op.currency,
        issuer=name,
    )
    try:
        with session.begin_nested():
            session.add(instrument)
            session.flush()
    except IntegrityError as exc:
        if not is_unique_violation(exc, _ISIN_UNIQUE_INDEX):
            raise
        # SQLAlchemy сам изгоняет instrument из сессии при откате SAVEPOINT — повторный
        # explicit expunge здесь лишний и падает с InvalidRequestError.
        winner = session.execute(
            select(Instrument).where(Instrument.isin == op.isin)
        ).scalar_one()
        apply_reference(winner, kind, name)
        return winner
    return instrument
