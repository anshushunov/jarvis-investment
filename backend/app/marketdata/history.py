"""Загрузка исторических котировок в таблицу `price`.

Отдельно от `service.py`: тот отвечает за сегодняшнюю цену и за чтение цен, а
здесь — разовое наполнение истории. Общее у них — правило перевода котировки в
деньги (`price_in_money`) и правило маршрута (`app/marketdata/symbols.py`); оба
живут в одном месте на проект и зовутся отсюда, а не переписываются.
"""

import logging
from datetime import date

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.marketdata.fx import CBR_SOURCE, METAL_SECIDS
from app.marketdata.fx import MOEX_SOURCE as FX_MOEX_SOURCE
from app.marketdata.service import (
    ENGINE_MARKET_BY_KIND,
    MOEX_SOURCE,
    price_in_money,
)
from app.marketdata.symbols import priced_at_moex, yahoo_symbol
from app.models import FxRate, Instrument, Price
from app.money import BASE_CURRENCY

logger = logging.getLogger(__name__)

# Метка независимого источника иностранных котировок.
YAHOO_SOURCE = "yahoo"


def _store(session: Session, instrument_id: int, rows: list[tuple[date, object, str]], source: str) -> int:
    written = 0
    for on_date, close, currency in rows:
        statement = insert(Price).values(
            instrument_id=instrument_id, on_date=on_date, close=close,
            currency=currency, source=source,
        ).on_conflict_do_update(
            index_elements=[Price.instrument_id, Price.on_date, Price.source],
            set_={"close": close, "currency": currency},
        )
        session.execute(statement)
        written += 1
    session.flush()
    return written


def _from_moex(instrument: Instrument, start: date, end: date, moex) -> list[tuple[date, object, str]]:
    engine, market = ENGINE_MARKET_BY_KIND.get(instrument.kind, ("stock", "shares"))
    rows: list[tuple[date, object, str]] = []
    for point in moex.close_history(instrument.secid, start, end, market=market, engine=engine):
        priced = price_in_money(instrument.kind, point.close, point.face_value, point.face_unit)
        if priced is None:
            # Облигация без номинала на эту дату: процент в деньги не перевести,
            # а записать процент ценой значило бы оценить выпуск в сотню рублей.
            continue
        close, currency = priced
        rows.append((point.on_date, close, currency))
    return rows


def _from_yahoo(instrument: Instrument, start: date, end: date, yahoo) -> list[tuple[date, object, str]]:
    symbol = yahoo_symbol(instrument)
    if symbol is None:
        logger.info("Инструмент %s (%s): символа Yahoo нет, история не загружается",
                    instrument.id, instrument.isin)
        return []

    history = yahoo.close_history(symbol, start, end)
    if history is None:
        logger.warning("Символ %s у Yahoo не найден (инструмент %s, %s)",
                       symbol, instrument.id, instrument.isin)
        return []

    expected = (instrument.currency or BASE_CURRENCY).upper()
    if history.currency != expected:
        # Сопоставление символа неверно. Отказ, а не предупреждение: цена чужой
        # бумаги ничем не отличается от настоящей, кроме того, что неверна, —
        # и обнаружится это не сразу, а через месяцы, кривым графиком.
        logger.error(
            "Символ %s отвечает в %s, а инструмент %s (%s) номинирован в %s — "
            "сопоставление неверно, история не загружается",
            symbol, history.currency, instrument.id, instrument.isin, expected,
        )
        return []

    return [(on_date, close, history.currency) for on_date, close in history.points]


def load_price_history(
    session: Session, instrument: Instrument, start: date, end: date, *, moex, yahoo
) -> int:
    """Загружает историю котировок одного инструмента. Возвращает число дней.

    Маршрут выбирается общим правилом (`app/marketdata/symbols.py`): бумага
    российского эмитента идёт на MOEX независимо от валюты расчётов, остальные
    — на Yahoo. Ноль возвращается и когда истории нет, и когда спрашивать
    некого: и то и другое оставляет бумагу неоценённой на своих датах, и видно
    это будет в покрытии снимка, а не в тишине.
    """
    if priced_at_moex(instrument):
        return _store(session, instrument.id, _from_moex(instrument, start, end, moex), MOEX_SOURCE)
    return _store(session, instrument.id, _from_yahoo(instrument, start, end, yahoo), YAHOO_SOURCE)


def _store_rate(session: Session, currency: str, on_date: date, rate, source: str) -> None:
    statement = insert(FxRate).values(
        currency=currency, on_date=on_date, rate=rate, source=source
    ).on_conflict_do_update(
        index_elements=[FxRate.currency, FxRate.on_date],
        set_={"rate": rate, "source": source},
    )
    session.execute(statement)


def load_fx_history(session: Session, currencies: list[str], start: date, end: date, *, cbr) -> int:
    """Курсы ЦБ за период по каждой названной валюте. Возвращает число строк.

    Базовая валюта пропускается: рубль к рублю — единица, и она не хранится
    (см. `latest_rates`). Дни, в которые ЦБ курса не публиковал, остаются
    пустыми — «курс, действующий на дату» выводит читающая сторона.
    """
    written = 0
    for currency in currencies:
        if currency.upper() == BASE_CURRENCY:
            continue
        for on_date, rate in cbr.rate_history(currency, start, end):
            _store_rate(session, currency.upper(), on_date, rate, CBR_SOURCE)
            written += 1
    session.flush()
    return written


def load_metal_history(session: Session, start: date, end: date, *, moex) -> int:
    """Курсы металлов за период с MOEX: у ЦБ их нет вовсе.

    Тот же инструмент, которым фаза 2a считает золото сегодня (GLDRUB_TOM,
    движок currency, рынок selt), — рубли за грамм.
    """
    written = 0
    for currency, secid in METAL_SECIDS.items():
        for point in moex.close_history(secid, start, end, market="selt", engine="currency"):
            _store_rate(session, currency, point.on_date, point.close, FX_MOEX_SOURCE)
            written += 1
    session.flush()
    return written
