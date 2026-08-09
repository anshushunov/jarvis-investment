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

    instrument_ids = {
        isin: instrument_id
        for instrument_id, isin in session.execute(
            select(Instrument.id, Instrument.isin).where(
                Instrument.isin.in_({item.isin for item in positions})
            )
        ).all()
    }

    for item in positions:
        session.add(BrokerHolding(
            account_id=account.id,
            instrument_id=instrument_ids.get(item.isin),
            isin=item.isin,
            quantity=item.quantity,
            blocked=item.blocked,
        ))

    session.flush()
    return len(positions)


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
