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


def test_confirmed_conversion_moves_quantity_between_instruments(session):
    """Решение владельца порождает пару записей журнала, и после пересборки
    количество переезжает из старой бумаги в новую."""
    from app.decisions.service import record_decision
    from app.ledger.service import append_operations
    from app.ledger.schemas import RawOperation
    from app.models import Position, Transaction
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    append_operations(session, account, "tbank", [RawOperation(
        external_id="1", op_type="BUY",
        executed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        isin="HK0000310034", ticker="3010", quantity=Decimal("79"),
        price=Decimal("120"), amount=Decimal("-9480"), currency="HKD",
        fee=Decimal("0"), payload={},
    )])

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация гонконгского ETF", proposed={},
    ))

    generated = session.execute(
        select(Transaction).where(Transaction.source == "manual")
        .order_by(Transaction.external_id)
    ).scalars().all()
    assert [tx.op_type.value for tx in generated] == ["CONVERSION_IN", "CONVERSION_OUT"]
    assert all(tx.payload["decision_id"] == decision.id for tx in generated)

    positions = {
        p.instrument_id: p.quantity
        for p in session.execute(select(Position)).scalars()
    }
    assert positions == {new.id: Decimal("79")}


def test_adjustment_decision_changes_quantity_by_the_difference(session):
    from app.decisions.service import record_decision
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        to_instrument_id=instrument.id, to_quantity=Decimal("1012"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Редомициляция ТКС: расписки заменены акциями по отчёту брокера",
        proposed={},
    ))

    position = session.execute(select(Position)).scalar_one()
    assert position.quantity == Decimal("1012")
    # Себестоимость владелец не указал — позиция помечена.
    assert position.cost_basis_known is False


def test_rejected_decision_generates_no_ledger_entries(session):
    from app.decisions.service import record_decision
    from app.models import Transaction
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.REJECTED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Это не конвертация, бумаги не связаны", proposed={},
    ))

    assert session.execute(select(Transaction)).scalars().all() == []


def test_revert_returns_positions_to_the_previous_state(session):
    from app.decisions.service import record_decision, revert_decision
    from app.ledger.service import append_operations
    from app.ledger.schemas import RawOperation
    from app.models import Position
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    append_operations(session, account, "tbank", [RawOperation(
        external_id="1", op_type="BUY",
        executed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        isin="HK0000310034", ticker="3010", quantity=Decimal("79"),
        price=Decimal("120"), amount=Decimal("-9480"), currency="HKD",
        fee=Decimal("0"), payload={},
    )])

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.CONVERSION,
        status=DecisionStatus.CONFIRMED,
        from_instrument_id=old.id, from_quantity=Decimal("79"),
        to_instrument_id=new.id, to_quantity=Decimal("79"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Конвертация", proposed={},
    ))

    revert_decision(session, decision.id, note="Ошибся бумагой")

    assert session.get(LedgerDecision, decision.id).status is DecisionStatus.REVERTED
    positions = {
        p.instrument_id: p.quantity
        for p in session.execute(select(Position)).scalars()
    }
    assert positions == {old.id: Decimal("79")}


@pytest.mark.parametrize("from_quantity, to_quantity", [
    (Decimal("79"), Decimal("0")),
    (Decimal("0"), Decimal("79")),
    (Decimal("79"), Decimal("-79")),
])
def test_conversion_with_non_positive_quantity_is_refused(session, from_quantity, to_quantity):
    """Нулевая и отрицательная конвертация отклоняются в службе решений.

    Дальше по дороге такое решение падало с чужим текстом («CONVERSION_IN не
    нашёл снятых партий»), а нулевое количество на зачисляющей стороне не
    падало вовсе: движок раскладывал снятые партии на ноль бумаг, себестоимость
    исчезала, а признак «себестоимость известна» оставался истинным.
    """
    from app.decisions.service import DecisionError, record_decision
    from app.models import Transaction
    from sqlalchemy import select

    account = _account(session)
    old = _instrument(session, "HK0000310034")
    new = _instrument(session, "HK0000051877")

    with pytest.raises(DecisionError, match="строго больше нуля"):
        record_decision(session, LedgerDecision(
            account_id=account.id, kind=DecisionKind.CONVERSION,
            status=DecisionStatus.CONFIRMED,
            from_instrument_id=old.id, from_quantity=from_quantity,
            to_instrument_id=new.id, to_quantity=to_quantity,
            effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            note="Конвертация с негодным количеством", proposed={},
        ))

    assert session.execute(select(Transaction)).scalars().all() == []


def test_adjustment_write_off_is_given_as_a_positive_quantity(session):
    """Списывающая поправка задаётся положительным количеством.

    Минус ставит сама служба при порождении записи журнала. Отрицательное
    значение от владельца означало бы двойное отрицание — поправка сработала бы
    в обратную сторону.
    """
    from app.decisions.service import DecisionError, record_decision

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    with pytest.raises(DecisionError, match="строго больше нуля"):
        record_decision(session, LedgerDecision(
            account_id=account.id, kind=DecisionKind.ADJUSTMENT,
            status=DecisionStatus.CONFIRMED,
            from_instrument_id=instrument.id, from_quantity=Decimal("-5"),
            effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
            note="Лишние бумаги в журнале", proposed={},
        ))


def test_generated_entry_is_read_back_through_the_shared_payload_key(session):
    """Ключ payload у службы решений и у сборщика позиций общий.

    Разъедься они при переименовании — конвертация упала бы с «нет link_id»,
    и текст ошибки увёл бы от настоящей причины.
    """
    from app.decisions.service import record_decision
    from app.models.ledger_decision import DECISION_PAYLOAD_KEY
    from app.positions.service import _entries

    account = _account(session)
    instrument = _instrument(session, "RU000A107UL4")

    decision = record_decision(session, LedgerDecision(
        account_id=account.id, kind=DecisionKind.ADJUSTMENT,
        status=DecisionStatus.CONFIRMED,
        to_instrument_id=instrument.id, to_quantity=Decimal("1012"),
        effective_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
        note="Редомициляция ТКС", proposed={},
    ))

    generated = _entries(session, account)
    assert [entry.link_id for entry in generated] == [decision.id]
    assert DECISION_PAYLOAD_KEY == "decision_id"


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
