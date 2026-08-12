from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    DECISION_PAYLOAD_KEY,
    DECISION_REVERTS_PAYLOAD_KEY,
    Account,
    Position,
    Transaction,
)
from app.positions.engine import LedgerEntry, fold


def ledger_entries(session: Session, account: Account) -> list[LedgerEntry]:
    """Записи журнала счёта в виде, понятном движку позиций.

    Публичная: тем же входом пользуется восстановление состава на прошлую дату
    (app/positions/history.py). Собирать LedgerEntry в двух местах нельзя —
    разъедется трактовка payload, и одна из сторон перестанет видеть решения
    владельца.
    """
    transactions = session.execute(
        select(Transaction).where(Transaction.account_id == account.id)
    ).scalars().all()
    return [
        LedgerEntry(
            op_type=tx.op_type,
            executed_at=tx.executed_at,
            instrument_id=tx.instrument_id,
            quantity=tx.quantity,
            price=tx.price,
            amount=tx.amount,
            fee=tx.fee,
            # Идентификатор решения владельца: связывает две стороны
            # конвертации. Лежит в payload, потому что колонка ради доли
            # процента записей журнала не окупается. Ключ — общая константа со
            # службой решений, которая его туда кладёт.
            link_id=(tx.payload or {}).get(DECISION_PAYLOAD_KEY),
            # Идентификатор отменяемого решения: по нему движок раскручивает
            # ровно те партии, которые то решение тронуло.
            reverts_link_id=(tx.payload or {}).get(DECISION_REVERTS_PAYLOAD_KEY),
            # Порядок применения решений внутри одного мгновения берётся из
            # номера строки журнала: отмена обязана лечь после отменяемого.
            row_id=tx.id,
        )
        for tx in transactions
    ]


def rebuild_positions(session: Session, account: Account) -> int:
    result = fold(ledger_entries(session, account), currency=account.currency)

    # Delete and re-insert happen inside the caller's transaction (no commit here), so
    # a crash or exception between them leaves the old rows intact under rollback —
    # readers never observe an account with zero positions mid-rebuild.
    session.execute(delete(Position).where(Position.account_id == account.id))

    kept = 0
    for instrument_id, state in result.positions.items():
        if state.quantity == 0:
            continue
        session.add(
            Position(
                account_id=account.id,
                instrument_id=instrument_id,
                quantity=state.quantity,
                average_price=state.average_price,
                cost_basis_known=state.cost_basis_known,
            )
        )
        kept += 1

    session.flush()
    return kept
