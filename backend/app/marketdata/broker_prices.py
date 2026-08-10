from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPrice
from app.marketdata.service import TBANK_SOURCE
from app.models import Instrument, Price


def store_broker_prices(session: Session, prices: list[BrokerPrice], on_date: date) -> int:
    """Записывает цены брокера в таблицу котировок под источником `tbank`.

    Инструменты ищутся одним запросом по всем ISIN пачки: цен на счёте до
    полусотни, а запрос на каждую превратил бы синхронизацию в сотни round-trip
    к базе.
    """
    if not prices:
        return 0

    # Один ISIN приходит в пачке дважды, когда брокер держит бумагу на двух
    # площадках: у store_holdings это уже уронило живой прогон. Здесь падения
    # не будет — источник входит в ключ уникальности, и вторая цена просто
    # затрёт первую, — но затрёт молча, а площадки различаются валютой, и в
    # оценку ушла бы та цена, что оказалась последней в ответе. Побеждает
    # первая: порядок ответа брокера — единственное, что их различает, и первая
    # хотя бы устойчива между прогонами. Складывать цены, в отличие от
    # количеств, нельзя: это одна и та же бумага, а не две её порции.
    merged: dict[str, BrokerPrice] = {}
    for item in prices:
        merged.setdefault(item.isin, item)

    instrument_ids = {
        isin: instrument_id
        for instrument_id, isin in session.execute(
            select(Instrument.id, Instrument.isin).where(Instrument.isin.in_(merged.keys()))
        ).all()
    }

    written = 0
    for item in merged.values():
        instrument_id = instrument_ids.get(item.isin)
        # Инструмента нет в справочнике — привязать цену не к чему. Заводить
        # его здесь нельзя: вид, название и валюта приходят с операциями, и
        # заготовка из одной цены осталась бы навсегда «видом неизвестно».
        if instrument_id is None:
            continue
        statement = insert(Price).values(
            instrument_id=instrument_id, on_date=on_date,
            close=item.price, currency=item.currency, source=TBANK_SOURCE,
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date, Price.source],
            set_={"close": item.price, "currency": item.currency},
        )
        session.execute(statement)
        written += 1

    session.flush()
    return written
