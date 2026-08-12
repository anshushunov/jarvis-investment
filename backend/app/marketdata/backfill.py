"""Разовая загрузка исторических котировок и курсов.

Запуск (из каталога backend):

    uv run python -m app.marketdata.backfill
    uv run python -m app.marketdata.backfill --from 2024-01-01
    uv run python -m app.marketdata.backfill --dry-run

Ходит в сеть: MOEX по бумагам российских эмитентов, Yahoo по иностранным, ЦБ
по валютам, MOEX по золоту. Объём — сотни запросов, минуты работы. Пишет в
`price` и `fx_rate`; повторный прогон обновляет уже загруженное, а не двоит.

`--dry-run` ничего не загружает, а показывает таблицу сопоставлений: какая
бумага куда пойдёт и под каким символом. Смотреть её до первого прогона
обязательно — неверно сопоставленный символ даёт не отказ, а правдоподобную
цену чужой бумаги.
"""

import argparse
import logging
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.marketdata.cbr import CbrClient
from app.marketdata.history import load_fx_history, load_metal_history, load_price_history
from app.marketdata.moex import MoexClient
from app.marketdata.symbols import priced_at_moex, yahoo_symbol
from app.marketdata.yahoo import YahooClient
from app.models import CashBalance, Instrument, Transaction
from app.money import BASE_CURRENCY
from app.snapshots.backfill import first_operation_date
from app.timeutils import moscow_today

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Металлы у ЦБ не котируются вовсе: они идут с MOEX отдельным прогоном
# (load_metal_history), и спрашивать по ним курс ЦБ — гарантированный KeyError.
METAL_CURRENCIES = {"XAU", "XAG", "XPT", "XPD"}


def history_currencies(session: Session) -> list[str]:
    """Валюты, для которых нужна история курсов.

    Собираются из трёх мест сразу: валюты операций (в них шли расчёты), валюты
    инструментов (в них номинированы цены) и валюты сегодняшних остатков.
    Металлы сюда не входят — у ЦБ их нет, они идут с MOEX отдельно.
    """
    currencies: set[str] = set()
    for column in (Transaction.currency, Instrument.currency, CashBalance.currency):
        for value in session.execute(select(column).distinct()).scalars():
            if value:
                currencies.add(value.upper())
    currencies.discard(BASE_CURRENCY)
    currencies -= METAL_CURRENCIES
    return sorted(currencies)


def _report_mapping(session: Session) -> None:
    instruments = list(session.execute(select(Instrument).order_by(Instrument.isin)).scalars())
    unresolved: list[Instrument] = []
    for instrument in instruments:
        if priced_at_moex(instrument):
            logger.info("MOEX   %-14s %-12s %s", instrument.isin, instrument.secid,
                        instrument.issuer or "")
            continue
        symbol = yahoo_symbol(instrument)
        if symbol is None:
            unresolved.append(instrument)
            continue
        logger.info("Yahoo  %-14s %-12s %s", instrument.isin, symbol, instrument.issuer or "")

    logger.info("")
    logger.info("Не сопоставлено: %s из %s", len(unresolved), len(instruments))
    for instrument in unresolved:
        logger.info("  %-14s %-12s %s", instrument.isin, instrument.ticker or "",
                    instrument.issuer or "")
    logger.info("")
    logger.info("Каждая несопоставленная бумага останется неоценённой на тех датах, "
                "где она лежала в портфеле. Символ добавляется в "
                "YAHOO_SYMBOL_BY_ISIN (app/marketdata/symbols.py).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Загрузка истории котировок и курсов")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=None,
                        help="начало периода; по умолчанию — дата первой операции журнала")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None,
                        help="конец периода; по умолчанию — сегодня")
    parser.add_argument("--dry-run", action="store_true",
                        help="показать сопоставление бумаг с источниками и выйти")
    args = parser.parse_args()

    with SessionLocal() as session:
        if args.dry_run:
            _report_mapping(session)
            return

        start = args.start or first_operation_date(session)
        if start is None:
            logger.warning("Журнал пуст — загружать историю не для чего")
            return
        end = args.end or moscow_today()

        moex, yahoo, cbr = MoexClient(), YahooClient(), CbrClient()

        instruments = list(session.execute(select(Instrument).order_by(Instrument.id)).scalars())
        loaded = 0
        for number, instrument in enumerate(instruments, start=1):
            try:
                days = load_price_history(session, instrument, start, end, moex=moex, yahoo=yahoo)
            except httpx.HTTPError:
                # Отказ источника по одной бумаге не должен ронять прогон на
                # двести пятьдесят бумаг: бумага останется неоценённой, и это
                # будет видно в покрытии, а не потеряно.
                logger.warning("Инструмент %s (%s): источник недоступен",
                               instrument.id, instrument.isin, exc_info=True)
                continue
            loaded += days
            if days:
                logger.info("[%s/%s] %s: дней %s", number, len(instruments),
                            instrument.isin or instrument.ticker, days)
            session.commit()

        currencies = history_currencies(session)
        rates = load_fx_history(session, currencies, start, end, cbr=cbr)
        metals = load_metal_history(session, start, end, moex=moex)
        session.commit()

        logger.info("Загружено дней котировок: %s по %s инструментам", loaded, len(instruments))
        logger.info("Курсов: %s по валютам %s; металлов: %s", rates, ", ".join(currencies), metals)


if __name__ == "__main__":
    main()
