"""Разовое приведение уже записанных инструментов в порядок по справочнику брокера.

Зачем отдельно от синхронизации: обычная синхронизация дозаполняет только те
инструменты, что встретились в операциях её окна (по умолчанию — трое суток
назад, см. SYNC_OVERLAP_DAYS). Инструменты, купленные годы назад и с тех пор
просто лежащие в портфеле, в это окно не попадают никогда, и их вид так и
остался бы тем, что записали при первой загрузке истории.

Запуск (из каталога backend, при заданном TBANK_TOKEN в .env):

    uv run python -m app.instruments.backfill

Обращения к брокеру — только читающие (списочные методы справочника
инструментов); состояние счёта не затрагивается. Запись идёт в таблицу
instrument рабочей базы: она не append-only, обновлять её можно (append-only
только журнал операций).
"""

import logging
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerInstrument
from app.instruments.service import apply_reference, secid_from_ticker
from app.models import Instrument

logger = logging.getLogger(__name__)


def backfill_instruments(session: Session, reference: Mapping[str, BrokerInstrument]) -> int:
    """Дозаполняет вид, название, валюту и признак ограничения в обороте всем
    инструментам, которые нашлись в справочнике `reference` (ключ — ISIN).
    Возвращает число реально изменённых записей. Инструмент, которого в
    справочнике нет, не трогается вовсе."""
    changed = 0
    instruments = session.execute(
        select(Instrument).where(Instrument.isin.is_not(None))
    ).scalars().all()

    for instrument in instruments:
        touched = _repair_secid(instrument)

        found = reference.get(instrument.isin)
        if found is not None:
            touched |= apply_reference(
                instrument, found.kind, found.name, found.currency,
                _restricted_from(found),
            )

        if touched:
            changed += 1

    session.flush()
    return changed


def _restricted_from(found: BrokerInstrument) -> bool | None:
    """Ограничение в обороте по флагам справочника. Правило то же, что и для
    операций (app/instruments/service.py): ограничением считается недоступность
    обеих операций сразу, а отсутствие любого из флагов — отсутствие сведений."""
    if not isinstance(found.buy_available, bool) or not isinstance(found.sell_available, bool):
        return None
    return not found.buy_available and not found.sell_available


def _repair_secid(instrument: Instrument) -> bool:
    """Приводит биржевой идентификатор к тому виду, в котором его знает биржа.

    Отдельно от справочника брокера и до него: инструменты, записанные до того,
    как суффикс «@» начали отбрасывать, стоят с идентификатором, которого на
    MOEX нет, и котировка им не находится. Тикера для починки достаточно —
    справочник тут ничего не добавляет."""
    expected = secid_from_ticker(instrument.ticker)
    if expected is None or instrument.secid == expected:
        return False
    instrument.secid = expected
    return True


def main() -> None:
    # Импорты внутри функции, чтобы импорт модуля (например, из тестов) не
    # тянул за собой настройки, подключение к базе и HTTP-клиент брокера.
    from app.config import get_settings
    from app.connectors.tbank.connector import TBankConnector
    from app.db import SessionLocal

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    token = get_settings().tbank_token
    if not token:
        raise SystemExit("Не задан TBANK_TOKEN в .env — справочник инструментов не у кого спросить")

    reference = TBankConnector(token).fetch_instrument_reference()
    logger.info("Инструментов в справочнике брокера: %s", len(reference))

    with SessionLocal() as session:
        changed = backfill_instruments(session, reference)
        session.commit()
    logger.info("Обновлено инструментов: %s", changed)


if __name__ == "__main__":
    main()
