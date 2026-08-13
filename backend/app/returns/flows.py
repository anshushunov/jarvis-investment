from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.money import money
from app.models import OperationType, Transaction
from app.returns.rates import RateBook
from app.timeutils import moscow_date

# Ключ payload, под которым лежит исходный тип операции брокера.
RAW_TYPE_KEY = "operation_type"

# Ввод и вывод денег, приехавшие от брокера как мультивалютные: в журнале у них
# op_type = OTHER, потому что маппер их не знает. Замер 13.08.2026: 13.04.2026
# ровно такой парой ходят 40 000 ₽ между счетами 1 и 7, и по op_type их не
# видно вовсе. Маппер фаза не чинит — журнал append-only, и переписывание
# истории это отдельный разговор.
RAW_CASH_MOVE_TYPES = {"OPERATION_TYPE_INP_MULTI", "OPERATION_TYPE_OUT_MULTI"}

CASH_MOVE_TYPES = {OperationType.DEPOSIT, OperationType.WITHDRAWAL}


@dataclass(frozen=True)
class CashFlow:
    """Денежный поток периметра, в рублях. Знак — с точки зрения владельца:
    вложение отрицательно, изъятие положительно. Это ровно минус движение денег
    на счёте: пополнение счёта — вложение владельца."""

    on_date: date
    amount: Decimal
    account_id: int
    transaction_id: int


def _is_cash_move(transaction: Transaction) -> bool:
    if transaction.op_type in CASH_MOVE_TYPES:
        return True
    return (transaction.payload or {}).get(RAW_TYPE_KEY) in RAW_CASH_MOVE_TYPES


def _cash_moves(session: Session) -> list[Transaction]:
    rows = session.execute(
        select(Transaction)
        .where(Transaction.op_type.in_([*CASH_MOVE_TYPES, OperationType.OTHER]))
        .order_by(Transaction.executed_at, Transaction.id)
    ).scalars().all()
    return [row for row in rows if _is_cash_move(row)]


def _in_period(day: date, since: date | None, until: date | None) -> bool:
    if since is not None and day < since:
        return False
    return until is None or day <= until


def _pair_key(transaction: Transaction) -> tuple[date, str, Decimal]:
    return (moscow_date(transaction.executed_at),
            transaction.currency.upper(),
            abs(transaction.amount))


def _paired_ids(moves: list[Transaction]) -> set[int]:
    """Идентификаторы записей, гасящих друг друга: перевод между своими счетами.

    Пара — ввод и вывод одного московского дня, равные по модулю, в одной
    валюте, на РАЗНЫХ счетах. Подбор жадный, каждая запись входит не более чем в
    одну пару. Замер 13.08.2026 на живых данных: за шесть лет таких пар две, и
    обе настоящие. Ложное срабатывание завысило бы доходность, приняв пополнение
    за перекладывание, — поэтому условие узкое, а не «похоже по сумме». Для
    каждого прихода ищем первый ещё не занятый расход с ДРУГИМ счётом, а не
    берущийся по позиции: позиционное сопоставление теряло настоящую пару,
    когда рядом лежала запись того же дня и суммы на том же счёте.
    """
    by_key: dict[tuple[date, str, Decimal], list[Transaction]] = {}
    for move in moves:
        by_key.setdefault(_pair_key(move), []).append(move)

    paired: set[int] = set()
    for group in by_key.values():
        incoming = [move for move in group if move.amount > 0]
        outgoing = [move for move in group if move.amount < 0]
        used_outcome_ids: set[int] = set()
        for income in incoming:
            for outcome in outgoing:
                if outcome.id in used_outcome_ids:
                    continue
                if income.account_id == outcome.account_id:
                    # Один счёт — перекладывать некуда: это настоящие ввод и
                    # вывод, случайно совпавшие по сумме и дню.
                    continue
                used_outcome_ids.add(outcome.id)
                paired.add(income.id)
                paired.add(outcome.id)
                break
    return paired


def _to_flow(transaction: Transaction, book: RateBook) -> CashFlow | None:
    day = moscow_date(transaction.executed_at)
    # Минус: движение денег на счёте и поток владельца противоположны по знаку.
    in_base = book.to_base(-transaction.amount, transaction.currency, day)
    if in_base is None:
        return None
    return CashFlow(on_date=day, amount=in_base, account_id=transaction.account_id,
                    transaction_id=transaction.id)


def portfolio_flows(session: Session, book: RateBook, since: date | None = None,
                    until: date | None = None) -> list[CashFlow]:
    """Внешние потоки всего капитала: переводы между своими счетами погашены."""
    moves = _cash_moves(session)
    paired = _paired_ids(moves)
    flows = []
    for move in moves:
        if move.id in paired:
            continue
        flow = _to_flow(move, book)
        if flow is not None and _in_period(flow.on_date, since, until):
            flows.append(flow)
    return flows


def account_flows(session: Session, book: RateBook, account_id: int,
                  since: date | None = None, until: date | None = None) -> list[CashFlow]:
    """Потоки одного счёта: пары НЕ гасятся. Для счёта перевод — настоящий
    приход или уход денег, и гашение занизило бы и вложения, и изъятия."""
    flows = []
    for move in _cash_moves(session):
        if move.account_id != account_id:
            continue
        flow = _to_flow(move, book)
        if flow is not None and _in_period(flow.on_date, since, until):
            flows.append(flow)
    return flows


def unconverted_flows(session: Session, book: RateBook) -> list[str]:
    """Валюты потоков, которым не нашлось курса на их дату.

    Такой поток в расчёт не входит — и обязан быть назван: молча выпавшее
    пополнение завышает доходность ровно на свою величину, и по экрану этого не
    видно никак.
    """
    missing = {
        move.currency.upper()
        for move in _cash_moves(session)
        if book.rate(move.currency, moscow_date(move.executed_at)) is None
    }
    return sorted(missing)


# Типы, движущие деньги внутри периметра: они не капитал владельца, а результат
# и издержки. В потоки бумаги входят все, привязанные к ней; непривязанные
# собираются отдельной строкой (см. unattributed_flows).
RESULT_TYPES = {
    OperationType.BUY, OperationType.SELL, OperationType.DIVIDEND,
    OperationType.COUPON, OperationType.AMORTIZATION, OperationType.REDEMPTION,
    OperationType.FEE, OperationType.TAX, OperationType.VARIATION_MARGIN,
    OperationType.OTHER,
}

FEE_TYPES = {OperationType.FEE}
TAX_TYPES = {OperationType.TAX}


@dataclass(frozen=True)
class Unattributed:
    """Комиссии, налоги и возвраты, не относящиеся ни к одной бумаге.

    Живой замер 13.08.2026: 770 записей на −103 тыс. ₽. Без этой строки сумма
    разреза по бумагам не сходится с прибылью портфеля ровно на неё, и объяснить
    расхождение было бы нечем.
    """

    profit: Decimal
    fees: Decimal
    taxes: Decimal
    other: Decimal


def _result_rows(session: Session) -> list[Transaction]:
    return list(session.execute(
        select(Transaction)
        .where(Transaction.op_type.in_(RESULT_TYPES))
        .order_by(Transaction.executed_at, Transaction.id)
    ).scalars().all())


def _trade_flow(transaction: Transaction, book: RateBook) -> CashFlow | None:
    """Поток сделки или выплаты. Комиссия записи входит в её же поток: она часть
    цены сделки, и отдельным событием её показывать не за что."""
    day = moscow_date(transaction.executed_at)
    # Знак `amount` уже такой, как у движения денег: покупка отрицательна.
    # Комиссия хранится положительной величиной и всегда уменьшает поток.
    total = transaction.amount - abs(transaction.fee)
    in_base = book.to_base(total, transaction.currency, day)
    if in_base is None:
        return None
    return CashFlow(on_date=day, amount=in_base, account_id=transaction.account_id,
                    transaction_id=transaction.id)


def instrument_flows(session: Session, book: RateBook, since: date | None = None,
                     until: date | None = None) -> dict[int, list[CashFlow]]:
    """Потоки по каждой бумаге. Ключ — instrument_id; записи без него сюда не
    попадают вовсе и учитываются строкой «Прочее»."""
    result: dict[int, list[CashFlow]] = {}
    for row in _result_rows(session):
        if row.instrument_id is None:
            continue
        if _is_cash_move(row):
            # INP_MULTI/OUT_MULTI с привязкой к бумаге — это движение денег, а
            # не результат по бумаге. Такого в живых данных нет, но правило
            # обязано быть одним и тем же для обоих периметров.
            continue
        flow = _trade_flow(row, book)
        if flow is None or not _in_period(flow.on_date, since, until):
            continue
        result.setdefault(row.instrument_id, []).append(flow)
    return result


def unattributed_flows(session: Session, book: RateBook, since: date | None = None,
                       until: date | None = None) -> Unattributed:
    """Итог по записям без бумаги, разложенный на комиссии, налоги и прочее."""
    fees = taxes = other = Decimal("0")
    for row in _result_rows(session):
        if row.instrument_id is not None or _is_cash_move(row):
            continue
        flow = _trade_flow(row, book)
        if flow is None or not _in_period(flow.on_date, since, until):
            continue
        if row.op_type in FEE_TYPES:
            fees += flow.amount
        elif row.op_type in TAX_TYPES:
            taxes += flow.amount
        else:
            other += flow.amount

    return Unattributed(profit=money(fees + taxes + other), fees=money(fees),
                        taxes=money(taxes), other=money(other))
