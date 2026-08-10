import json
import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.instruments import kinds
from app.marketdata.moex import MoexClient, MoexQuote
from app.models import Instrument, Price
from app.money import BASE_CURRENCY, money

logger = logging.getLogger(__name__)

# Метка источника котировок MOEX в таблице price.
MOEX_SOURCE = "moex"

# Метка цены, полученной от брокера (GetPortfolio.currentPrice). Заполняется
# задачей 4; здесь объявлена потому, что от неё зависит приоритет источников
# при чтении.
TBANK_SOURCE = "tbank"

# Приоритет при одинаковой дате: биржа важнее брокера. Биржа — независимый
# источник, брокер — тот самый, с чьим снимком мы сверяемся; оценивать портфель
# его же числами можно, но только когда своих нет.
SOURCE_PRIORITY = {MOEX_SOURCE: 0, TBANK_SOURCE: 1}
_UNKNOWN_SOURCE_PRIORITY = 99

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


# Коды валют номинала в ответах MOEX отличаются от ISO ровно в одном месте:
# рубль там SUR. Остальные совпадают.
FACE_UNIT_TO_ISO = {"SUR": BASE_CURRENCY}


# У MOEX запрашиваются только инструменты, номинированные в рублях. Дело не в
# пересчёте — он теперь есть, — а в том, что гонконгских и американских бумаг
# на MOEX нет вовсе: запрос по ним гарантированно возвращает пустоту и только
# засоряет журнал предупреждениями. Облигации с валютным номиналом сюда входят:
# в справочнике брокера они числятся рублёвыми (расчёты по ним рублёвые), а
# котирует их MOEX — и валюту номинала сообщает сама.
def _priced_at_moex(column) -> object:
    return func.upper(func.coalesce(column, BASE_CURRENCY)) == BASE_CURRENCY


def _price_in_money(instrument: Instrument, quote: MoexQuote) -> tuple[Decimal, str] | None:
    """Цена одной бумаги и валюта этой цены.

    Акции и фонды MOEX котирует прямо в деньгах и всегда в рублях. Облигации —
    в процентах от номинала, и номинал бывает не рублёвым: замещающие и
    юаневые выпуски. Без пересчёта из процентов облигация с номиналом 1000 ₽
    оценивалась в сотню рублей.

    Накопленный купонный доход в цену не входит: он платится сверх неё и по
    смыслу ближе к начислению, чем к стоимости бумаги.
    """
    if quote.price is None:
        return None
    if instrument.kind != kinds.BOND:
        return quote.price, BASE_CURRENCY
    if not quote.face_value:
        return None
    face_unit = (quote.face_unit or "SUR").upper()
    currency = FACE_UNIT_TO_ISO.get(face_unit, face_unit)
    return money(quote.price / Decimal("100") * quote.face_value), currency


def refresh_last_prices(session: Session, client: MoexClient, on_date: date) -> int:
    instruments = session.execute(
        select(Instrument).where(
            Instrument.secid.is_not(None),
            _priced_at_moex(Instrument.currency),
        )
    ).scalars().all()

    updated = 0
    for instrument in instruments:
        engine, market = ENGINE_MARKET_BY_KIND.get(instrument.kind, ("stock", "shares"))
        try:
            quote = client.quote(instrument.secid, market=market, engine=engine)
        except (httpx.HTTPError, KeyError, json.JSONDecodeError):
            logger.warning(
                "Не удалось получить цену для инструмента %s (secid=%s)",
                instrument.id, instrument.secid, exc_info=True,
            )
            continue

        priced = _price_in_money(instrument, quote)
        if priced is None:
            continue
        price, currency = priced

        statement = insert(Price).values(
            instrument_id=instrument.id, on_date=on_date, close=price,
            currency=currency, source=MOEX_SOURCE,
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date, Price.source],
            set_={"close": price, "currency": currency},
        )
        session.execute(statement)
        updated += 1

    session.flush()
    return updated


@dataclass(frozen=True)
class LatestPrice:
    """Последняя пригодная котировка инструмента: цена, её валюта, дата и
    источник. Всё четыре поля отдаются одним проходом по таблице цен —
    аналитике нужны все, а раздельные запросы за ними означали бы несколько
    одинаковых проходов на каждый показ дашборда."""

    close: Decimal
    on_date: date
    currency: str
    source: str


def latest_prices(session: Session) -> dict[int, LatestPrice]:
    """Самая свежая цена по каждому инструменту.

    Свежесть решает первой, происхождение — вторым: вчерашняя биржевая цена
    хуже сегодняшней брокерской, потому что вопрос стоит «сколько стоит
    сейчас». При равной дате выигрывает биржа (SOURCE_PRIORITY).

    Фильтра по валюте здесь больше нет: валюта хранится у самой цены, и
    пересчёт в рубли делает оценка (app/analytics/valuation.py).
    """
    priority = case(SOURCE_PRIORITY, value=Price.source, else_=_UNKNOWN_SOURCE_PRIORITY)
    ranked = select(
        Price.instrument_id,
        Price.close,
        Price.on_date,
        Price.currency,
        Price.source,
        func.row_number().over(
            partition_by=Price.instrument_id,
            order_by=(Price.on_date.desc(), priority.asc()),
        ).label("rn"),
    ).subquery()

    rows = session.execute(
        select(
            ranked.c.instrument_id, ranked.c.close, ranked.c.on_date,
            ranked.c.currency, ranked.c.source,
        ).where(ranked.c.rn == 1)
    ).all()
    return {
        instrument_id: LatestPrice(close=close, on_date=on_date, currency=currency, source=source)
        for instrument_id, close, on_date, currency, source in rows
    }
