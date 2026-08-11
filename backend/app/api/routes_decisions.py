"""REST-контур решений владельца по расхождениям.

Счёт и бумаги приходят подписями и ISIN, а не идентификаторами: интерфейс видит
именно их, и заставлять его знать внутренние ключи незачем.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.labels import account_label
from app.api.schemas import DecisionIn, DecisionOut, RevertIn
from app.db import get_session
from app.decisions.service import DecisionError, decisions_for, record_decision, revert_decision
from app.models import Account, Instrument, LedgerDecision
from app.models.ledger_decision import DecisionKind, DecisionStatus

router = APIRouter(prefix="/api", tags=["decisions"])


def _account_by_label(session: Session, label: str) -> Account:
    for account in session.execute(select(Account)).scalars():
        if account_label(account) == label:
            return account
    raise HTTPException(status_code=404, detail=f"Счёт «{label}» не найден")


def _instrument_id(session: Session, isin: str | None) -> int | None:
    if isin is None:
        return None
    instrument = session.execute(
        select(Instrument).where(Instrument.isin == isin)
    ).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Бумага {isin} не найдена в справочнике. Она попадёт туда после "
                "ближайшей синхронизации — снимок брокера заводит бумаги, "
                "которых нет в журнале."
            ),
        )
    return instrument.id


def _isin(session: Session, instrument_id: int | None) -> str | None:
    if instrument_id is None:
        return None
    return session.get(Instrument, instrument_id).isin


def _to_out(session: Session, decision: LedgerDecision) -> DecisionOut:
    return DecisionOut(
        id=decision.id,
        account=account_label(session.get(Account, decision.account_id)),
        kind=decision.kind.value,
        status=decision.status.value,
        from_isin=_isin(session, decision.from_instrument_id),
        from_quantity=decision.from_quantity,
        to_isin=_isin(session, decision.to_instrument_id),
        to_quantity=decision.to_quantity,
        effective_at=decision.effective_at,
        note=decision.note,
        reverts_id=decision.reverts_id,
    )


@router.get("/decisions", response_model=list[DecisionOut])
def list_decisions(session: Session = Depends(get_session)) -> list[DecisionOut]:
    decisions = decisions_for(session)

    # Тот же приём, что и в get_reconciliations (routes_portfolio.py): счета и
    # бумаги подгружаются одним запросом на весь список, а не по одному на
    # каждое решение — иначе список решений даёт N+1 обращений к базе.
    accounts = {
        account.id: account
        for account in session.execute(
            select(Account).where(Account.id.in_({d.account_id for d in decisions}))
        ).scalars()
    }
    instrument_ids = {
        instrument_id
        for decision in decisions
        for instrument_id in (decision.from_instrument_id, decision.to_instrument_id)
        if instrument_id is not None
    }
    isins = {
        instrument.id: instrument.isin
        for instrument in session.execute(
            select(Instrument).where(Instrument.id.in_(instrument_ids))
        ).scalars()
    }

    return [
        DecisionOut(
            id=decision.id,
            account=account_label(accounts[decision.account_id]),
            kind=decision.kind.value,
            status=decision.status.value,
            from_isin=isins.get(decision.from_instrument_id),
            from_quantity=decision.from_quantity,
            to_isin=isins.get(decision.to_instrument_id),
            to_quantity=decision.to_quantity,
            effective_at=decision.effective_at,
            note=decision.note,
            reverts_id=decision.reverts_id,
        )
        for decision in decisions
    ]


@router.post("/decisions", response_model=DecisionOut)
def create_decision(payload: DecisionIn, session: Session = Depends(get_session)) -> DecisionOut:
    account = _account_by_label(session, payload.account)
    try:
        decision = record_decision(session, LedgerDecision(
            account_id=account.id,
            kind=DecisionKind(payload.kind),
            status=DecisionStatus(payload.status),
            from_instrument_id=_instrument_id(session, payload.from_isin),
            from_quantity=payload.from_quantity,
            to_instrument_id=_instrument_id(session, payload.to_isin),
            to_quantity=payload.to_quantity,
            cost_basis=payload.cost_basis,
            effective_at=payload.effective_at,
            note=payload.note,
            proposed={},
        ))
    except DecisionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ValueError as error:
        # Неизвестный kind или status: DecisionKind(...) поднимает ValueError.
        raise HTTPException(status_code=400, detail=f"Неизвестное значение: {error}") from error

    session.commit()
    return _to_out(session, decision)


@router.post("/decisions/{decision_id}/revert", response_model=DecisionOut)
def revert(decision_id: int, payload: RevertIn,
           session: Session = Depends(get_session)) -> DecisionOut:
    try:
        mirror = revert_decision(session, decision_id, note=payload.note)
    except DecisionError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    session.commit()
    return _to_out(session, mirror)
