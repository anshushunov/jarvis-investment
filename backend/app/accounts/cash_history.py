"""Денежные остатки счетов на прошлые даты.

Считаются назад от сегодняшнего остатка брокера, а не вперёд от нуля. Причина
измерена: свёртка журнала вперёд не сходится с брокером — на «Инвестиционном»
расхождение 53 083,71 ₽ (замер 12.08.2026). Сегодняшний остаток известен точно,
и якорь на нём уводит накопленную ошибку в глубь истории, где её можно
измерить по дате открытия счёта, а не на сегодняшний экран, где ей верят.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.cash import cash_by_account
from app.models import Transaction
from app.money import money
from app.positions.engine import signed_quantity
from app.timeutils import moscow_date

logger = logging.getLogger(__name__)

# Валютные псевдоинструменты Т-Банка: покупка валюты приходит обычной BUY, где
# сумма — рубли, а количество — сама валюта. FIGI, а не название: название
# брокер меняет, идентификатор — нет. Список закрыт замером живого журнала
# 12.08.2026 (988 операций, пять инструментов); незнакомый FIGI не угадывается,
# а пишется в лог.
CURRENCY_BY_FIGI = {
    "BBG0013HRTL0": "CNY",
    "BBG0013HSW87": "HKD",
    "BBG0013HGFT4": "USD",
    "BBG0013HJJ31": "EUR",
    "BBG000VJ5YR4": "XAU",
}

CURRENCY_KIND = "currency"


def cash_flows(session: Session) -> list[tuple[datetime, int, str, Decimal]]:
    """Все движения денег журнала: когда, по какому счёту, в какой валюте, сколько.

    У валютной операции ног две: рублёвая (сумма минус комиссия) и валютная
    (количество со знаком по типу операции). Знак валютной ноги берётся из
    общего доменного соглашения (`signed_quantity`), а не ставится здесь: то же
    правило читают движок позиций и служба решений, и разъезжаться им нельзя.
    """
    flows: list[tuple[datetime, int, str, Decimal]] = []
    transactions = session.execute(
        select(Transaction).order_by(Transaction.executed_at)
    ).scalars().all()

    for tx in transactions:
        flows.append((tx.executed_at, tx.account_id, tx.currency.upper(),
                      money(tx.amount - tx.fee)))

        payload = tx.payload or {}
        if payload.get("instrument_kind") != CURRENCY_KIND:
            continue

        figi = payload.get("figi") or ""
        currency = CURRENCY_BY_FIGI.get(figi)
        if currency is None:
            logger.warning(
                "Валютная операция %s с неизвестным FIGI %s: вторая нога не "
                "учтена, история остатков по этой валюте неполна",
                tx.id, figi,
            )
            continue

        amount = signed_quantity(tx.op_type, tx.quantity)
        if amount:
            flows.append((tx.executed_at, tx.account_id, currency, money(amount)))

    return flows


def cash_history(
    session: Session, start: date, end: date
) -> dict[date, dict[int, dict[str, Decimal]]]:
    """Остатки на каждый день периода: дата → счёт → валюта → сумма.

    Идём от `end` назад: остаток предыдущего дня — это остаток следующего минус
    движения следующего дня. Валюта, которой в сегодняшнем остатке нет, но
    которая встречалась в журнале, появляется по ходу сама — так в истории
    оживают доллары, проданные в 2023 году.
    """
    balances: dict[int, dict[str, Decimal]] = {
        account_id: dict(currencies)
        for account_id, currencies in cash_by_account(session).items()
    }

    by_day: dict[date, list[tuple[int, str, Decimal]]] = defaultdict(list)
    for executed_at, account_id, currency, amount in cash_flows(session):
        # Московская календарная дата операции: снимок живёт в ней же, и
        # операция 21:30 UTC обязана попасть в следующий день, а не в текущий.
        # Правило одно на проект и живёт в `moscow_date` — ради этого она и
        # заведена; вторая запись того же перевода разъехалась бы с первой.
        moscow_day = moscow_date(executed_at)
        by_day[moscow_day].append((account_id, currency, amount))

    history: dict[date, dict[int, dict[str, Decimal]]] = {}
    day = end
    while day >= start:
        history[day] = {
            account_id: dict(currencies) for account_id, currencies in balances.items()
        }
        for account_id, currency, amount in by_day.get(day, []):
            account = balances.setdefault(account_id, {})
            account[currency] = money(account.get(currency, money("0")) - amount)
        day -= timedelta(days=1)

    return history
