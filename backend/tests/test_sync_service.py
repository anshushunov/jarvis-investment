from datetime import datetime, timezone
from decimal import Decimal

from app.connectors.base import BrokerAccount, BrokerPosition
from app.ledger.schemas import RawOperation
from app.models import Account, OperationType, Position, SyncRun
from app.sync.service import sync_broker

SINCE = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeConnector:
    source = "tbank"

    def __init__(self, operations=None, positions=None, fail_on_positions=False):
        self.operations = operations or []
        self.positions = positions or []
        self.fail_on_positions = fail_on_positions

    def fetch_accounts(self):
        return [BrokerAccount(external_id="acc-1", name="Брокерский", kind="brokerage")]

    def fetch_operations(self, account_external_id, since):
        return self.operations

    def fetch_positions(self, account_external_id):
        if self.fail_on_positions:
            raise RuntimeError("брокер недоступен")
        return self.positions


class TwoAccountsConnector:
    """Первый счёт несёт битые данные (kind длиннее колонки account.kind —
    String(16)), из-за чего Postgres реально прерывает транзакцию DataError'ом при
    flush в _get_or_create_account. Второй счёт валиден и должен синхронизироваться
    штатно — сессия обязана остаться пригодной для работы после отказа первого."""

    source = "tbank"

    def fetch_accounts(self):
        return [
            BrokerAccount(external_id="broken", name="Битый счёт", kind="x" * 20),
            BrokerAccount(external_id="acc-2", name="ИИС", kind="brokerage"),
        ]

    def fetch_operations(self, account_external_id, since):
        return []

    def fetch_positions(self, account_external_id):
        return []


def buy() -> RawOperation:
    return RawOperation(
        external_id="op-1", op_type=OperationType.BUY,
        executed_at=datetime(2026, 3, 12, tzinfo=timezone.utc),
        isin="RU0009029540", ticker="SBER", quantity=Decimal("35"),
        price=Decimal("142.5"), amount=Decimal("-4987.5"), currency="RUB",
        fee=Decimal("0"), payload={},
    )


def test_creates_account_on_first_sync(session):
    sync_broker(session, FakeConnector(), SINCE)
    account = session.query(Account).one()
    assert account.external_id == "acc-1"
    assert account.broker == "tbank"


def test_second_sync_reuses_account(session):
    sync_broker(session, FakeConnector(), SINCE)
    sync_broker(session, FakeConnector(), SINCE)
    assert session.query(Account).count() == 1


def test_operations_land_in_journal_and_positions(session):
    runs = sync_broker(session, FakeConnector(operations=[buy()],
                                              positions=[BrokerPosition("RU0009029540", "SBER", Decimal("35"))]), SINCE)
    assert runs[0].inserted == 1
    assert runs[0].mismatches == 0
    assert session.query(Position).one().quantity == Decimal("35.00000000")


def test_mismatch_is_counted(session):
    runs = sync_broker(session, FakeConnector(operations=[buy()],
                                              positions=[BrokerPosition("RU0009029540", "SBER", Decimal("40"))]), SINCE)
    assert runs[0].mismatches == 1
    assert runs[0].status == "success"


def test_connector_failure_is_recorded_not_raised(session):
    runs = sync_broker(session, FakeConnector(operations=[buy()], fail_on_positions=True), SINCE)
    assert runs[0].status == "failed"
    assert "недоступен" in runs[0].error


def test_failed_sync_keeps_already_written_operations(session):
    sync_broker(session, FakeConnector(operations=[buy()], fail_on_positions=True), SINCE)
    from app.models import Transaction
    assert session.query(Transaction).count() == 1


def test_run_records_are_persisted(session):
    sync_broker(session, FakeConnector(), SINCE)
    assert session.query(SyncRun).count() == 1


def test_db_level_failure_on_one_account_does_not_break_others(session):
    """Отказ на уровне PostgreSQL (не сетевой/брокерский, а настоящий DataError на
    flush) переводит транзакцию в aborted-состояние. Прогон по первому счёту обязан
    завершиться failed, а сессия — остаться рабочей для второго счёта, который должен
    синхронизироваться успешно в рамках того же вызова sync_broker."""
    runs = sync_broker(session, TwoAccountsConnector(), SINCE)

    assert len(runs) == 2
    assert runs[0].status == "failed"
    assert runs[0].error
    assert runs[1].status == "success"

    accounts = session.query(Account).all()
    assert [a.external_id for a in accounts] == ["acc-2"]
