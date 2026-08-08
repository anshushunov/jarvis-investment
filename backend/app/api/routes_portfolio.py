from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.service import portfolio_overview, position_rows
from app.api.account_labels import account_label
from app.api.schemas import HistoryPointOut, OverviewOut, PositionOut, ReconciliationOut
from app.db import get_session
from app.models import DailySnapshot, Reconciliation

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio/overview", response_model=OverviewOut)
def get_overview(session: Session = Depends(get_session)) -> OverviewOut:
    overview = portfolio_overview(session)
    return OverviewOut(
        total_value=overview.total_value,
        positions_value=overview.positions_value,
        by_asset_class=overview.by_asset_class,
        by_account=overview.by_account,
        as_of=overview.as_of,
        valued_positions=overview.valued_positions,
        positions_total=overview.positions_total,
    )


@router.get("/portfolio/positions", response_model=list[PositionOut])
def get_positions(session: Session = Depends(get_session)) -> list[PositionOut]:
    return [PositionOut(**row.__dict__) for row in position_rows(session)]


@router.get("/portfolio/history", response_model=list[HistoryPointOut])
def get_history(days: int = 90, session: Session = Depends(get_session)) -> list[HistoryPointOut]:
    since = date.today() - timedelta(days=days)
    rows = session.execute(
        select(DailySnapshot).where(DailySnapshot.on_date >= since).order_by(DailySnapshot.on_date)
    ).scalars().all()
    return [HistoryPointOut(date=row.on_date, total_value=row.total_value) for row in rows]


@router.get("/reconciliations", response_model=list[ReconciliationOut])
def get_reconciliations(session: Session = Depends(get_session)) -> list[ReconciliationOut]:
    rows = session.execute(select(Reconciliation).order_by(Reconciliation.isin)).scalars().all()
    return [
        ReconciliationOut(
            isin=row.isin, status=row.status,
            ledger_quantity=row.ledger_quantity, broker_quantity=row.broker_quantity,
            # Сверка считается по каждому счёту отдельно — один и тот же ISIN
            # может дать две строки на двух разных счетах, неразличимые без
            # подписи счёта (см. отчёт задачи 15, раунд правок 1).
            account=account_label(session, row.account_id),
        )
        for row in rows
    ]
