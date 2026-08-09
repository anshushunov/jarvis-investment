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


def apply_reference(
    instrument: Instrument,
    kind: str | None,
    name: str | None,
    currency: str | None = None,
    restricted: bool | None = None,
) -> bool:
    """Дозаполняет справочные сведения инструмента. Возвращает True, если
    что-то реально изменилось.

    Справочник брокера здесь — источник истины: вид и валюта перезаписываются,
    а не только заполняются на пустом месте. Иначе уже записанные инструменты
    навсегда останутся с тем, что попало в строку при её создании — «пусто» в
    этих колонках не бывает, там лежит неверное значение, а не NULL.

    Валюта особенно: при создании она берётся из платежа первой встреченной
    операции, а платёж по валютной бумаге вполне может прийти в рублях
    (комиссия, налог, дивиденд) — на живых данных так получилось у шести
    инструментов, чьи сделки шли в USD и HKD. Пока валюта была почти
    декоративной, это было терпимо; теперь она решает, попадёт ли позиция в
    совокупный капитал.

    Отсутствующие справочные сведения ничего не затирают: справочник может не
    знать экзотический инструмент, и терять из-за этого уже установленное
    значение незачем. Для вида то же самое делает и явный kinds.OTHER —
    «вид неизвестен» не должен вытеснять известный.

    Признак ограничения в обороте обновляется в обе стороны, в отличие от
    остальных полей: снятие блокировки — такое же сообщение справочника, как и
    её появление.
    """
    changed = False

    if kind and kind != kinds.OTHER and instrument.kind != kind:
        instrument.kind = kind
        changed = True

    if name and instrument.issuer != name:
        instrument.issuer = name
        changed = True

    if currency and instrument.currency != currency:
        instrument.currency = currency
        changed = True

    # None и False здесь разное: None — «справочник ничего не сказал», и тогда
    # прежнее значение сохраняется; False — «брокер говорит, что операции
    # доступны», и признак обязан сняться. Проверка на истинность, как у
    # остальных полей, склеила бы эти два случая, и разблокированная бумага
    # осталась бы ограниченной навсегда.
    if restricted is not None and instrument.trading_restricted != restricted:
        instrument.trading_restricted = restricted
        changed = True

    return changed


def _reference_from(op: RawOperation) -> tuple[str | None, str | None, str | None, bool | None]:
    """Справочные сведения, положенные коннектором в payload операции (см.
    app/connectors/tbank/mapper.py). Ключей может не быть вовсе — например, у
    операции, записанной в журнал до того, как коннектор научился их класть."""
    kind = op.payload.get("instrument_kind")
    name = op.payload.get("instrument_name")
    currency = op.payload.get("instrument_currency")
    buy = op.payload.get("instrument_buy_available")
    sell = op.payload.get("instrument_sell_available")
    return (
        str(kind) if kind else None,
        str(name) if name else None,
        str(currency).upper() if currency else None,
        _restricted(buy, sell),
    )


def _restricted(buy: object, sell: object) -> bool | None:
    """Ограничена ли бумага в обороте: недоступны обе операции сразу.

    Одного флага мало. Бумага, которую нельзя купить, но можно продать,
    распоряжению поддаётся — именно так выглядят выпуски, закрытые для новых
    покупок, но не замороженные. Ограничением считается только пара.

    Хотя бы один флаг отсутствует — сведений нет, возвращаем None: прежнее
    значение в базе трогать нельзя.
    """
    if not isinstance(buy, bool) or not isinstance(sell, bool):
        return None
    return not buy and not sell


def secid_from_ticker(ticker: str | None) -> str | None:
    """Биржевой идентификатор инструмента из тикера брокера.

    Т-Банк помечает часть фондов тикером с «@» на конце (TMOS@, TLCB@), а на
    MOEX такого идентификатора нет — котировка не находится вовсе, и позиция
    остаётся неоценённой. Проверено на живых данных: TMOS стоит 5.69 ₽ при
    средней цене позиции 6.07, TLCB — 10.83 при 9.92, то есть речь об одной и
    той же бумаге (ISIN совпадает).

    Сам тикер не трогаем: позиция должна называться так же, как в приложении
    брокера. Чинится только идентификатор, с которым мы идём на биржу."""
    if not ticker:
        return None
    return ticker.rstrip("@") or None


def _insert_instrument(session: Session, op: RawOperation) -> Instrument:
    """Вставляет новый инструмент по ISIN операции `op`.

    Отделена от `resolve_instrument`, чтобы обе части гонки были явными: вызов этой
    функции напрямую (в обход предварительного select в `resolve_instrument`) — это
    именно то, что происходит при двух параллельных пачках, впервые увидевших один и
    тот же ISIN одновременно. Побеждает вставка, успевшая раньше; проигравшая ловит
    нарушение уникального индекса и переиспользует уже вставленную запись — без
    падения всей пачки операций.
    """
    kind, name, currency, restricted = _reference_from(op)
    instrument = Instrument(
        isin=op.isin,
        ticker=op.ticker,
        secid=secid_from_ticker(op.ticker),
        # Вида нет только если справочник брокера сам его не дал — записываем
        # честное "неизвестно", а не подразумеваемую акцию.
        kind=kind or kinds.OTHER,
        # Валюта самой бумаги, а валюта платежа (op.currency) — только запасное
        # значение на случай, когда справочник ничего не дал: колонка NOT NULL,
        # а платёж хоть какую-то валюту всегда несёт.
        currency=currency or op.currency,
        issuer=name,
        trading_restricted=bool(restricted),
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
        apply_reference(winner, kind, name, currency, restricted)
        return winner
    return instrument
