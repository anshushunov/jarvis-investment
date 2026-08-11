"""Гипотезы корпоративных действий из расхождений сверки.

Источника сведений о корпоративных действиях у T-Invest API нет. Единственное,
на что можно опереться, — арифметика: из журнала пропало ровно столько же,
сколько появилось у брокера. Величины сравниваются **точно**; подгонять близкие
числа нельзя, цена ошибки — неверная налоговая база.

Гипотезы нигде не хранятся: они пересчитываются при каждом запросе. В базе
остаётся только решение владельца, и отклонённое глушит повторный показ.
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrokerHolding, Instrument, LedgerDecision, Reconciliation
from app.models.ledger_decision import DecisionKind, DecisionStatus


@dataclass(frozen=True)
class Suggestion:
    from_isin: str
    from_quantity: Decimal
    to_isin: str
    to_quantity: Decimal
    # Бумага-получатель заблокирована у брокера целиком. Конвертации часто
    # оседают именно так — у живой пары это верно с обеих сторон. Признак
    # усиливающий: сам по себе гипотезу не создаёт, но показывается владельцу.
    blocked_fully: bool
    # У пары есть конкуренты — с любой из двух сторон. Выбирать за владельца
    # нельзя: в фазе 2a «правдоподобный» выбор стоил ошибок на миллионы.
    ambiguous: bool


def _rejected_pairs(session: Session, account_id: int) -> set[tuple[str, str]]:
    """Пары ISIN, по которым владелец уже сказал «нет»."""
    rows = session.execute(
        select(Instrument.isin, LedgerDecision.to_instrument_id)
        .join(LedgerDecision, LedgerDecision.from_instrument_id == Instrument.id)
        .where(
            LedgerDecision.account_id == account_id,
            LedgerDecision.kind == DecisionKind.CONVERSION,
            LedgerDecision.status == DecisionStatus.REJECTED,
        )
    ).all()
    if not rows:
        return set()

    to_isin = {
        instrument_id: isin
        for instrument_id, isin in session.execute(
            select(Instrument.id, Instrument.isin).where(
                Instrument.id.in_({row[1] for row in rows})
            )
        ).all()
    }
    # Строка без instrument_id на любой из сторон (решение записано не обеими
    # бумагами) в словарь to_isin не попадёт — такую пару глушить нечем, и
    # условие `to_id in to_isin` её просто отбрасывает, не роняя запрос.
    return {(from_isin, to_isin[to_id]) for from_isin, to_id in rows if to_id in to_isin}


def _fully_blocked(session: Session, account_id: int) -> set[str]:
    return {
        isin
        for isin, quantity, blocked in session.execute(
            select(BrokerHolding.isin, BrokerHolding.quantity, BrokerHolding.blocked)
            .where(BrokerHolding.account_id == account_id)
        ).all()
        if quantity > 0 and quantity == blocked
    }


def suggestions_for_account(session: Session, account_id: int) -> dict[str, list[Suggestion]]:
    """Гипотезы по счёту, сгруппированные по ISIN строки расхождения.

    Одна гипотеза попадает в словарь дважды — под ISIN обеих сторон: владелец
    может открыть разбор с любой из двух строк, и видеть он должен одно и то же.
    """
    findings = session.execute(
        select(Reconciliation).where(Reconciliation.account_id == account_id)
    ).scalars().all()

    # Кандидатами становятся только строки с известным ISIN и неотрицательным
    # остатком журнала. Пустой ISIN нечем подписать в возвращаемом словаре, а
    # отрицательный остаток — след короткой позиции, а не бумага, которой можно
    # конвертироваться; это верно для обеих сторон пары, не только для
    # списания. Без этого фильтра такая строка могла случайно совпасть по
    # величине с посторонним расхождением и породить гипотезу на пустом месте.
    candidates = [f for f in findings if f.isin is not None and f.ledger_quantity >= 0]

    # Излишек в журнале — кандидат на списание.
    surplus = [
        (f.isin, f.ledger_quantity - f.broker_quantity)
        for f in candidates
        if f.ledger_quantity > f.broker_quantity
    ]
    shortage = [
        (f.isin, f.broker_quantity - f.ledger_quantity)
        for f in candidates
        if f.broker_quantity > f.ledger_quantity
    ]

    rejected = _rejected_pairs(session, account_id)
    blocked = _fully_blocked(session, account_id)

    pairs = [
        (from_isin, from_quantity, to_isin, to_quantity)
        for from_isin, from_quantity in surplus
        for to_isin, to_quantity in shortage
        if to_quantity == from_quantity and (from_isin, to_isin) not in rejected
    ]

    # Конкуренция считается с обеих сторон. Одной стороны мало: два излишка по
    # 10 и одна недостача 10 дают каждому излишку ровно по одной гипотезе, и
    # каждая из них выглядела бы достоверной — панель предзаполнила бы форму
    # сама, а подтверждение обеих зачислило бы одну и ту же недостачу дважды.
    # Неоднозначна и та пара, у которой конкурент есть только у бумаги-получателя.
    rivals_of_source = Counter(pair[0] for pair in pairs)
    rivals_of_target = Counter(pair[2] for pair in pairs)

    result: dict[str, list[Suggestion]] = {}
    for from_isin, from_quantity, to_isin, to_quantity in pairs:
        suggestion = Suggestion(
            from_isin=from_isin, from_quantity=from_quantity,
            to_isin=to_isin, to_quantity=to_quantity,
            blocked_fully=to_isin in blocked,
            ambiguous=rivals_of_source[from_isin] > 1 or rivals_of_target[to_isin] > 1,
        )
        result.setdefault(from_isin, []).append(suggestion)
        result.setdefault(to_isin, []).append(suggestion)

    return result
