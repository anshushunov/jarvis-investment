from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.labels import account_label
from app.api.schemas import (
    AccountReturnOut,
    AssetClassReturnOut,
    CoverageOut,
    InstrumentReturnOut,
    MetricOut,
    PeriodOut,
    ReturnsOut,
    UnattributedOut,
)
from app.db import get_session
from app.models import Account
from app.returns.service import PERIOD_12M, PERIOD_ALL, PERIOD_YTD, returns_report

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics/returns", response_model=ReturnsOut)
def get_returns(
    # Literal, а не str: неизвестный период — ошибка запроса, а не молчаливый
    # откат к «всё время». Владелец, увидевший цифру за не тот период, не узнает
    # об этом никогда.
    period: Literal[PERIOD_ALL, PERIOD_12M, PERIOD_YTD] = PERIOD_ALL,
    session: Session = Depends(get_session),
) -> ReturnsOut:
    report = returns_report(session, period)
    # Подпись счёта строится при чтении — той же единственной на проект
    # функцией, что и в четырёх соседних обработчиках.
    accounts = {
        account.id: account
        for account in session.execute(select(Account)).scalars()
    }

    return ReturnsOut(
        period=PeriodOut(
            from_date=report.period.since or report.period.until,
            to_date=report.period.until,
            annualized=report.period.annualized,
        ),
        portfolio=MetricOut(**report.portfolio.__dict__),
        coverage=CoverageOut(**report.coverage.__dict__),
        by_account=[
            AccountReturnOut(title=account_label(accounts[row.account_id]),
                             **row.metric.__dict__)
            for row in report.by_account
            if row.account_id in accounts
        ],
        by_asset_class=[
            AssetClassReturnOut(asset_class=row.asset_class, **row.metric.__dict__)
            for row in report.by_asset_class
        ],
        by_instrument=[
            InstrumentReturnOut(
                ticker=row.ticker, name=row.name, xirr=row.xirr, profit=row.profit,
                value=row.value, closed=row.closed, price_part=row.price_part,
                fx_part=row.fx_part, reason=row.reason,
            )
            for row in report.by_instrument
        ],
        unattributed=UnattributedOut(**report.unattributed.__dict__),
    )
