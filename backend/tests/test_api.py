from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.routes_sync import get_tbank_connector
from app.connectors.base import BrokerAccount
from app.db import get_session
from app.main import app
from app.models import Account, DailySnapshot, Instrument, Position, Price, Reconciliation, SyncRun
from app.sync.service import DEFAULT_HISTORY_DAYS, SYNC_OVERLAP_DAYS


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def seed(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB", issuer="Сбербанк")
    session.add_all([account, instrument])
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=instrument.id,
                         quantity=Decimal("10"), average_price=Decimal("100")))
    session.add(Price(instrument_id=instrument.id, on_date=date(2026, 3, 12),
                      close=Decimal("150"), source="moex"))
    session.flush()
    return account, instrument


def test_overview_returns_strings_not_floats(client, session):
    seed(session)
    payload = client.get("/api/portfolio/overview").json()
    assert payload["positions_value"] == "1500.0000"
    assert isinstance(payload["by_asset_class"]["equity"], str)


def test_overview_includes_as_of_date(client, session):
    seed(session)
    payload = client.get("/api/portfolio/overview").json()
    assert payload["as_of"] == "2026-03-12"


def test_overview_as_of_is_none_for_empty_portfolio(client, session):
    payload = client.get("/api/portfolio/overview").json()
    assert payload["as_of"] is None


def test_positions_endpoint_returns_row(client, session):
    seed(session)
    rows = client.get("/api/portfolio/positions").json()
    assert len(rows) == 1
    assert rows[0]["ticker"] == "SBER"
    assert rows[0]["profit"] == "500.0000"
    assert rows[0]["account"] == "Брокерский (acc-1)"
    assert rows[0]["currency"] == "RUB"


def test_positions_endpoint_distinguishes_same_ticker_on_different_accounts(client, session):
    """Пять счетов одного брокера — и один тикер даёт пять строк, различить
    которые было нечем: в ответе не было признака счёта вовсе."""
    account, instrument = seed(session)
    second = Account(broker="tbank", kind="iis", external_id="acc-2", name="Брокерский")
    session.add(second)
    session.flush()
    session.add(Position(account_id=second.id, instrument_id=instrument.id,
                         quantity=Decimal("4"), average_price=Decimal("120")))
    session.flush()

    rows = client.get("/api/portfolio/positions").json()

    assert len(rows) == 2
    assert {row["account"] for row in rows} == {"Брокерский (acc-1)", "Брокерский (acc-2)"}


def test_history_returns_snapshots_in_date_order(client, session):
    # Брифовый тест использовал фиксированные даты 2026-03-11/12, но эндпоинт
    # фильтрует относительно date.today() (окно `days`) — на реальных датах
    # хоста (сильно позже марта 2026) такое фиксированное окно неизбежно
    # схлопывается в пустой список независимо от корректности кода. Берём
    # даты относительно "сегодня", чтобы тест проверял поведение (порядок,
    # сериализацию), а не совпадение с датой запуска.
    earlier = date.today() - timedelta(days=2)
    later = date.today() - timedelta(days=1)
    session.add_all([
        DailySnapshot(on_date=earlier, total_value=Decimal("7000"),
                      by_asset_class={}, by_account={}),
        DailySnapshot(on_date=later, total_value=Decimal("7350"),
                      by_asset_class={}, by_account={}),
    ])
    session.flush()

    rows = client.get("/api/portfolio/history?days=90").json()
    assert [row["date"] for row in rows] == [earlier.isoformat(), later.isoformat()]
    assert rows[1]["total_value"] == "7350.0000"


def test_reconciliations_endpoint_lists_findings(client, session):
    account, instrument = seed(session)
    session.add(Reconciliation(
        account_id=account.id, instrument_id=instrument.id, isin="RU0009029540",
        ledger_quantity=Decimal("10"), broker_quantity=Decimal("12"),
        status="quantity_mismatch",
    ))
    session.flush()

    rows = client.get("/api/reconciliations").json()
    assert rows[0]["status"] == "quantity_mismatch"
    assert rows[0]["broker_quantity"] == "12.00000000"
    assert rows[0]["account"] == "Брокерский (acc-1)"


def test_reconciliations_endpoint_distinguishes_accounts_with_same_isin(client, session):
    # Сверка считается по каждому счёту отдельно: один и тот же ISIN может
    # дать две строки на двух разных счетах, а имя счёта не обязано быть
    # уникальным (коннектор Т-Банка подставляет заглушку «Счёт»). Подпись в
    # ответе обязана всё равно их различать.
    account_a = Account(broker="tbank", kind="brokerage", external_id="acc-a", name="Счёт")
    account_b = Account(broker="tbank", kind="iis", external_id="acc-b", name="Счёт")
    session.add_all([account_a, account_b])
    session.flush()

    session.add_all([
        Reconciliation(account_id=account_a.id, isin="RU0009029540",
                       ledger_quantity=Decimal("10"), broker_quantity=Decimal("12"),
                       status="quantity_mismatch"),
        Reconciliation(account_id=account_b.id, isin="RU0009029540",
                       ledger_quantity=Decimal("5"), broker_quantity=Decimal("5.5"),
                       status="quantity_mismatch"),
    ])
    session.flush()

    rows = client.get("/api/reconciliations").json()
    labels = {row["account"] for row in rows if row["isin"] == "RU0009029540"}
    assert labels == {"Счёт (acc-a)", "Счёт (acc-b)"}


def test_account_label_is_the_same_everywhere_on_the_screen(client, session):
    """Один и тот же счёт подписан одинаково и в разбивке по счетам, и в
    баннере расхождений: обе подписи строит одна функция на проект. Раньше их
    было две, и на одном экране счёт назывался по-разному."""
    account, instrument = seed(session)
    session.add(Reconciliation(
        account_id=account.id, instrument_id=instrument.id, isin="RU0009029540",
        ledger_quantity=Decimal("10"), broker_quantity=Decimal("12"),
        status="quantity_mismatch",
    ))
    session.flush()

    overview = client.get("/api/portfolio/overview").json()
    reconciliations = client.get("/api/reconciliations").json()

    assert list(overview["by_account"]) == ["Брокерский (acc-1)"]
    assert reconciliations[0]["account"] == "Брокерский (acc-1)"


def test_empty_portfolio_returns_zeroes(client, session):
    payload = client.get("/api/portfolio/overview").json()
    assert payload["total_value"] == "0.0000"
    assert payload["by_asset_class"] == {}


class RecordingConnector:
    """Двойник BrokerConnector: не ходит в сеть, только запоминает, какое
    значение `since` синхронизация фактически передала в fetch_operations."""

    source = "tbank"

    def __init__(self):
        self.received_since: datetime | None = None

    def fetch_accounts(self):
        return [BrokerAccount(external_id="acc-1", name="Брокерский", kind="brokerage")]

    def fetch_operations(self, account_external_id, since):
        self.received_since = since
        return []

    def fetch_positions(self, account_external_id):
        return []


class SameNameAccountsConnector:
    """Два счёта с одинаковым именем — коннектор Т-Банка подставляет такую
    заглушку («Счёт»), если брокер имени не дал. Подпись счёта в ответе
    обязана различать их всё равно (за счёт внешнего идентификатора)."""

    source = "tbank"

    def fetch_accounts(self):
        return [
            BrokerAccount(external_id="acc-a", name="Счёт", kind="brokerage"),
            BrokerAccount(external_id="acc-b", name="Счёт", kind="brokerage"),
        ]

    def fetch_operations(self, account_external_id, since):
        return []

    def fetch_positions(self, account_external_id):
        return []


class AccountCreationFailsConnector:
    """Счёт с kind длиннее колонки account.kind (String(16)) — Postgres
    прерывает транзакцию DataError'ом ещё на заведении счёта, SAVEPOINT
    откатывает и его тоже. run.account_id остаётся None — ссылки на счёт,
    о котором шла речь, в записи прогона нет."""

    source = "tbank"

    def fetch_accounts(self):
        return [BrokerAccount(external_id="broken", name="Битый счёт", kind="x" * 20)]

    def fetch_operations(self, account_external_id, since):
        return []

    def fetch_positions(self, account_external_id):
        return []


def test_sync_tbank_endpoint_returns_runs(client, session):
    connector = RecordingConnector()
    app.dependency_overrides[get_tbank_connector] = lambda: connector

    payload = client.post("/api/sync/tbank").json()

    assert payload == [{
        "account": "Брокерский (acc-1)", "broker": "tbank", "status": "success",
        "inserted": 0, "skipped": 0, "mismatches": 0, "error": None,
    }]


def test_sync_response_distinguishes_accounts_with_same_name(client, session):
    app.dependency_overrides[get_tbank_connector] = lambda: SameNameAccountsConnector()

    payload = client.post("/api/sync/tbank").json()

    labels = [row["account"] for row in payload]
    assert labels == ["Счёт (acc-a)", "Счёт (acc-b)"]
    assert len(set(labels)) == 2


def test_sync_response_uses_meaningful_label_when_account_creation_fails(client, session):
    app.dependency_overrides[get_tbank_connector] = lambda: AccountCreationFailsConnector()

    payload = client.post("/api/sync/tbank").json()

    assert payload[0]["status"] == "failed"
    assert payload[0]["account"] == "счёт не определён"


def test_sync_first_run_uses_deep_history(client, session):
    connector = RecordingConnector()
    app.dependency_overrides[get_tbank_connector] = lambda: connector

    client.post("/api/sync/tbank")

    expected = datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)
    assert connector.received_since is not None
    assert abs((connector.received_since - expected).total_seconds()) < 5


def test_sync_repeat_run_uses_window_since_last_success(client, session):
    existing_account = Account(broker="tbank", kind="brokerage", external_id="acc-1", name="Брокерский")
    session.add(existing_account)
    session.flush()

    last_started = datetime(2026, 1, 1, tzinfo=timezone.utc)
    session.add(SyncRun(broker="tbank", account_id=existing_account.id, status="success",
                        started_at=last_started, finished_at=last_started))
    session.flush()

    connector = RecordingConnector()
    app.dependency_overrides[get_tbank_connector] = lambda: connector

    client.post("/api/sync/tbank")

    assert connector.received_since == last_started - timedelta(days=SYNC_OVERLAP_DAYS)


def test_sync_without_token_returns_clear_error(client, monkeypatch):
    class EmptyTokenSettings:
        tbank_token = ""

    monkeypatch.setattr("app.api.routes_sync.get_settings", lambda: EmptyTokenSettings())

    response = client.post("/api/sync/tbank")

    assert response.status_code == 400
    assert "TBANK_TOKEN" in response.json()["detail"]
