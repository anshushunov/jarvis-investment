from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cash import all_balances
from app.accounts.labels import account_label, account_label_by_id
from app.analytics.service import portfolio_overview, position_rows
from app.api.schemas import (
    CashOut,
    HistoryPointOut,
    OverviewOut,
    PositionOut,
    ReconciliationOut,
    SuggestionOut,
)
from app.db import get_session
from app.decisions.suggestions import suggestions_for_account
from app.models import Account, DailySnapshot, Reconciliation
from app.snapshots.service import snapshot_by_account
from app.timeutils import moscow_today

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio/overview", response_model=OverviewOut)
def get_overview(session: Session = Depends(get_session)) -> OverviewOut:
    overview = portfolio_overview(session)
    # Аналитика ключует разбивку по счетам их идентификаторами; подпись
    # строится здесь, при чтении, единственной на проект функцией — той же,
    # что подписывает счета в расхождениях и в результатах синхронизации.
    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.id.in_(overview.by_account))
        ).scalars()
    }
    return OverviewOut(
        total_value=overview.total_value,
        securities_value=overview.securities_value,
        cash_value=overview.cash_value,
        restricted_value=overview.restricted_value,
        by_asset_class=overview.by_asset_class,
        by_account={
            account_label(accounts[account_id]): value
            for account_id, value in overview.by_account.items()
        },
        by_currency=overview.by_currency,
        position_currencies=overview.position_currencies,
        currencies_without_rate=overview.currencies_without_rate,
        as_of=overview.as_of,
        fx_as_of=overview.fx_as_of,
        valued_positions=overview.valued_positions,
        positions_total=overview.positions_total,
    )


@router.get("/portfolio/positions", response_model=list[PositionOut])
def get_positions(session: Session = Depends(get_session)) -> list[PositionOut]:
    rows = position_rows(session)
    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.id.in_({row.account_id for row in rows}))
        ).scalars()
    }
    return [
        PositionOut(
            **{key: value for key, value in row.__dict__.items() if key != "account_id"},
            account=account_label(accounts[row.account_id]),
        )
        for row in rows
    ]


@router.get("/portfolio/cash", response_model=list[CashOut])
def get_cash(session: Session = Depends(get_session)) -> list[CashOut]:
    balances = all_balances(session)
    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.id.in_({b.account_id for b in balances}))
        ).scalars()
    }
    return [
        CashOut(
            account=account_label(accounts[balance.account_id]),
            currency=balance.currency,
            amount=balance.amount,
            blocked=balance.blocked,
        )
        for balance in balances
    ]


@router.get("/portfolio/history", response_model=list[HistoryPointOut])
def get_history(days: int = 90, session: Session = Depends(get_session)) -> list[HistoryPointOut]:
    # Дата берётся в московском поясе явно: снимки пишутся под московской
    # календарной датой (см. app/timeutils.py), и окно истории обязано
    # отсчитываться от той же, а не от даты по поясу контейнера.
    since = moscow_today() - timedelta(days=days)
    rows = session.execute(
        select(DailySnapshot).where(DailySnapshot.on_date >= since).order_by(DailySnapshot.on_date)
    ).scalars().all()
    # Счета выбираются один раз на весь ответ, а не на точку истории: снимок
    # снимается раз в сутки, и запрос без фильтра внутри цикла по строкам (как
    # было раньше — см. snapshot_by_account) превращал бы один обход окна в
    # 1 + N запросов. Тот же приём, что и у соседей выше (get_overview,
    # get_positions, get_cash).
    account_ids = {
        int(key)
        for row in rows
        for key in (row.by_account or {})
        if key.lstrip("-").isdigit()
    }
    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.id.in_(account_ids))
        ).scalars()
    }
    return [
        HistoryPointOut(
            date=row.on_date,
            total_value=row.total_value,
            by_account=snapshot_by_account(accounts, row),
        )
        for row in rows
    ]


@router.get("/reconciliations", response_model=list[ReconciliationOut])
def get_reconciliations(session: Session = Depends(get_session)) -> list[ReconciliationOut]:
    rows = session.execute(select(Reconciliation).order_by(Reconciliation.isin)).scalars().all()
    # Гипотезы считаются по счёту целиком: пара ищется среди расхождений
    # одного счёта, поэтому кэшируем результат на счёт, а не запрашиваем его
    # для каждой строки.
    by_account: dict[int, dict[str, list]] = {}
    for account_id in {row.account_id for row in rows}:
        by_account[account_id] = suggestions_for_account(session, account_id)

    return [
        ReconciliationOut(
            isin=row.isin, status=row.status,
            ledger_quantity=row.ledger_quantity, broker_quantity=row.broker_quantity,
            # Сверка считается по каждому счёту отдельно — один и тот же ISIN
            # может дать две строки на двух разных счетах, неразличимые без
            # подписи счёта (проверено на живых данных владельца).
            account=account_label_by_id(session, row.account_id),
            suggestions=[
                SuggestionOut(**suggestion.__dict__)
                for suggestion in by_account[row.account_id].get(row.isin, [])
            ],
        )
        for row in rows
    ]
