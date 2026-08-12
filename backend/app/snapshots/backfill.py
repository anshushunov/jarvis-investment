"""Достройка истории стоимости задним числом.

Запуск (из каталога backend):

    uv run python -m app.snapshots.backfill
    uv run python -m app.snapshots.backfill --from 2024-01-01 --to 2024-12-31

В сеть не ходит вовсе: считает по журналу, по уже загруженной истории цен и
курсов (`uv run python -m app.marketdata.backfill`) и по сегодняшним остаткам
брокера. Разделение не косметическое: пересчёт понадобится повторять — после
разбора расхождений владельцем, после починки сопоставления символа, — и если
каждый пересчёт заново выгребает сеть, его не будут делать вовсе.

Прогон идемпотентен: правило перезаписи живёт в `store_snapshot`.
"""

import argparse
import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.cash_history import cash_history
from app.analytics.service import Holding, value_portfolio
from app.db import SessionLocal
from app.marketdata.fx import latest_rate_dates, latest_rates
from app.marketdata.service import prices_as_of
from app.models import SNAPSHOT_BACKFILL, Account, DailySnapshot, Instrument, Transaction
from app.positions.history import holdings_at
from app.positions.service import ledger_entries
from app.snapshots.service import store_snapshot
from app.timeutils import moscow_today

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def first_operation_date(session: Session) -> date | None:
    """Дата первой операции журнала — начало истории портфеля."""
    earliest = session.execute(select(func.min(Transaction.executed_at))).scalar()
    return earliest.date() if earliest is not None else None


def backfill_snapshots(session: Session, start: date, end: date) -> int:
    """Достраивает точки истории за период. Возвращает число записанных дней.

    Журнал каждого счёта читается один раз на весь период, а не на каждую дату:
    двух тысяч обходов таблицы операций прогон бы не пережил. Цены и курсы, в
    отличие от него, спрашиваются на каждую дату — они и есть то, что меняется.
    """
    accounts = list(session.execute(select(Account)).scalars())
    entries = {account.id: ledger_entries(session, account) for account in accounts}
    instruments = {
        instrument.id: instrument
        for instrument in session.execute(select(Instrument)).scalars()
    }
    cash = cash_history(session, start, end)

    written = 0
    day = start
    while day <= end:
        holdings: list[Holding] = []
        for account in accounts:
            for instrument_id, state in holdings_at(entries[account.id], day).items():
                holdings.append(Holding(
                    account_id=account.id,
                    instrument=instruments[instrument_id],
                    quantity=state.quantity,
                    # Блокировки на прошлую дату взять неоткуда: снимок
                    # блокировок у брокера текущий. Ноль честнее подстановки
                    # сегодняшнего значения — оно к 2021 году отношения не имеет.
                    blocked=Decimal("0"),
                ))

        overview = value_portfolio(
            holdings=holdings,
            cash=cash.get(day, {}),
            blocked_cash={},
            prices=prices_as_of(session, day),
            rates=latest_rates(session, day),
            rate_dates=latest_rate_dates(session, day),
        )
        store_snapshot(session, day, overview, SNAPSHOT_BACKFILL)
        written += 1

        if day.day == 1:
            logger.info("Достроено по %s: %s ₽, оценено %s из %s",
                        day, overview.total_value,
                        overview.valued_positions, overview.positions_total)
        day += timedelta(days=1)

    session.flush()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Достройка истории стоимости портфеля")
    parser.add_argument("--from", dest="start", type=date.fromisoformat, default=None,
                        help="начало периода; по умолчанию — дата первой операции журнала")
    parser.add_argument("--to", dest="end", type=date.fromisoformat, default=None,
                        help="конец периода; по умолчанию — сегодня")
    args = parser.parse_args()

    with SessionLocal() as session:
        start = args.start or first_operation_date(session)
        if start is None:
            logger.warning("Журнал пуст — достраивать нечего")
            return
        end = args.end or moscow_today()

        written = backfill_snapshots(session, start, end)
        session.commit()

        points = session.execute(
            select(
                func.count(DailySnapshot.id),
                func.count(DailySnapshot.id).filter(
                    DailySnapshot.valued_positions == DailySnapshot.positions_total
                ),
            )
        ).one()
        logger.info("Достроено дней: %s (с %s по %s)", written, start, end)
        logger.info("Точек всего %s, из них с полной оценкой %s", points[0], points[1])


if __name__ == "__main__":
    main()
