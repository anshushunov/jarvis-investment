from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPosition
from app.instruments import kinds
from app.instruments.service import apply_reference, secid_from_ticker
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
    # Количества складываются: это две реальные порции одной и той же бумаги
    # на одном счёте, и общий объём — их сумма; отбросить одну из них значило
    # бы молча потерять часть бумаги и её блокировки. То же правило действует
    # в reconcile_account, чтобы сверка не выдумывала расхождение с журналом
    # на ровном месте.
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
                reference=existing.reference or item.reference,
            )

    instruments = {
        instrument.isin: instrument
        for instrument in session.execute(
            select(Instrument).where(Instrument.isin.in_(merged.keys()))
        ).scalars()
    }

    for item in merged.values():
        instrument = instruments.get(item.isin)
        if instrument is None and item.reference is not None:
            # Бумага есть у брокера, но не в нашем справочнике: она попала на
            # счёт помимо журнала — конвертацией или переводом. Так лежат
            # HK0000051877 и HK0000123577, обе заблокированы целиком, и обе
            # безымянны в расхождениях. Заводим из справочных сведений,
            # разрешённых коннектором по FIGI позиции.
            instrument = Instrument(
                isin=item.isin,
                ticker=item.reference.ticker or item.ticker,
                secid=secid_from_ticker(item.reference.ticker or item.ticker),
                kind=item.reference.kind or kinds.OTHER,
                currency=(item.reference.currency or "RUB").upper(),
                issuer=item.reference.name,
                trading_restricted=bool(_restricted_from(item.reference)),
            )
            session.add(instrument)
            session.flush()
            instruments[item.isin] = instrument
        elif instrument is not None and item.reference is not None:
            # Уже известную бумагу справочник тоже освежает: разблокировка —
            # такое же сообщение брокера, как и блокировка.
            apply_reference(
                instrument,
                item.reference.kind,
                item.reference.name,
                (item.reference.currency or "").upper() or None,
                _restricted_from(item.reference),
            )

        session.add(BrokerHolding(
            account_id=account.id,
            instrument_id=instrument.id if instrument is not None else None,
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


def _restricted_from(reference) -> bool | None:
    """Ограничена ли бумага в обороте по справочным сведениям снимка.

    Правило то же, что в app/instruments/service.py: ограничением считается
    недоступность обеих операций сразу. Один флаг ничего не решает — выпуск,
    закрытый для покупки, но открытый для продажи, распоряжению поддаётся.
    Хотя бы один флаг отсутствует — сведений нет, возвращаем None.
    """
    buy, sell = reference.buy_available, reference.sell_available
    if not isinstance(buy, bool) or not isinstance(sell, bool):
        return None
    return not buy and not sell
