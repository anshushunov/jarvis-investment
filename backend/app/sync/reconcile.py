import logging
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.connectors.base import BrokerPosition
from app.models import Account, BrokerHolding, Instrument, Position, Reconciliation

logger = logging.getLogger(__name__)

TOLERANCE = Decimal("0.000001")


def reconcile_account(
    session: Session, account: Account, broker_positions: list[BrokerPosition]
) -> list[Reconciliation]:
    session.execute(delete(Reconciliation).where(Reconciliation.account_id == account.id))

    rows = session.execute(
        select(Position, Instrument)
        .join(Instrument, Position.instrument_id == Instrument.id)
        .where(Position.account_id == account.id)
    ).all()

    ledger: dict[str, tuple[Position, Instrument]] = {}
    for position, instrument in rows:
        if not instrument.isin:
            # Сверять нечем: снимок брокера ключуется ISIN. Позиция остаётся в
            # портфеле и в капитале, но в расхождения не попадает никогда —
            # и без этой строки понять, почему её там нет, неоткуда.
            logger.warning(
                "Позиция счёта %s по инструменту %s (%s, количество %s) не участвует в сверке: "
                "инструмент без ISIN.",
                account.external_id, instrument.id, instrument.ticker or instrument.issuer,
                position.quantity,
            )
            continue
        ledger[instrument.isin] = (position, instrument)
    # Тот же ISIN приходит от брокера дважды, когда бумага лежит на двух
    # площадках. Количества складываются — ровно как в store_holdings, потому
    # что это две порции одной бумаги на одном счёте. Одно правило на снимок и
    # на сверку обязательно: «последняя запись побеждает» давало здесь другое
    # количество, чем в таблице позиций, и вдобавок выдумывало расхождение с
    # журналом на ровном месте.
    broker: dict[str, Decimal] = {}
    for item in broker_positions:
        broker[item.isin] = broker.get(item.isin, Decimal("0")) + item.quantity

    findings: list[Reconciliation] = []

    for isin in sorted(ledger.keys() | broker.keys()):
        position_pair = ledger.get(isin)
        at_broker = broker.get(isin)

        ledger_qty = position_pair[0].quantity if position_pair else Decimal("0")
        broker_qty = at_broker if at_broker is not None else Decimal("0")

        if abs(ledger_qty - broker_qty) <= TOLERANCE:
            continue

        if position_pair is None:
            status = "missing_in_ledger"
        elif at_broker is None:
            status = "missing_at_broker"
        else:
            status = "quantity_mismatch"

        finding = Reconciliation(
            account_id=account.id,
            instrument_id=position_pair[1].id if position_pair else None,
            isin=isin,
            ledger_quantity=ledger_qty,
            broker_quantity=broker_qty,
            status=status,
        )
        session.add(finding)
        findings.append(finding)

    session.flush()
    return findings


def reconcile_from_snapshot(session: Session, account: Account) -> list[Reconciliation]:
    """Пересчитывает сверку по уже сохранённому снимку брокера.

    Нужна после решения владельца: подтверждение конвертации меняет позиции, и
    расхождения обязаны пересчитаться сразу. Ходить за этим к брокеру незачем —
    снимок лежит в broker_holding с прошлой синхронизации, а частота запросов у
    T-Invest API ограничена.

    Пустая таблица снимка означает «снимка нет», а не «у брокера ничего нет»:
    reconcile_account сначала стирает прежние расхождения счёта, а потом
    выписывает missing_at_broker на каждую позицию журнала. Счёт, чья
    синхронизация упала, не дойдя до store_holdings, получал бы после первого же
    решения владельца полный набор выдуманных расхождений. Отличить пустой
    снимок от отсутствующего нечем, поэтому выбор в пользу осторожного: старые
    расхождения остаются как есть до следующей удачной синхронизации.
    """
    holdings = session.execute(
        select(BrokerHolding).where(BrokerHolding.account_id == account.id)
    ).scalars().all()
    if not holdings:
        return []
    return reconcile_account(session, account, [
        BrokerPosition(isin=holding.isin, ticker=None,
                       quantity=holding.quantity, blocked=holding.blocked)
        for holding in holdings
    ])
