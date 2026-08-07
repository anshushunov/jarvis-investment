import json
import logging
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.marketdata.moex import MoexClient
from app.models import Instrument, Price

logger = logging.getLogger(__name__)

ENGINE_MARKET_BY_KIND = {
    "share": ("stock", "shares"),
    "etf": ("stock", "shares"),
    "bond": ("stock", "bonds"),
    "currency": ("currency", "selt"),
}


def refresh_last_prices(session: Session, client: MoexClient, on_date: date) -> int:
    instruments = session.execute(
        select(Instrument).where(Instrument.secid.is_not(None))
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
            instrument_id=instrument.id, on_date=on_date, close=price, source="moex"
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date], set_={"close": price}
        )
        session.execute(statement)
        updated += 1

    session.flush()
    return updated


def latest_prices(session: Session) -> dict[int, Decimal]:
    ranked = select(
        Price.instrument_id,
        Price.close,
        func.row_number().over(
            partition_by=Price.instrument_id, order_by=Price.on_date.desc()
        ).label("rn"),
    ).subquery()

    rows = session.execute(
        select(ranked.c.instrument_id, ranked.c.close).where(ranked.c.rn == 1)
    ).all()
    return {instrument_id: close for instrument_id, close in rows}
