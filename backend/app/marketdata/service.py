import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.instruments import kinds
from app.marketdata.moex import MoexClient
from app.models import Instrument, Price
from app.money import BASE_CURRENCY

logger = logging.getLogger(__name__)

# Метка источника котировок MOEX в таблице price.
MOEX_SOURCE = "moex"

# Ключи — доменные виды инструментов (app/instruments/kinds.py); их же кладёт
# коннектор при разрешении инструмента. Вид, которого здесь нет (kinds.OTHER,
# kinds.METAL, kinds.FUTURES), уходит на рынок акций по умолчанию — котировки
# там для него просто не найдётся, и это честнее, чем искать заведомо не там.
ENGINE_MARKET_BY_KIND = {
    kinds.SHARE: ("stock", "shares"),
    kinds.ETF: ("stock", "shares"),
    kinds.BOND: ("stock", "bonds"),
    kinds.CURRENCY: ("currency", "selt"),
}


# MOEX ISS отдаёт котировки в рублях. Для инструмента, номинированного не в
# рублях, такая цена — не оценка: рублёвое число под знаком доллара выглядит
# правдой, но ею не является, а пересчёта по курсам в этой фазе нет. Поэтому
# такие инструменты не запрашиваются у MOEX вовсе и их прежние рублёвые
# котировки (если успели записаться) не используются при оценке — позиция
# честно показывается неоценённой и попадает в счётчик покрытия.
def _priced_in_base_currency(column) -> object:
    return func.upper(func.coalesce(column, BASE_CURRENCY)) == BASE_CURRENCY


def refresh_last_prices(session: Session, client: MoexClient, on_date: date) -> int:
    instruments = session.execute(
        select(Instrument).where(
            Instrument.secid.is_not(None),
            _priced_in_base_currency(Instrument.currency),
        )
    ).scalars().all()

    updated = 0
    for instrument in instruments:
        engine, market = ENGINE_MARKET_BY_KIND.get(instrument.kind, ("stock", "shares"))
        try:
            price = client.last_price(instrument.secid, market=market, engine=engine)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError):
            logger.warning(
                "Не удалось получить цену для инструмента %s (secid=%s)",
                instrument.id, instrument.secid, exc_info=True,
            )
            continue

        if price is None:
            continue

        statement = insert(Price).values(
            instrument_id=instrument.id, on_date=on_date, close=price, source=MOEX_SOURCE
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date], set_={"close": price}
        )
        session.execute(statement)
        updated += 1

    session.flush()
    return updated


@dataclass(frozen=True)
class LatestPrice:
    """Последняя известная котировка инструмента вместе с её датой.

    Цена и дата отдаются вместе, одним проходом по таблице цен. Раньше
    аналитика заводила собственный оконный запрос дат, дословно повторяющий
    этот, — два одинаковых прохода по всей таблице цен на каждый показ
    дашборда.
    """

    close: Decimal
    on_date: date


def latest_prices(session: Session) -> dict[int, LatestPrice]:
    """Последние котировки, пригодные для оценки в базовой валюте.

    Рублёвые котировки MOEX отбрасываются для инструментов, номинированных не в
    рублях (см. комментарий у refresh_last_prices). Фильтр стоит и здесь, а не
    только при загрузке: в базе могли остаться котировки, записанные до того,
    как валюта инструмента была исправлена по справочнику брокера. Котировки из
    других источников (когда появится курсовой) под это правило не подпадают.
    """
    ranked = select(
        Price.instrument_id,
        Price.close,
        Price.on_date,
        func.row_number().over(
            partition_by=Price.instrument_id, order_by=Price.on_date.desc()
        ).label("rn"),
    ).join(
        Instrument, Instrument.id == Price.instrument_id
    ).where(
        or_(Price.source != MOEX_SOURCE, _priced_in_base_currency(Instrument.currency))
    ).subquery()

    rows = session.execute(
        select(ranked.c.instrument_id, ranked.c.close, ranked.c.on_date).where(ranked.c.rn == 1)
    ).all()
    return {
        instrument_id: LatestPrice(close=close, on_date=on_date)
        for instrument_id, close, on_date in rows
    }
