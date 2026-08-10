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

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.connectors.base import BrokerInstrument
from app.instruments.service import apply_reference, secid_from_ticker
from app.models import Instrument

logger = logging.getLogger(__name__)


def backfill_instruments(session: Session, reference: Mapping[str, BrokerInstrument]) -> int:
    """Дозаполняет вид, название, валюту и признак ограничения в обороте всем
    инструментам, которые нашлись в справочнике `reference` (ключ — FIGI).
    Возвращает число реально изменённых записей. Инструмент, которого в
    справочнике нет, не трогается вовсе.

    Ключ справочника — FIGI, а не ISIN, потому что запись справочника описывает
    не бумагу, а бумагу на площадке. У одного ISIN таких записей до двенадцати,
    и расходятся они ровно в том, ради чего дозаполнение затевалось: NVDA на
    SPBXM номинирована в долларах и недоступна ни к покупке, ни к продаже, а её
    рублёвое зеркало NVDA-RM на MTQR доступно к обеим.

    Выбирать среди них «самую доступную» — значит объявить свободной любую
    бумагу, у которой есть хоть одно живое зеркало (живая проверка 10.08.2026:
    так свободными оказались Unity, Block и Teladoc на 53 тыс. ₽). Выбирать
    «последнюю по порядку ответа» — значит с той же лёгкостью объявить
    ограниченной свободно торгуемую бумагу (тот же прогон: OZON, EQMX, GOLD, T,
    SBBY, OBLG, DATA и ДОМ.РФ на 2.45 млн ₽) и заодно переписать американским
    акциям валюту на рубли.

    Правильная площадка известна точно: это FIGI операции, которой бумага
    попала в журнал. Он приходит от самого брокера и описывает ровно ту
    площадку, на которой бумага у владельца лежит. По ISIN справочник сводится
    только там, где FIGI сопоставить не удалось, — см. _by_isin.
    """
    changed = 0
    instruments = session.execute(select(Instrument)).scalars().all()
    board_figi = _board_figi_by_instrument(session)
    fallback = _by_isin(reference)

    for instrument in instruments:
        touched = _repair_secid(instrument)

        found = reference.get(board_figi.get(instrument.id, ""))
        if found is None and instrument.isin:
            found = fallback.get(instrument.isin)
        if found is not None:
            touched |= apply_reference(
                instrument, found.kind, found.name, found.currency,
                _restricted_from(found),
            )

        if touched:
            changed += 1

    session.flush()
    return changed


def _board_figi_by_instrument(session: Session) -> dict[int, str]:
    """FIGI площадки, на которой бумага лежит у владельца, по каждому
    инструменту журнала.

    Берётся самая свежая операция: площадка со временем меняется, и текущее
    состояние описывает последняя из них, а не первая. Тикер для той же цели не
    годится: у OZON он одинаковый и на TQBR, и на SPBXM, а у половины
    американских бумаг в журнале вместо тикера записан ISIN — различить
    площадки по нему нельзя.
    """
    rows = session.execute(text("""
        select distinct on (instrument_id) instrument_id, payload->>'figi'
        from transaction
        where instrument_id is not null and payload->>'figi' is not null
        order by instrument_id, executed_at desc, id desc
    """)).all()
    return {instrument_id: figi for instrument_id, figi in rows}


def _by_isin(reference: Mapping[str, BrokerInstrument]) -> dict[str, BrokerInstrument]:
    """Запасной путь: справочник, сведённый по ISIN.

    Нужен инструменту, для которого площадка неизвестна, — например записанному
    не из операции, а из снимка позиций брокера. Победитель выбирается по рангу
    доступности: из двух записей об одной бумаге больше сообщает та, что
    разрешает хоть какую-то операцию. Правило заведомо грубее выбора по FIGI и
    именно поэтому запасное — зеркальная площадка с рублёвыми расчётами по нему
    побеждает основную.
    """
    result: dict[str, BrokerInstrument] = {}
    for instrument in reference.values():
        if not instrument.isin:
            continue
        known = result.get(instrument.isin)
        if known is None or _availability_rank(instrument) > _availability_rank(known):
            result[instrument.isin] = instrument
    return result


def _availability_rank(instrument: BrokerInstrument) -> int:
    """Насколько запись справочника свидетельствует о свободе распоряжения
    бумагой. Сравнивать имеет смысл только записи одного ISIN — см. _by_isin.

    Ноль — сведений нет вовсе (хотя бы одного флага не хватает), и такая запись
    проигрывает любой другой: по ней всё равно ничего не решить. Единица — обе
    операции недоступны. Двойка — доступна хотя бы одна.
    """
    if not isinstance(instrument.buy_available, bool):
        return 0
    if not isinstance(instrument.sell_available, bool):
        return 0
    return 2 if (instrument.buy_available or instrument.sell_available) else 1


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

    reference = TBankConnector(token).fetch_instruments_by_figi()
    logger.info("Записей в справочнике брокера: %s", len(reference))

    with SessionLocal() as session:
        changed = backfill_instruments(session, reference)
        session.commit()
    logger.info("Обновлено инструментов: %s", changed)


if __name__ == "__main__":
    main()
