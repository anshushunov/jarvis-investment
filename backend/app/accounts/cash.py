from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerCash
from app.models import Account, CashBalance


def store_cash(session: Session, account: Account, balances: list[BrokerCash]) -> int:
    """Заменяет остатки счёта присланными брокером.

    Именно заменяет, а не дополняет: остаток — снимок на момент времени.
    Валюта, которой у брокера больше нет, должна исчезнуть, иначе проданные
    доллары вечно висят в капитале. Удаление и вставка идут в транзакции
    вызывающего — как и пересборка позиций, чтобы читатель никогда не увидел
    счёт без денег в середине обновления.
    """
    session.execute(delete(CashBalance).where(CashBalance.account_id == account.id))

    for item in balances:
        session.add(CashBalance(
            account_id=account.id,
            currency=item.currency,
            amount=item.amount,
            blocked=item.blocked,
        ))

    session.flush()
    return len(balances)


def cash_by_account(session: Session) -> dict[int, dict[str, Decimal]]:
    """Остатки всех счетов: идентификатор счёта → валюта → сумма."""
    result: dict[int, dict[str, Decimal]] = {}
    for balance in session.execute(select(CashBalance)).scalars():
        result.setdefault(balance.account_id, {})[balance.currency] = balance.amount
    return result
