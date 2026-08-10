"""Решения владельца по расхождениям: хранение и целостность.

Хранятся только принятые решения. Гипотезы в базу не пишутся — они
пересчитываются из сверки (app/decisions/suggestions.py); в таблице они
оставляют след только тогда, когда владелец их отклонил, и этот след глушит
повторный показ.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Account, Instrument, LedgerDecision
from app.models.ledger_decision import DecisionKind, DecisionStatus


def _account(session) -> Account:
    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    return account


def _instrument(session, isin: str) -> Instrument:
    instrument = Instrument(isin=isin, ticker=isin[:4], secid=isin[:4],
                            kind="share", currency="RUB")
    session.add(instrument)
    session.flush()
    return instrument


def test_conversion_decision_round_trip(session):
    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    decision = LedgerDecision(
        account_id=account.id,
        kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация гонконгского ETF, обе стороны заблокированы целиком",
        proposed={"reason": "равные количества", "blocked_fully": True},
    )
    session.add(decision)
    session.flush()
    session.expire_all()

    loaded = session.get(LedgerDecision, decision.id)
    assert loaded.kind is DecisionKind.CONVERSION
    assert loaded.status is DecisionStatus.CONFIRMED
    assert loaded.to_quantity == Decimal("79")
    assert loaded.proposed["blocked_fully"] is True


def test_note_is_required(session):
    account = _account(session)

    session.add(LedgerDecision(
        account_id=account.id,
        kind=DecisionKind.ACCEPTED_AS_IS,
        status=DecisionStatus.CONFIRMED,
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note=None,
        proposed={},
    ))

    with pytest.raises(IntegrityError):
        session.flush()


def test_decision_can_point_at_the_one_it_reverts(session):
    account = _account(session)
    original = LedgerDecision(
        account_id=account.id, kind=DecisionKind.ACCEPTED_AS_IS,
        status=DecisionStatus.REVERTED,
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Первое решение", proposed={},
    )
    session.add(original)
    session.flush()

    revert = LedgerDecision(
        account_id=account.id, kind=DecisionKind.ACCEPTED_AS_IS,
        status=DecisionStatus.CONFIRMED,
        effective_at=datetime(2026, 3, 2, tzinfo=timezone.utc),
        note="Передумал", proposed={}, reverts_id=original.id,
    )
    session.add(revert)
    session.flush()

    assert session.get(LedgerDecision, revert.id).reverts_id == original.id
