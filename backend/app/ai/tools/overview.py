"""Инструмент portfolio_overview: сколько всего, по счетам, деньги, что
недоступно, на какую дату, когда синхронизировано."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cash import all_balances
from app.ai import serialize as s
from app.analytics.service import portfolio_overview as overview_of
from app.models import Account, SyncRun


def last_sync(session: Session) -> dict | None:
    """Последний завершившийся прогон синхронизации любого счёта. Успешный и
    неуспешный различаются статусом — модель обязана видеть оба."""
    run = session.execute(
        select(SyncRun).where(SyncRun.finished_at.is_not(None))
        .order_by(SyncRun.finished_at.desc()).limit(1)
    ).scalars().first()
    if run is None:
        return None
    return {"finished_at": s.moment(run.finished_at), "status": run.status,
            "inserted": run.inserted, "mismatches": run.mismatches, "error": run.error}


def portfolio_overview(session: Session) -> dict:
    overview = overview_of(session)
    accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
    cash_rows = all_balances(session)

    # Счета — объединение разбивки обзора и денежных строк: счёт, у чьих
    # денег нет курса, в обзор не попал, но исчезать не должен.
    account_ids_in_overview = set(overview.by_account.keys())
    account_ids_in_cash = {row.account_id for row in cash_rows}
    all_account_ids = sorted(account_ids_in_overview | account_ids_in_cash)

    by_account = []
    for account_id in all_account_ids:
        account = accounts.get(account_id)
        if account is None:
            continue
        value = overview.by_account.get(account_id)
        by_account.append({
            **s.account_ref(account),
            "value_rub": s.amount(value),
            "cash": [{"currency": row.currency, "amount": s.amount(row.amount),
                      "blocked": s.amount(row.blocked)}
                     for row in cash_rows if row.account_id == account_id],
        })

    cash_by_currency: dict[str, Decimal] = {}
    for row in cash_rows:
        cash_by_currency[row.currency] = cash_by_currency.get(row.currency, Decimal("0")) + row.amount

    total = overview.total_value
    return {
        "as_of": s.day(overview.as_of),
        "fx_as_of": s.day(overview.fx_as_of),
        "total_value_rub": s.amount(total),
        "securities_value_rub": s.amount(overview.securities_value),
        "cash_value_rub": s.amount(overview.cash_value),
        "restricted_value_rub": s.amount(overview.restricted_value),
        "by_account": by_account,
        "by_asset_class": [
            {"asset_class": klass, "value_rub": s.amount(value),
             "share": s.rate(value / total) if total else None}
            for klass, value in overview.by_asset_class.items()
        ],
        "cash_by_currency": [{"currency": currency, "amount": s.amount(value)}
                             for currency, value in sorted(cash_by_currency.items())],
        "coverage": {
            "positions_total": overview.positions_total,
            "valued_positions": overview.valued_positions,
            "unpriced": overview.unpriced,
            "currencies_without_rate": overview.currencies_without_rate,
        },
        "last_sync": last_sync(session),
        "note": ("Суммы в рублях по курсам на fx_as_of; неоценённые позиции в итог не входят "
                 "и названы в coverage.unpriced. restricted_value_rub входит в итог, а не "
                 "вычитается из него."),
    }
