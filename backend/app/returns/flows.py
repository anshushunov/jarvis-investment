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
    на счёте: пополнение счёта — вложение владельца.

    Дата и сумма — всё, что нужно и XIRR, и цепочке TWR, и прибыли. Счёт и
    запись журнала здесь лежали и не читались никем: периметр, к которому поток
    относится, задаёт та функция, которая его собрала (`account_flows`,
    `instrument_flows`), а не поле внутри потока.
    """

    on_date: date
    amount: Decimal


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
    return CashFlow(on_date=day, amount=in_base)


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


def _journal_rows(session: Session) -> list[Transaction]:
    """Весь журнал по порядку. Денежный периметр считается по нему целиком, а
    не по известным типам операций: запись неизвестного типа, двигающая деньги,
    обязана остаться расхождением, а не потеряться."""
    return list(session.execute(
        select(Transaction).order_by(Transaction.executed_at, Transaction.id)
    ).scalars().all())


def cash_movement(session: Session, book: RateBook, since: date | None = None,
                  until: date | None = None) -> Decimal:
    """Чистое движение денег за период, в рублях: сколько денег пришло в
    денежный периметр и сколько ушло. Положительное — пришло.

    Считается прямой суммой по журналу, а НЕ зеркалом посчитанных потоков
    («внешние потоки минус потоки бумаг минус Прочее»). Зеркало тождественно
    равно невязке разрезов: любая ошибка атрибуции по бумагам молча становилась
    прибылью денег, и «Расхождение с прибылью портфеля» переставало ловить
    что-либо вовсе (дизайн, раздел 7: строка не свалка для остатка).

    Правило движения — то же, что у движка позиций (`app/positions/engine.py`:
    `cash[currency] + entry.amount - entry.fee`), второго правила в проекте нет.

    Конверсии исключены: перекладывание рублей в юани или в золото остаётся
    внутри периметра, а записан у него только один бок — рублёвый, и сумма
    приняла бы обмен за уход денег на все 1,5 млн ₽ живого журнала.
    """
    total = Decimal("0")
    for row in _journal_rows(session):
        if _is_conversion(row):
            continue
        day = moscow_date(row.executed_at)
        if not _in_period(day, since, until):
            continue
        # abs(fee) — как в трёх соседних местах (_trade_flow, движок позиций,
        # прогон сверки): комиссия хранится положительной величиной и ВСЕГДА
        # уменьшает движение. Знак минус у неё в журнале означал бы возврат
        # комиссии, а `- row.fee` молча превратил бы такой возврат в списание.
        moved = book.to_base(row.amount - abs(row.fee), row.currency, day)
        if moved is not None:
            total += moved
    return total


def unconverted_flows(session: Session, book: RateBook, since: date | None = None,
                      until: date | None = None) -> list[str]:
    """Валюты потоков ПЕРИОДА, которым не нашлось курса на их дату.

    Границы обязательны по смыслу: покрытие показывается рядом с цифрой за
    период, и валюта, потоков в которой в этом периоде не было вовсе, поднимала
    бы тревогу о числе, на которое она не влияет. «С начала года» жаловался на
    гонконгский доллар из-за сделки 2021 года.

    Смотрится весь журнал, а не известные типы операций: молча выпавшее
    движение денег завышает доходность портфеля ровно на свою величину; молча
    выпавшая сделка исчезает из потока бумаги, и сумма по бумагам перестаёт
    сходиться с портфелем на ту же величину; молча выпавшая запись любого
    другого типа искажает строку «Деньги», которая считается по журналу
    целиком (`cash_movement`). Ни одно из трёх не видно на экране никак, если
    не назвать валюту явно.

    Конверсии сюда не попадают: они исключены из расчёта решением, а не
    отсутствием курса, и жаловаться на их валюту значило бы поднимать тревогу
    там, где ничего не потеряно.
    """
    return sorted({
        row.currency.upper()
        for row in _journal_rows(session)
        if not _is_conversion(row)
        and _in_period(moscow_date(row.executed_at), since, until)
        and book.rate(row.currency, moscow_date(row.executed_at)) is None
    })


# Типы, движущие деньги внутри периметра: они не капитал владельца, а результат
# и издержки. В потоки бумаги входят все, привязанные к ней; непривязанные
# собираются отдельной строкой (см. unattributed_flows).
#
# ЧЕГО ЗДЕСЬ НЕТ И КУДА ДЕВАЮТСЯ СУММЫ ЭТИХ ЗАПИСЕЙ:
#
# - DEPOSIT и WITHDRAWAL — не результат, а капитал владельца: они и есть потоки
#   портфеля (`portfolio_flows`), и попасть сюда не могут по смыслу. Войди они
#   в поток бумаги — пополнение счёта стало бы её убытком.
# - TRANSFER_IN/TRANSFER_OUT, CONVERSION_IN/CONVERSION_OUT — движение
#   КОЛИЧЕСТВА, не денег: перевод бумаг от другого брокера и две стороны
#   корпоративного действия (`app/decisions/service.py`). Денег они не несут, а
#   результат такого события виден стоимостью позиции — сама бумага никуда не
#   девалась.
# - ADJUSTMENT — корректировка операции, переписанной брокером задним числом
#   (`app/ledger/service.py::_correction_for`). Такая запись создаётся с
#   `instrument_id` исходной операции и НЕСЁТ настоящую денежную разницу
#   переписанной сделки, а порождается каждой синхронизацией.
#
# Сумма записи, не попавшей в RESULT_TYPES, не теряется молча и не оседает в
# строке «Деньги»: `cash_movement` читает журнал целиком, поэтому в прибыли
# денежного периметра она взаимно уничтожается (пришла на счёт — и учтена как
# движение), в поток бумаги не входит, в «Прочее» тоже. В прибыли портфеля она
# при этом есть — портфель считается по стоимости и внешним потокам. Значит,
# ненулевая сумма такой записи выходит наружу «Расхождением с прибылью
# портфеля» в прогоне (`app/returns/check.py`) — видимой, а не спрятанной.
#
# Замер 14.08.2026: в журнале один ADJUSTMENT, и он с нулевой суммой (решение
# владельца № 2 — поправка количества), поэтому сегодня цифры верны. Должен ли
# ADJUSTMENT с ненулевой суммой входить в поток своей бумаги — решение
# владельца, а не уборка: оно меняет прибыль конкретных бумаг задним числом.
RESULT_TYPES = {
    OperationType.BUY, OperationType.SELL, OperationType.DIVIDEND,
    OperationType.COUPON, OperationType.AMORTIZATION, OperationType.REDEMPTION,
    OperationType.FEE, OperationType.TAX, OperationType.VARIATION_MARGIN,
    OperationType.OTHER,
}

FEE_TYPES = {OperationType.FEE}
TAX_TYPES = {OperationType.TAX}

# Покупка и продажа без бумаги: конверсия валюты или металла.
CONVERSION_TYPES = {OperationType.BUY, OperationType.SELL}


def _is_conversion(transaction: Transaction) -> bool:
    """Покупка или продажа без `instrument_id` — конверсия, а не результат.

    Замер 14.08.2026: таких записей в журнале 563 — юань (200), гонконгский
    доллар (177), доллар (107), золото (13), фьючерс (11) и 123 покупки
    иностранных бумаг без сопоставленного инструмента, сальдо −1,52 млн ₽. Это
    движение внутри портфеля: рубли превратились в юани, капитал не изменился, а
    переоценка остатка уже видна в стоимости портфеля. Пока правило «запись без
    бумаги — комиссия или налог» держалось на всём подряд, строка «Прочее»
    показывала владельцу −1,66 млн ₽ вместо −103 тыс. ₽ комиссий и налогов, то
    есть полтора миллиона убытка, которого не было (дизайн, раздел 4.2).
    """
    return transaction.instrument_id is None and transaction.op_type in CONVERSION_TYPES


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
    return CashFlow(on_date=day, amount=in_base)


def instrument_flows(session: Session, book: RateBook, since: date | None = None,
                     until: date | None = None) -> dict[int, list[CashFlow]]:
    """Потоки по каждой бумаге. Ключ — instrument_id; записи без него сюда не
    попадают вовсе: комиссии и налоги учитываются строкой «Прочее», а конверсии
    валюты и металла не учитываются нигде (`_is_conversion`)."""
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
        if row.instrument_id is not None or _is_cash_move(row) or _is_conversion(row):
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
