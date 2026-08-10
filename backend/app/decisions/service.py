"""Решения владельца по расхождениям журнала со снимком брокера.

Решение хранится в ledger_decision и **порождает** записи журнала — движок
позиций по-прежнему читает ровно один вход. Отмена ничего не удаляет: журнал
append-only, поэтому создаётся зеркальное решение с reverts_id.
"""

import hashlib
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    DECISION_PAYLOAD_KEY,
    Account,
    LedgerDecision,
    OperationType,
    Transaction,
)
from app.models.ledger_decision import DecisionKind, DecisionStatus
from app.money import money, quantity as q
from app.positions.service import rebuild_positions
from app.sync.reconcile import reconcile_from_snapshot

SOURCE = "manual"


class DecisionError(ValueError):
    """Решение не описывает того, что обещает его вид."""


def _validate(decision: LedgerDecision) -> None:
    if not (decision.note or "").strip():
        raise DecisionError("Пояснение обязательно: через год причину решения не восстановит никто.")

    has_from = decision.from_instrument_id is not None and decision.from_quantity is not None
    has_to = decision.to_instrument_id is not None and decision.to_quantity is not None

    if decision.kind is DecisionKind.CONVERSION and not (has_from and has_to):
        raise DecisionError(
            "Конвертация описывается обеими сторонами: из какой бумаги и в какую, "
            "с количествами."
        )
    if decision.kind is DecisionKind.ADJUSTMENT and has_from == has_to:
        raise DecisionError(
            "Корректировка описывает ровно одну сторону: либо списание, либо зачисление."
        )
    if decision.kind is DecisionKind.ACCEPTED_AS_IS and (has_from or has_to):
        raise DecisionError(
            "«Принято как есть» ничего не двигает — бумаги и количества у такого "
            "решения быть не должно."
        )

    _validate_quantities(decision, has_from=has_from, has_to=has_to)


def _validate_quantities(decision: LedgerDecision, *, has_from: bool, has_to: bool) -> None:
    """Количество у любой описанной стороны — строго больше нуля.

    Проверять это обязано решение, а не движок. Нулевая конвертация доходила до
    движка и падала там с чужим текстом («CONVERSION_IN не нашёл снятых
    партий»), уводящим от настоящей причины, а нулевое количество на
    зачисляющей стороне не падало вовсе: снятые партии раскладывались на ноль
    бумаг, себестоимость исчезала, и позиция при этом оставалась помеченной как
    «себестоимость известна».

    Списывающая сторона задаётся положительным количеством: минус ставит сама
    служба при порождении записи журнала (см. _generate_entries), а
    отрицательное значение от владельца сработало бы в обратную сторону.
    """
    sides = []
    if has_from:
        sides.append(decision.from_quantity)
    if has_to:
        sides.append(decision.to_quantity)

    if any(value <= Decimal("0") for value in sides):
        raise DecisionError(
            "Количество в решении задаётся строго больше нуля: нулевое ничего не "
            "переносит, а знак списания служба проставляет сама."
        )


def _dedup_key(decision_id: int, leg: str) -> str:
    return hashlib.sha256(f"{SOURCE}|{decision_id}|{leg}".encode()).hexdigest()


def _entry(
    decision: LedgerDecision, leg: str, op_type: OperationType,
    instrument_id: int, quantity, price,
) -> Transaction:
    return Transaction(
        account_id=decision.account_id,
        instrument_id=instrument_id,
        op_type=op_type,
        executed_at=decision.effective_at,
        quantity=q(quantity),
        price=money(price),
        amount=money("0"),
        currency="RUB",
        fee=money("0"),
        external_id=f"decision:{decision.id}:{leg}",
        source=SOURCE,
        dedup_key=_dedup_key(decision.id, leg),
        # decision_id связывает две стороны конвертации: движок достаёт его в
        # LedgerEntry.link_id (app/positions/service.py).
        payload={DECISION_PAYLOAD_KEY: decision.id},
    )


def _generate_entries(session: Session, decision: LedgerDecision) -> None:
    """Записи журнала, порождённые подтверждённым решением.

    Отклонённое решение и «принято как есть» не порождают ничего: первое —
    потому что владелец сказал «нет», второе — потому что расхождение
    остаётся, оно лишь объяснено.
    """
    if decision.status is not DecisionStatus.CONFIRMED:
        return

    if decision.kind is DecisionKind.CONVERSION:
        session.add(_entry(decision, "out", OperationType.CONVERSION_OUT,
                           decision.from_instrument_id, decision.from_quantity, "0"))
        session.add(_entry(decision, "in", OperationType.CONVERSION_IN,
                           decision.to_instrument_id, decision.to_quantity, "0"))
    elif decision.kind is DecisionKind.ADJUSTMENT:
        if decision.to_instrument_id is not None:
            # Себестоимость известна — цена на бумагу; нет — ноль, и партия
            # пометится неизвестной (WITHOUT_COST в движке этого не сделает,
            # поэтому цена ноль здесь означает ровно «неизвестно»).
            price = (money(decision.cost_basis / decision.to_quantity)
                     if decision.cost_basis is not None and decision.to_quantity
                     else money("0"))
            session.add(_entry(decision, "in", OperationType.ADJUSTMENT,
                               decision.to_instrument_id, decision.to_quantity, price))
        else:
            session.add(_entry(decision, "out", OperationType.ADJUSTMENT,
                               decision.from_instrument_id, -decision.from_quantity, "0"))

    session.flush()


def rebuild_after_decision(session: Session, account: Account) -> None:
    """Пересобирает позиции и сверку счёта после изменения журнала."""
    rebuild_positions(session, account)
    reconcile_from_snapshot(session, account)


def record_decision(session: Session, decision: LedgerDecision) -> LedgerDecision:
    _validate(decision)
    session.add(decision)
    session.flush()

    _generate_entries(session, decision)
    rebuild_after_decision(session, session.get(Account, decision.account_id))
    return decision


def revert_decision(session: Session, decision_id: int, note: str) -> LedgerDecision:
    """Отменяет решение зеркальным.

    Ни решение, ни порождённые им записи не удаляются: журнал append-only, и
    правка задним числом стёрла бы след того, что владелец однажды решил иначе.
    """
    original = session.get(LedgerDecision, decision_id)
    if original is None:
        raise DecisionError(f"Решение {decision_id} не найдено.")
    if original.status is not DecisionStatus.CONFIRMED:
        raise DecisionError(
            f"Отменить можно только подтверждённое решение, а это — "
            f"{original.status.value}."
        )

    mirror = LedgerDecision(
        account_id=original.account_id,
        kind=original.kind,
        status=DecisionStatus.CONFIRMED,
        # Стороны меняются местами: то, что было зачислено, списывается.
        from_instrument_id=original.to_instrument_id,
        from_quantity=original.to_quantity,
        to_instrument_id=original.from_instrument_id,
        to_quantity=original.from_quantity,
        cost_basis=original.cost_basis,
        effective_at=original.effective_at,
        note=note,
        proposed={"reverts": original.id},
        reverts_id=original.id,
    )
    _validate(mirror)
    session.add(mirror)
    session.flush()

    _generate_entries(session, mirror)
    original.status = DecisionStatus.REVERTED
    session.flush()

    rebuild_after_decision(session, session.get(Account, original.account_id))
    return mirror


def decisions_for(session: Session, account_id: int | None = None) -> list[LedgerDecision]:
    statement = select(LedgerDecision).order_by(LedgerDecision.created_at.desc())
    if account_id is not None:
        statement = statement.where(LedgerDecision.account_id == account_id)
    return list(session.execute(statement).scalars())
