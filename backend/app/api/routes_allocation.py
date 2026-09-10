"""Целевые доли: чтение и запись набора целиком.

Отклонения от целей на экраны фаза не выводит (дизайн 5a, раздел 9) — их
считает инструмент `allocation` ассистента поверх app/allocation/service.py.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.allocation.service import AllocationError, TargetInput, list_targets, replace_targets
from app.api.schemas import TargetIn, TargetOut
from app.db import get_session
from app.models import Instrument, TargetAllocation

router = APIRouter(prefix="/api/allocation", tags=["allocation"])


def _to_out(session: Session, rows: list[TargetAllocation]) -> list[TargetOut]:
    # Бумаги подгружаются одним запросом на весь список, как в соседних
    # обработчиках, а не по одной на строку.
    instruments = {
        instrument.id: instrument
        for instrument in session.execute(select(Instrument).where(Instrument.id.in_(
            {row.instrument_id for row in rows if row.instrument_id is not None}
        ))).scalars()
    }
    result = []
    for row in rows:
        instrument = instruments.get(row.instrument_id) if row.instrument_id is not None else None
        result.append(TargetOut(
            asset_class=row.asset_class,
            isin=instrument.isin if instrument else None,
            ticker=instrument.ticker if instrument else None,
            name=(instrument.issuer or instrument.ticker or instrument.isin) if instrument else None,
            share=row.share,
            updated_at=row.updated_at,
        ))
    return result


@router.get("/targets", response_model=list[TargetOut])
def get_targets(session: Session = Depends(get_session)) -> list[TargetOut]:
    return _to_out(session, list_targets(session))


@router.put("/targets", response_model=list[TargetOut])
def put_targets(payload: list[TargetIn], session: Session = Depends(get_session)) -> list[TargetOut]:
    try:
        rows = replace_targets(session, [
            TargetInput(share=item.share, asset_class=item.asset_class, isin=item.isin)
            for item in payload
        ])
    except AllocationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    session.commit()
    return _to_out(session, rows)
