"""Инструмент ledger: что происходило — операции плюс агрегаты по всей выборке.

Журнал — двенадцать тысяч операций. Страница ограничена, агрегаты считаются по
всей выборке, и признак усечения едет в ответе: без него модель посчитала бы
итог по первой сотне и не заметила бы подмены (дизайн, раздел 4.1).
"""

from datetime import date, datetime, time
from typing import Annotated

from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.ai.errors import ToolRefusal
from app.models import Account, Instrument, OperationType, Transaction
from app.timeutils import MOSCOW_TZ, moscow_date, moscow_day_end

MAX_LIMIT = 500
OP_TYPES_HELP = ", ".join(member.value for member in OperationType)


def ledger(
    session: Session,
    instrument_id: Annotated[int | None, Field(
        description="Только операции по этой бумаге (идентификатор из find_instrument)")] = None,
    account_id: Annotated[int | None, Field(
        description="Только этот счёт (account_id из portfolio_overview)")] = None,
    op_types: Annotated[list[str] | None, Field(
        description=f"Только эти типы операций: {OP_TYPES_HELP}")] = None,
    since: Annotated[date | None, Field(description="С даты по Москве, ГГГГ-ММ-ДД")] = None,
    until: Annotated[date | None, Field(description="По дату по Москве включительно")] = None,
    limit: Annotated[int, Field(ge=1, le=MAX_LIMIT, description=(
        "Сколько строк вернуть; агрегаты sums и date_range считаются по всей выборке"))] = 100,
    offset: Annotated[int, Field(ge=0, description="Смещение для следующей страницы")] = 0,
) -> dict:
    types: list[OperationType] = []
    for raw in op_types or []:
        try:
            types.append(OperationType(raw.upper()))
        except ValueError:
            raise ToolRefusal(f"Типа операции «{raw}» нет. Известные: {OP_TYPES_HELP}") from None
    if since is not None and until is not None and since > until:
        raise ToolRefusal(f"Начало {since} позже конца {until}")
    if instrument_id is not None and session.get(Instrument, instrument_id) is None:
        raise ToolRefusal(f"Бумаги с идентификатором {instrument_id} нет — найди её через find_instrument")
    accounts = {account.id: account for account in session.execute(select(Account)).scalars()}
    if account_id is not None and account_id not in accounts:
        known = ", ".join(f"{account.id} — {s.account_ref(account)['title']}"
                          for account in accounts.values())
        raise ToolRefusal(f"Счёта {account_id} нет. Известные счета: {known or 'ни одного'}")

    conditions = []
    if instrument_id is not None:
        conditions.append(Transaction.instrument_id == instrument_id)
    if account_id is not None:
        conditions.append(Transaction.account_id == account_id)
    if types:
        conditions.append(Transaction.op_type.in_(types))
    if since is not None:
        # Границы дня — московские, как у снимков и графика (app/timeutils.py).
        conditions.append(Transaction.executed_at >= datetime.combine(since, time.min, tzinfo=MOSCOW_TZ))
    if until is not None:
        conditions.append(Transaction.executed_at < moscow_day_end(until))

    total, first, last = session.execute(
        select(func.count(Transaction.id), func.min(Transaction.executed_at),
               func.max(Transaction.executed_at)).where(*conditions)
    ).one()
    sums = session.execute(
        select(Transaction.op_type, Transaction.currency, func.count(Transaction.id),
               func.sum(Transaction.amount), func.sum(Transaction.fee))
        .where(*conditions)
        .group_by(Transaction.op_type, Transaction.currency)
        .order_by(Transaction.op_type, Transaction.currency)
    ).all()
    rows = session.execute(
        select(Transaction).where(*conditions)
        .order_by(Transaction.executed_at.desc(), Transaction.id.desc())
        .limit(limit).offset(offset)
    ).scalars().all()

    return {
        "filter": {"instrument_id": instrument_id, "account_id": account_id,
                   "op_types": [member.value for member in types] or None,
                   "since": s.day(since), "until": s.day(until)},
        "total": total, "offset": offset, "limit": limit, "returned": len(rows),
        "truncated": offset + len(rows) < total,
        "date_range": {"from": s.day(moscow_date(first)) if first else None,
                       "to": s.day(moscow_date(last)) if last else None},
        "sums": [
            {"op_type": getattr(op_type, "value", op_type), "currency": currency, "count": count,
             "amount": s.amount(amount), "fee": s.amount(fee)}
            for op_type, currency, count, amount, fee in sums
        ],
        "rows": [
            {"id": row.id, "date": s.day(moscow_date(row.executed_at)),
             "executed_at": s.moment(row.executed_at),
             "account": s.account_ref(accounts[row.account_id]) if row.account_id in accounts else None,
             "op_type": row.op_type.value,
             "instrument": s.instrument_ref(row.instrument) if row.instrument is not None else None,
             "quantity": s.qty(row.quantity), "price": s.price(row.price),
             "amount": s.amount(row.amount), "currency": row.currency, "fee": s.amount(row.fee),
             "source": row.source}
            for row in rows
        ],
        "note": ("Знак amount — с точки зрения счёта: покупка и комиссия отрицательны, продажа и "
                 "выплаты положительны. Строки — самые новые первыми; sums и date_range посчитаны "
                 "по всей выборке, а не по странице. source=manual — запись, порождённая решением "
                 "владельца по расхождению."),
    }
