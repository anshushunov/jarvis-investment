"""Решения владельца по расхождениям журнала со снимком брокера.

Решение хранится в ledger_decision и **порождает** записи журнала — движок
позиций по-прежнему читает ровно один вход. Отмена ничего не удаляет: журнал
append-only, поэтому создаётся зеркальное решение с reverts_id.
"""

import hashlib
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    DECISION_PAYLOAD_KEY,
    DECISION_REVERTS_PAYLOAD_KEY,
    Account,
    LedgerDecision,
    OperationType,
    Transaction,
)
from app.models.ledger_decision import DecisionKind, DecisionStatus
from app.money import money, quantity as q
from app.positions.engine import ConversionError, ReversalError
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


def _payload(decision: LedgerDecision) -> dict:
    """Связи порождённой записи: со своим решением и с отменяемым.

    У записи отмены количество и цена описательные — книгу партий движок
    восстанавливает по следу отменяемого решения, а не по ним (см.
    app/positions/engine.py, _revert_decision). Себестоимость съеденной партии
    здесь и не вычислить: какие именно партии закрыло списание, знает только
    FIFO внутри движка.
    """
    payload = {DECISION_PAYLOAD_KEY: decision.id}
    if decision.reverts_id is not None:
        payload[DECISION_REVERTS_PAYLOAD_KEY] = decision.reverts_id
    return payload


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
        payload=_payload(decision),
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

    # Всё под общим SAVEPOINT: движок отказывает уже после того, как решение и
    # порождённые им записи легли в сессию, и без отката вызывающий закоммитил
    # бы журнал, который потом не сворачивается. Чинить такое пришлось бы
    # правкой базы — журнал append-only.
    try:
        with session.begin_nested():
            session.add(decision)
            session.flush()
            _generate_entries(session, decision)
            rebuild_after_decision(session, session.get(Account, decision.account_id))
    except (ConversionError, ReversalError) as error:
        raise DecisionError(
            f"Решение не сходится с журналом операций: {error} Ни решение, ни "
            "записи журнала не сохранены."
        ) from error
    return decision


def _blocking_decisions(session: Session, original: LedgerDecision) -> list[LedgerDecision]:
    """Более поздние решения того же счёта, мешающие отменить это.

    Отмена раскручивает след решения — те самые партии, которые оно открыло.
    Если поверх легло ещё одно решение, этих партий в книге уже нет: они ушли в
    следующую конвертацию. Отказ обязан назвать настоящую причину, иначе
    владелец читает про «количество в решении» (так падал движок) и правит не
    то.

    «Позже» — по паре (время создания, номер): номер один растёт вместе с
    порядком принятия решений только пока их создаёт эта служба, а время
    создания переживает и импорт.

    Пара «решение и его отмена» друг друга гасит и мешать не должна — иначе
    первое решение оказывается неотменяемым навсегда. Исключение — решение,
    чей CONVERSION_OUT черпал ту самую бумагу, которую зачислило отменяемое:
    эта запись осталась в журнале на своей, более поздней дате и по-прежнему
    требует бумаги в книге. Сами зеркальные записи ничего не черпают — они
    раскручивают чужой след, — поэтому зеркала из проверки исключены всегда.
    """
    instruments = {original.from_instrument_id, original.to_instrument_id} - {None}
    if not instruments:
        return []

    statement = (
        select(LedgerDecision)
        .where(
            LedgerDecision.account_id == original.account_id,
            LedgerDecision.id != original.id,
            or_(
                LedgerDecision.created_at > original.created_at,
                and_(
                    LedgerDecision.created_at == original.created_at,
                    LedgerDecision.id > original.id,
                ),
            ),
            or_(
                LedgerDecision.from_instrument_id.in_(instruments),
                LedgerDecision.to_instrument_id.in_(instruments),
            ),
        )
        .order_by(LedgerDecision.created_at, LedgerDecision.id)
    )
    later = list(session.execute(statement).scalars())
    reverted = {item.id for item in later if item.status is DecisionStatus.REVERTED}

    blocking = []
    for decision in later:
        # Отклонённое решение записей журнала не порождало — мешать нечему.
        if decision.status is DecisionStatus.REJECTED:
            continue
        cancelled = decision.status is DecisionStatus.REVERTED or decision.reverts_id in reverted
        if cancelled and (
            decision.reverts_id is not None
            or decision.from_instrument_id != original.to_instrument_id
        ):
            continue
        blocking.append(decision)
    return blocking


def _operations_after(session: Session, original: LedgerDecision) -> list[Transaction]:
    """Операции брокера по зачисленной решением бумаге после даты события.

    Отмена убирает партии, которые решение открыло. Если после этой даты бумагу
    успели продать, история становится противоречивой: по отменённой версии
    событий этих бумаг не существовало вовсе. Промолчать нельзя, и упасть уже
    некуда — движок такого не заметит: зеркальные записи несут дату отменяемого
    решения и ложатся в журнал раньше позднейшей продажи. На живом разборе
    выходило, что реальная продажа 40 бумаг на 8000 исчезала из налоговой базы,
    а в портфеле оставалась короткая позиция, которой нет у брокера.

    Записи, порождённые решениями, здесь не считаются: их разбирает
    _blocking_decisions, а погасившая себя пара «решение и его отмена» следа в
    книге не оставляет.

    Бумага, с которой решение только списывало, не проверяется: возврат снятых
    партий ни с чем не спорит — они просто ложатся обратно в книгу, а всё, что
    случилось позже, считается поверх них как считалось.
    """
    if original.to_instrument_id is None:
        return []

    statement = (
        select(Transaction)
        .where(
            Transaction.account_id == original.account_id,
            Transaction.instrument_id == original.to_instrument_id,
            Transaction.executed_at > original.effective_at,
            Transaction.source != SOURCE,
        )
        .order_by(Transaction.executed_at)
    )
    return list(session.execute(statement).scalars())


def revert_decision(session: Session, decision_id: int, note: str) -> LedgerDecision:
    """Отменяет решение зеркальным.

    Ни решение, ни порождённые им записи не удаляются: журнал append-only, и
    правка задним числом стёрла бы след того, что владелец однажды решил иначе.

    Зеркальные записи несут ссылку на отменяемое решение, и движок по ней
    возвращает книгу партий ровно к прежнему виду: снимает те самые партии,
    которые решение открыло, и возвращает те самые, которые оно сняло, — с их
    датами открытия, ценами и признаком известной себестоимости.
    """
    original = session.get(LedgerDecision, decision_id)
    if original is None:
        raise DecisionError(f"Решение {decision_id} не найдено.")
    if original.status is not DecisionStatus.CONFIRMED:
        raise DecisionError(
            f"Отменить можно только подтверждённое решение, а это — "
            f"{original.status.value}."
        )

    if original.reverts_id is not None:
        raise DecisionError(
            f"Решение {original.id} само отменяет решение {original.reverts_id}: "
            "отменять отмену нельзя — своего следа в книге партий она не "
            "оставляет, и раскручивать было бы нечего. Запишите вместо этого "
            "новое решение."
        )

    blocking = _blocking_decisions(session, original)
    if blocking:
        numbers = ", ".join(str(decision.id) for decision in blocking)
        raise DecisionError(
            f"Поверх решения {original.id} лежат более поздние решения по тем же "
            f"бумагам ({numbers}): они опираются на бумаги, которые оно "
            "зачислило, и отмена вырвала бы у них опору. Пока эти записи в "
            "журнале, отменить это решение нельзя — приведите позиции новым "
            "решением."
        )

    traded = _operations_after(session, original)
    if traded:
        raise DecisionError(
            f"После даты решения {original.id} по зачисленной им бумаге были "
            f"операции ({len(traded)}), самая ранняя — "
            f"{traded[0].op_type.value} от {traded[0].executed_at:%d.%m.%Y}. "
            "Отмена убрала бы бумаги, которых по её версии событий не было бы "
            "вовсе: финансовый результат этих операций исчез бы из налоговой "
            "базы, а в портфеле осталась бы короткая позиция, которой нет у "
            "брокера. Приведите позиции новым решением."
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

    # Всё под общим SAVEPOINT — по той же причине, что и в record_decision:
    # отказ движка не должен оставить в сессии зеркальное решение, две записи
    # журнала и исходное решение в статусе REVERTED. Закоммить такое вызывающий
    # получил бы счёт, позиции которого не пересобираются больше никогда.
    try:
        with session.begin_nested():
            session.add(mirror)
            session.flush()
            _generate_entries(session, mirror)
            original.status = DecisionStatus.REVERTED
            session.flush()
            rebuild_after_decision(session, session.get(Account, original.account_id))
    except (ConversionError, ReversalError) as error:
        raise DecisionError(
            f"Отмена решения {original.id} не сходится с журналом: {error} Ни "
            "зеркальное решение, ни записи журнала не сохранены."
        ) from error
    return mirror


def decisions_for(session: Session, account_id: int | None = None) -> list[LedgerDecision]:
    statement = select(LedgerDecision).order_by(LedgerDecision.created_at.desc())
    if account_id is not None:
        statement = statement.where(LedgerDecision.account_id == account_id)
    return list(session.execute(statement).scalars())
