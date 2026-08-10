from decimal import Decimal

from app.connectors.base import BrokerPosition
from app.models import Account, Instrument, Position, Reconciliation
from app.sync.reconcile import reconcile_account


def setup(session) -> tuple[Account, Instrument]:
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB")
    session.add_all([account, instrument])
    session.flush()
    return account, instrument


def add_position(session, account, instrument, qty: str) -> Position:
    position = Position(account_id=account.id, instrument_id=instrument.id,
                        quantity=Decimal(qty), average_price=Decimal("100"))
    session.add(position)
    session.flush()
    return position


def test_matching_quantities_produce_no_records(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("35"))
    ])

    assert result == []
    assert session.query(Reconciliation).count() == 0


def test_duplicate_isin_from_broker_is_summed_like_the_snapshot(session):
    """Одна бумага с двух площадок приходит в ответе дважды — живой случай,
    уронивший store_holdings на паре (1, RU0009029540). Снимок складывает такие
    записи, а сверка брала последнюю: одно и то же количество у брокера
    получалось разным в таблице позиций и в баннере расхождений, и вдобавок на
    ровном месте появлялось ложное «количество не сходится»."""
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("20")),
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("15")),
    ])

    assert result == []
    assert session.query(Reconciliation).count() == 0


def test_duplicate_isin_sums_into_the_reported_broker_quantity(session):
    """А когда расхождение всё-таки есть, у брокера показывается сумма обеих
    порций, а не последняя из них."""
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("20")),
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("10")),
    ])

    assert len(result) == 1
    assert (result[0].status, result[0].broker_quantity) == ("quantity_mismatch", Decimal("30"))


def test_quantity_mismatch_is_recorded(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("40"))
    ])

    assert len(result) == 1
    assert result[0].ledger_quantity == Decimal("35.00000000")
    assert result[0].broker_quantity == Decimal("40.00000000")
    assert result[0].status == "quantity_mismatch"


def test_mismatch_does_not_modify_position(session):
    account, instrument = setup(session)
    position = add_position(session, account, instrument, "35")

    reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("40"))
    ])

    session.refresh(position)
    assert position.quantity == Decimal("35.00000000")


def test_position_missing_in_ledger_is_recorded(session):
    account, _ = setup(session)

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU000A101234", ticker="OFZ", quantity=Decimal("10"))
    ])

    assert result[0].status == "missing_in_ledger"
    assert result[0].ledger_quantity == Decimal("0")
    assert result[0].isin == "RU000A101234"


def test_position_missing_at_broker_is_recorded(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [])

    assert result[0].status == "missing_at_broker"
    assert result[0].broker_quantity == Decimal("0")


def test_rerun_replaces_previous_results(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")
    broker = [BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("40"))]

    reconcile_account(session, account, broker)
    reconcile_account(session, account, broker)

    assert session.query(Reconciliation).count() == 1


def test_tiny_difference_below_threshold_is_ignored(session):
    account, instrument = setup(session)
    add_position(session, account, instrument, "35")

    result = reconcile_account(session, account, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("35.000000001"))
    ])

    assert result == []


def test_reconcile_does_not_touch_other_accounts_findings(session):
    account1, instrument = setup(session)
    account2 = Account(broker="tbank", kind="brokerage", external_id="acc-2",
                       name="ИИС", currency="RUB")
    session.add(account2)
    session.flush()

    add_position(session, account1, instrument, "35")
    add_position(session, account2, instrument, "99")

    result2 = reconcile_account(session, account2, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("50"))
    ])
    assert len(result2) == 1

    result1 = reconcile_account(session, account1, [
        BrokerPosition(isin="RU0009029540", ticker="SBER", quantity=Decimal("40"))
    ])

    assert len(result1) == 1
    assert result1[0].ledger_quantity == Decimal("35.00000000")
    assert result1[0].broker_quantity == Decimal("40.00000000")

    account2_findings = session.query(Reconciliation).filter_by(account_id=account2.id).all()
    assert len(account2_findings) == 1
    assert account2_findings[0].ledger_quantity == Decimal("99.00000000")
    assert account2_findings[0].broker_quantity == Decimal("50.00000000")
