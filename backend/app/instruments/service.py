from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ledger.schemas import RawOperation
from app.models import Instrument

KIND_BY_PREFIX = {"share": "share", "bond": "bond", "etf": "etf", "currency": "currency"}


def resolve_instrument(session: Session, op: RawOperation) -> Instrument | None:
    if op.isin is None:
        return None

    existing = session.execute(
        select(Instrument).where(Instrument.isin == op.isin)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    instrument = Instrument(
        isin=op.isin,
        ticker=op.ticker,
        secid=op.ticker,
        kind=str(op.payload.get("instrument_kind", "share")),
        currency=op.currency,
        issuer=op.payload.get("issuer"),
    )
    session.add(instrument)
    session.flush()
    return instrument
