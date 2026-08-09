from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPosition
from app.models import Account, BrokerHolding, Instrument


def store_holdings(session: Session, account: Account, positions: list[BrokerPosition]) -> int:
    """Заменяет снимок бумаг счёта присланным брокером.

    Замена, а не дополнение: снимок описывает состояние на момент времени, и
    бумага, которой у брокера больше нет, обязана исчезнуть.
    """
    session.execute(delete(BrokerHolding).where(BrokerHolding.account_id == account.id))

    if not positions:
        session.flush()
        return 0

    # Разные FIGI брокера иногда разрешаются в один и тот же ISIN — та же
    # бумага на другой площадке или в другом режиме торгов (живой случай,
    # уронивший прогон: две записи с (account_id, isin) = (1, RU0009029540)).
    # Уникальный ключ таблицы не переживёт две отдельные вставки на одну и ту
    # же пару, поэтому такие позиции сводятся в одну строку до вставки.
    # Количества складываются, а не «последняя запись побеждает», как в
    # reconcile_account: там сверка сравнивает итоговое число с журналом и
    # результат в базу под уникальным ключом не уходит, а здесь это две
    # реальные порции одной и той же бумаги на одном счёте, и общий объём —
    # их сумма; отбросить одну из них значило бы молча потерять часть бумаги
    # и её блокировки.
    merged: dict[str, BrokerPosition] = {}
    for item in positions:
        existing = merged.get(item.isin)
        if existing is None:
            merged[item.isin] = item
        else:
            merged[item.isin] = BrokerPosition(
                isin=item.isin,
                ticker=existing.ticker or item.ticker,
                quantity=existing.quantity + item.quantity,
                blocked=existing.blocked + item.blocked,
            )

    instrument_ids = {
        isin: instrument_id
        for instrument_id, isin in session.execute(
            select(Instrument.id, Instrument.isin).where(
                Instrument.isin.in_(merged.keys())
            )
        ).all()
    }

    for item in merged.values():
        session.add(BrokerHolding(
            account_id=account.id,
            instrument_id=instrument_ids.get(item.isin),
            isin=item.isin,
            quantity=item.quantity,
            blocked=item.blocked,
        ))

    session.flush()
    return len(merged)


def blocked_by_instrument(session: Session) -> dict[tuple[int, int], Decimal]:
    """Заблокированные количества по парам «счёт, инструмент».

    Строки без связи с инструментом и с нулевой блокировкой пропускаются: у
    первых нечего показывать в таблице позиций, вторые ничего не сообщают.
    """
    rows = session.execute(
        select(BrokerHolding.account_id, BrokerHolding.instrument_id, BrokerHolding.blocked)
        .where(BrokerHolding.instrument_id.is_not(None), BrokerHolding.blocked != 0)
    ).all()
    return {(account_id, instrument_id): blocked
            for account_id, instrument_id, blocked in rows}
