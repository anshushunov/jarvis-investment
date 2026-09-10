"""Инструмент data_quality: границы честности — расхождения с брокером, бумаги
без цен, блокировки, свежесть данных.

Это то, что не даёт назвать TWR −25,26 % без оговорки: число измеренных дней,
шесть бумаг без котировок и неразобранные расхождения из таблицы reconciliation.
"""

from collections import Counter
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.analytics.service import portfolio_overview
from app.models import (
    Account,
    BrokerHolding,
    CashBalance,
    DailySnapshot,
    Instrument,
    Reconciliation,
    SyncRun,
)
from app.returns.metrics import incomplete_days

# Денежного итога брокера (totalAmountPortfolio) в базе нет: его знает только
# живой запрос, и инструмент честно называет прогон, которым сверка снимается.
VALUATION_CHECK_NOTE = (
    "Денежной сверки с итогом брокера (totalAmountPortfolio) здесь нет: его знает только "
    "живой запрос к API, и снимает её прогон `cd backend && uv run python -m app.valuation_check`."
)


def data_quality(session: Session) -> dict:
    accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
    instruments = {row.id: row for row in session.execute(select(Instrument)).scalars()}
    overview = portfolio_overview(session)

    def account_of(account_id: int | None) -> dict | None:
        return s.account_ref(accounts[account_id]) if account_id in accounts else None

    def name_of(instrument_id: int | None) -> str | None:
        return s.instrument_name(instruments[instrument_id]) if instrument_id in instruments else None

    reconciliations = [
        {"account": account_of(row.account_id), "isin": row.isin, "name": name_of(row.instrument_id),
         "ledger_quantity": s.qty(row.ledger_quantity), "broker_quantity": s.qty(row.broker_quantity),
         "status": row.status, "checked_at": s.moment(row.checked_at)}
        for row in session.execute(
            select(Reconciliation).order_by(Reconciliation.account_id, Reconciliation.isin)
        ).scalars()
    ]

    snapshots = list(session.execute(select(DailySnapshot).order_by(DailySnapshot.on_date)).scalars())
    incomplete = incomplete_days(snapshots)
    without_price = Counter(name for row in snapshots for name in (row.unpriced or []))
    full_days = len(snapshots) - len(incomplete)

    blocked_holdings = [
        {"account": account_of(row.account_id), "isin": row.isin, "name": name_of(row.instrument_id),
         "quantity": s.qty(row.quantity), "blocked": s.qty(row.blocked)}
        for row in session.execute(select(BrokerHolding).where(BrokerHolding.blocked != 0)).scalars()
    ]
    blocked_cash = [
        {"account": account_of(row.account_id), "currency": row.currency,
         "amount": s.amount(row.amount), "blocked": s.amount(row.blocked)}
        for row in session.execute(select(CashBalance).where(CashBalance.blocked != 0)).scalars()
    ]

    # Последний прогон синхронизации каждого счёта — в порядке запуска, поэтому
    # последний по счёту перетирает предыдущие.
    latest: dict[int | None, SyncRun] = {}
    for run in session.execute(select(SyncRun).order_by(SyncRun.started_at, SyncRun.id)).scalars():
        latest[run.account_id] = run
    last_runs = [
        {"account": account_of(run.account_id), "status": run.status,
         "started_at": s.moment(run.started_at), "finished_at": s.moment(run.finished_at),
         "inserted": run.inserted, "mismatches": run.mismatches, "corrected": run.corrected,
         "error": run.error}
        for run in latest.values()
    ]

    last = snapshots[-1] if snapshots else None
    return {
        "reconciliation": {
            "unresolved": reconciliations, "count": len(reconciliations),
            "note": ("Расхождения количеств журнала с брокером; разбираются решениями владельца на "
                     "экране «Сделки и расхождения», не инструментами."),
        },
        "valuation": {
            "positions_total": overview.positions_total, "valued_positions": overview.valued_positions,
            "unpriced_today": overview.unpriced,
            "currencies_without_rate": overview.currencies_without_rate,
            "restricted_value_rub": s.amount(overview.restricted_value),
            "as_of": s.day(overview.as_of), "fx_as_of": s.day(overview.fx_as_of),
        },
        "history": {
            "snapshots": len(snapshots), "days_fully_valued": full_days,
            "share_fully_valued": (s.rate(Decimal(full_days) / len(snapshots)) if snapshots else None),
            "first_date": s.day(snapshots[0].on_date) if snapshots else None,
            "last_date": s.day(last.on_date) if last else None,
            "last_source": last.source if last else None,
            "instruments_without_price": [{"name": name, "days": days}
                                          for name, days in without_price.most_common()],
            "note": ("Дни с неполной оценкой рвут цепочку TWR: доходность по времени измерена только "
                     "на полных днях (см. returns.twr_coverage). XIRR от этого не зависит."),
        },
        "blocked": {"holdings": blocked_holdings, "cash": blocked_cash},
        "sync": {"last_runs": last_runs},
        "broker_total_check": VALUATION_CHECK_NOTE,
    }
