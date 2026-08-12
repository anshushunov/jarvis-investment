import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.instruments import kinds
from app.marketdata.moex import MoexClient, MoexQuote
from app.marketdata.symbols import moex_filter
from app.models import Instrument, Price
from app.money import BASE_CURRENCY, money

logger = logging.getLogger(__name__)

# Метка источника котировок MOEX в таблице price.
MOEX_SOURCE = "moex"

# Метка цены, полученной от брокера (GetPortfolio.currentPrice). Заполняется
# задачей 4; здесь объявлена потому, что от неё зависит приоритет источников
# при чтении.
TBANK_SOURCE = "tbank"

# Приоритет при одинаковой дате: биржа важнее независимого источника, а тот
# важнее брокера. Брокер — сторона, с чьим снимком мы сверяемся; оценивать
# портфель его же числами можно, только когда своих нет.
#
# Yahoo указан литералом, а не импортом YAHOO_SOURCE: history.py импортирует
# service.py, и обратный импорт замкнул бы круг.
SOURCE_PRIORITY = {MOEX_SOURCE: 0, "yahoo": 1, TBANK_SOURCE: 2}
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


def price_in_money(
    kind: str, price: Decimal, face_value: Decimal | None, face_unit: str | None
) -> tuple[Decimal, str] | None:
    """Цена одной бумаги и валюта этой цены.

    Акции и фонды MOEX котирует прямо в деньгах и всегда в рублях. Облигации —
    в процентах от номинала, и номинал бывает не рублёвым: замещающие и
    юаневые выпуски. Без пересчёта из процентов облигация с номиналом 1000 ₽
    оценивалась в сотню рублей.

    Накопленный купонный доход в цену не входит: он платится сверх неё и по
    смыслу ближе к начислению, чем к стоимости бумаги.

    Функция берёт числа, а не котировку: живая цена приходит из блока
    marketdata, историческая — из блока history, и правило перевода у них
    обязано быть одно.
    """
    if kind != kinds.BOND:
        return price, BASE_CURRENCY
    if not face_value:
        return None
    unit = (face_unit or "SUR").upper()
    currency = FACE_UNIT_TO_ISO.get(unit, unit)
    return money(price / Decimal("100") * face_value), currency


def refresh_last_prices(session: Session, client: MoexClient, on_date: date) -> int:
    instruments = session.execute(
        select(Instrument).where(
            Instrument.secid.is_not(None),
            moex_filter(Instrument.isin, Instrument.currency),
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

        priced = (
            None if quote.price is None
            else price_in_money(instrument.kind, quote.price, quote.face_value, quote.face_unit)
        )
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


# Предельный возраст цены. Выходные, праздники и несовпадение календарей MOEX,
# США и Гонконга закрываются молча — это устройство биржи, а не пробел в
# данных. Настоящая остановка торгов (иностранные бумаги в 2022 году) за неделю
# выходит, и позиция честно становится неоценённой: замороженная цена, которую
# тянут месяцами, выглядит фактом и им не является.
PRICE_MAX_AGE = timedelta(days=7)


def prices_as_of(
    session: Session, on_date: date, max_age: timedelta = PRICE_MAX_AGE
) -> dict[int, LatestPrice]:
    """Цена каждого инструмента на дату: самая свежая не позже неё.

    Свежесть решает первой, происхождение — вторым: вчерашняя биржевая цена
    хуже сегодняшней брокерской, потому что вопрос стоит «сколько стоит на эту
    дату». При равной дате выигрывает биржа, затем независимый источник, и
    только потом брокер (SOURCE_PRIORITY).

    Цена старше `max_age` не возвращается вовсе: инструмент считается
    неоценённым, и покрытие снимка это назовёт.

    Фильтра по валюте здесь нет: валюта хранится у самой цены, и пересчёт в
    рубли делает оценка (app/analytics/valuation.py).
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
    ).where(
        Price.on_date <= on_date,
        Price.on_date >= on_date - max_age,
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
