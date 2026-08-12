from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.accounts.labels import account_label
from app.api.routes_sync import get_tbank_connector
from app.connectors.base import BrokerAccount
from app.db import get_session
from app.main import app
from app.models import (
    Account,
    CashBalance,
    DailySnapshot,
    Instrument,
    Position,
    Price,
    Reconciliation,
    SyncRun,
)
from app.snapshots.service import take_snapshot
from app.sync.service import DEFAULT_HISTORY_DAYS, SYNC_OVERLAP_DAYS
from app.timeutils import moscow_today


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def price_day(days_ago: int = 3) -> date:
    """Дата котировки в тестах — от сегодняшней московской, а не зафиксированная
    в прошлом: оценка не берёт цену старше `PRICE_MAX_AGE`
    (app/marketdata/service.py), и дата из марта делала бы тест зелёным ровно до
    истечения недели после неё. По той же причине к «сегодня» привязаны курсы."""
    return moscow_today() - timedelta(days=days_ago)


def seed(session):
    account = Account(broker="tbank", kind="brokerage", external_id="acc-1",
                      name="Брокерский", currency="RUB")
    instrument = Instrument(isin="RU0009029540", ticker="SBER", secid="SBER",
                            kind="share", currency="RUB", issuer="Сбербанк")
    session.add_all([account, instrument])
    session.flush()
    session.add(Position(account_id=account.id, instrument_id=instrument.id,
                         quantity=Decimal("10"), average_price=Decimal("100")))
    session.add(Price(instrument_id=instrument.id, on_date=price_day(),
                      close=Decimal("150"), source="moex"))
    session.flush()
    return account, instrument


def test_overview_returns_strings_not_floats(client, session):
    seed(session)
    payload = client.get("/api/portfolio/overview").json()
    assert payload["total_value"] == "1500.0000"
    assert isinstance(payload["by_asset_class"]["equity"], str)
    # Дословного дубля total_value в контракте больше нет: два одинаковых числа
    # заставляли гадать, какое из них главное. Отдельная стоимость позиций
    # вернётся вместе с денежными остатками, когда перестанет их дублировать.
    assert "positions_value" not in payload


def test_overview_includes_as_of_date(client, session):
    seed(session)
    payload = client.get("/api/portfolio/overview").json()
    assert payload["as_of"] == price_day().isoformat()


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


def test_history_returns_breakdown_by_account(client, session, account):
    """История отдаёт разбивку по счетам, а не только итог.

    Разбивка считается и хранится с фазы 2a, но читатель (snapshot_by_account)
    не вызывался из production-кода ни разу — данные копились в стол.
    """
    session.add(CashBalance(account_id=account.id, currency="RUB",
                            amount=Decimal("1000"), blocked=Decimal("0")))
    session.flush()

    take_snapshot(session, moscow_today())
    session.commit()

    points = client.get("/api/portfolio/history").json()

    assert points, "снимок за сегодня должен попасть в окно истории"
    assert account_label(account) in points[-1]["by_account"]


def test_history_does_not_query_accounts_per_point(client, session, account):
    """Разбивка по счетам в истории — один запрос к таблице account на весь
    ответ, а не один на точку.

    До этой правки `snapshot_by_account` сама выбирала все счета без фильтра
    внутри цикла по строкам `get_history` — один обход истории превращался в
    1 + N запросов, где N — число точек в окне (до 90, снимок один в сутки).
    Три соседних обработчика в этом же файле (`get_overview`, `get_positions`,
    `get_cash`) уже выбирают счета в словарь один раз на запрос и передают его
    дальше; `get_history` был единственным исключением.
    """
    session.add(CashBalance(account_id=account.id, currency="RUB",
                            amount=Decimal("1000"), blocked=Decimal("0")))
    session.flush()
    for offset in range(5):
        take_snapshot(session, moscow_today() - timedelta(days=offset))
    session.commit()

    statements: list[str] = []

    @event.listens_for(session.get_bind(), "before_cursor_execute")
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    try:
        response = client.get("/api/portfolio/history")
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", record)

    assert response.status_code == 200
    lookups = [s for s in statements if "FROM account" in s]
    assert len(lookups) == 1, (
        f"Выбор счетов ушёл {len(lookups)} раз на 5 точек истории — запрос "
        "обязан быть один на весь ответ."
    )


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


def test_overview_exposes_capital_parts(client, session):
    """Контракт обязан разделять бумаги и деньги: одна общая цифра не даёт
    понять, отчего капитал изменился."""
    account, instrument = seed(session)
    session.add(CashBalance(account_id=account.id, currency="RUB",
                            amount=Decimal("20782.27"), blocked=Decimal("0")))
    session.flush()

    body = client.get("/api/portfolio/overview").json()

    assert body["securities_value"] == "1500.0000"
    assert body["cash_value"] == "20782.2700"
    assert body["total_value"] == "22282.2700"
    assert body["restricted_value"] == "0.0000"


def test_overview_names_currencies_left_out_of_the_total(client, session):
    """Валюта без курса выпадает из капитала, и контракт обязан её назвать:
    покрытие оценкой считает одни позиции, а денежный остаток в такой валюте
    исчезал бы, не отразившись ни в одной цифре ответа."""
    account, _ = seed(session)
    session.add(CashBalance(account_id=account.id, currency="XAG",
                            amount=Decimal("500"), blocked=Decimal("0")))
    session.flush()

    body = client.get("/api/portfolio/overview").json()

    assert body["currencies_without_rate"] == ["XAG"]


def test_positions_expose_price_source_and_blocked(client, session):
    """Оценка по цене брокера не независима, и это должно быть видно на экране,
    а не только в базе."""
    seed(session)

    body = client.get("/api/portfolio/positions").json()

    assert body[0]["price_source"] in ("moex", "tbank", None)
    assert "blocked" in body[0]
    assert "restricted" in body[0]
    assert "value_base" in body[0]
    # Валюта средней цены — своя: у замещающей облигации она рублёвая при
    # валютной котировке, и подписать среднюю валютой строки значит соврать.
    assert "average_price_currency" in body[0]


def test_cash_endpoint_lists_balances_per_account_and_currency(client, session):
    account, _ = seed(session)
    session.add(CashBalance(account_id=account.id, currency="RUB",
                            amount=Decimal("20782.27"), blocked=Decimal("0")))
    session.flush()

    body = client.get("/api/portfolio/cash").json()

    assert body == [{"account": "Брокерский (acc-1)", "currency": "RUB",
                     "amount": "20782.2700", "blocked": "0.0000"}]


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

    def fetch_prices(self, account_external_id):
        return []

    def fetch_cash(self, account_external_id):
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

    def fetch_prices(self, account_external_id):
        return []

    def fetch_cash(self, account_external_id):
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

    def fetch_prices(self, account_external_id):
        return []

    def fetch_cash(self, account_external_id):
        return []


def test_sync_tbank_endpoint_returns_runs(client, session):
    connector = RecordingConnector()
    app.dependency_overrides[get_tbank_connector] = lambda: connector

    payload = client.post("/api/sync/tbank").json()

    assert payload == [{
        "account": "Брокерский (acc-1)", "broker": "tbank", "status": "success",
        "inserted": 0, "skipped": 0, "mismatches": 0, "corrected": 0, "error": None,
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


def test_reconciliation_row_carries_its_suggestion(client, session):
    """Гипотеза едет вместе со строкой расхождения: интерфейс не должен
    сопоставлять два списка на своей стороне."""
    from decimal import Decimal

    from app.models import Account, Reconciliation

    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    session.add(account)
    session.flush()
    session.add_all([
        Reconciliation(account_id=account.id, isin="HK0000310034",
                       ledger_quantity=Decimal("79"), broker_quantity=Decimal("0"),
                       status="missing_at_broker"),
        Reconciliation(account_id=account.id, isin="HK0000051877",
                       ledger_quantity=Decimal("0"), broker_quantity=Decimal("79"),
                       status="missing_in_ledger"),
    ])
    session.commit()

    rows = client.get("/api/reconciliations").json()

    by_isin = {row["isin"]: row for row in rows}
    suggestion = by_isin["HK0000310034"]["suggestions"][0]
    assert suggestion["to_isin"] == "HK0000051877"
    assert suggestion["to_quantity"] == "79.00000000"
    assert suggestion["ambiguous"] is False


def test_post_decision_records_it_and_returns_the_result(client, session):
    from decimal import Decimal

    from app.ledger.schemas import RawOperation
    from app.ledger.service import append_operations
    from app.models import Account, Instrument

    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                     name="Инвестиционный", currency="RUB")
    old = Instrument(isin="HK0000310034", ticker="3010", secid="3010",
                     kind="share", currency="HKD")
    new = Instrument(isin="HK0000051877", ticker="3690", secid="3690",
                     kind="share", currency="HKD")
    session.add_all([account, old, new])
    session.flush()
    # Конвертация списывает партию из «старой» бумаги — она должна быть
    # открыта в журнале заранее, иначе движок отказывает: списывать нечего.
    append_operations(session, account, "tbank", [RawOperation(
        external_id="1", op_type="BUY",
        executed_at=datetime(2024, 5, 1, tzinfo=timezone.utc),
        isin="HK0000310034", ticker="3010", quantity=Decimal("79"),
        price=Decimal("120"), amount=Decimal("-9480"), currency="HKD",
        fee=Decimal("0"), payload={},
    )])
    session.commit()

    response = client.post("/api/decisions", json={
        "account": "Инвестиционный (acc-1)",
        "kind": "CONVERSION",
        "status": "CONFIRMED",
        "from_isin": "HK0000310034",
        "from_quantity": "79",
        "to_isin": "HK0000051877",
        "to_quantity": "79",
        "effective_at": "2026-03-01T00:00:00Z",
        "note": "Конвертация гонконгского ETF",
    })

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "CONVERSION"
    assert body["note"] == "Конвертация гонконгского ETF"

    listed = client.get("/api/decisions").json()
    assert len(listed) == 1


def test_post_decision_that_fails_in_the_engine_leaves_no_trace(client, session):
    """Решение проходит валидацию (_validate), но падает уже в движке
    партий — это ветка `except (ConversionError, ReversalError)` внутри
    SAVEPOINT в record_decision, а не ранняя проверка. Ни решение, ни
    порождённые им записи не должны остаться в базе, и клиент обязан
    получить текст настоящей причины, а не общую ошибку сервера."""
    from app.models import Account, Instrument, LedgerDecision, Transaction
    from sqlalchemy import select

    account = Account(broker="tbank", kind="broker", external_id="acc-1",
                      name="Инвестиционный", currency="RUB")
    old = Instrument(isin="HK0000310034", ticker="3010", secid="3010",
                     kind="share", currency="HKD")
    new = Instrument(isin="HK0000051877", ticker="3690", secid="3690",
                     kind="share", currency="HKD")
    session.add_all([account, old, new])
    session.commit()

    # В журнале нет ни одной операции по HK0000310034 — списывать движку
    # нечего, и отказ приходит уже после того, как решение и его записи легли
    # в сессию (см. record_decision в app/decisions/service.py).
    response = client.post("/api/decisions", json={
        "account": "Инвестиционный (acc-1)",
        "kind": "CONVERSION",
        "status": "CONFIRMED",
        "from_isin": "HK0000310034",
        "from_quantity": "79",
        "to_isin": "HK0000051877",
        "to_quantity": "79",
        "effective_at": "2026-03-01T00:00:00Z",
        "note": "Конвертация гонконгского ETF",
    })

    assert response.status_code == 400
    assert "не сходится с журналом операций" in response.json()["detail"]

    assert session.execute(select(LedgerDecision)).scalars().all() == []
    manual = session.execute(
        select(Transaction).where(Transaction.source == "manual")
    ).scalars().all()
    assert manual == []


def test_post_decision_without_note_is_rejected(client, session):
    from app.models import Account

    session.add(Account(broker="tbank", kind="broker", external_id="acc-1",
                        name="Инвестиционный", currency="RUB"))
    session.commit()

    response = client.post("/api/decisions", json={
        "account": "Инвестиционный (acc-1)",
        "kind": "ACCEPTED_AS_IS",
        "status": "CONFIRMED",
        "effective_at": "2026-03-01T00:00:00Z",
        "note": "   ",
    })

    assert response.status_code == 400
    assert "Пояснение обязательно" in response.json()["detail"]


def test_post_decision_for_unknown_account_returns_404(client, session):
    """Подпись счёта, которой нет ни у одного счёта, обязана вернуть внятную
    ошибку, а не 500 или молчаливое создание решения на случайном счёте."""
    response = client.post("/api/decisions", json={
        "account": "Не существует (acc-x)",
        "kind": "ACCEPTED_AS_IS",
        "status": "CONFIRMED",
        "effective_at": "2026-03-01T00:00:00Z",
        "note": "Проверка несуществующего счёта",
    })

    assert response.status_code == 404
    assert "Не существует (acc-x)" in response.json()["detail"]


def test_post_decision_for_unknown_isin_returns_404(client, session):
    """ISIN, которого нет в справочнике бумаг, — та же ситуация: решение не
    должно падать с чужой ошибкой или создаваться со сломанной ссылкой."""
    from app.models import Account

    session.add(Account(broker="tbank", kind="broker", external_id="acc-1",
                        name="Инвестиционный", currency="RUB"))
    session.commit()

    response = client.post("/api/decisions", json={
        "account": "Инвестиционный (acc-1)",
        "kind": "ADJUSTMENT",
        "status": "CONFIRMED",
        "from_isin": "XX0000000000",
        "from_quantity": "1",
        "effective_at": "2026-03-01T00:00:00Z",
        "note": "Проверка несуществующей бумаги",
    })

    assert response.status_code == 404
    assert "XX0000000000" in response.json()["detail"]


def test_revert_of_unknown_decision_returns_readable_error(client, session):
    """Отмена решения, которого нет, обязана вернуть причину владельцу, а не
    уронить запрос: сессия после неудачного вызова службы должна оставаться
    пригодной для ответа клиенту."""
    response = client.post("/api/decisions/999/revert", json={"note": "Отмена"})

    assert response.status_code == 400
    assert "999" in response.json()["detail"]
    assert "не найдено" in response.json()["detail"]


def test_reconciliation_suggestions_are_scoped_per_account(client, session):
    """Гипотезы считаются по каждому счёту отдельно: совпадение величин на
    чужом счёте не должно натекать в чужую строку расхождения."""
    from decimal import Decimal

    from app.models import Account, Reconciliation

    account_a = Account(broker="tbank", kind="broker", external_id="acc-a",
                        name="Счёт А", currency="RUB")
    account_b = Account(broker="tbank", kind="broker", external_id="acc-b",
                        name="Счёт Б", currency="RUB")
    session.add_all([account_a, account_b])
    session.flush()
    session.add_all([
        Reconciliation(account_id=account_a.id, isin="HK0000310034",
                       ledger_quantity=Decimal("79"), broker_quantity=Decimal("0"),
                       status="missing_at_broker"),
        Reconciliation(account_id=account_a.id, isin="HK0000051877",
                       ledger_quantity=Decimal("0"), broker_quantity=Decimal("79"),
                       status="missing_in_ledger"),
        # На счёте Б та же бумага и та же величина расхождения, но пары для
        # неё на этом счёте нет — гипотеза со счёта А не должна на него натечь.
        Reconciliation(account_id=account_b.id, isin="HK0000310034",
                       ledger_quantity=Decimal("79"), broker_quantity=Decimal("0"),
                       status="missing_at_broker"),
    ])
    session.commit()

    rows = client.get("/api/reconciliations").json()

    by_account_isin = {(row["account"], row["isin"]): row for row in rows}
    assert by_account_isin[("Счёт А (acc-a)", "HK0000310034")]["suggestions"]
    assert by_account_isin[("Счёт Б (acc-b)", "HK0000310034")]["suggestions"] == []


def test_history_returns_the_whole_period_by_default(client, session):
    """По умолчанию окно было девяносто дней, и достроенной истории за шесть
    лет в нём не видно вовсе."""
    session.add_all([
        DailySnapshot(on_date=date(2020, 7, 16), total_value=Decimal("1000.0000"),
                      by_asset_class={}, by_account={}, source="backfill",
                      positions_total=1, valued_positions=1, unpriced=[]),
        DailySnapshot(on_date=moscow_today(), total_value=Decimal("2000.0000"),
                      by_asset_class={}, by_account={}, source="live",
                      positions_total=2, valued_positions=1, unpriced=["ТКС Холдинг"]),
    ])
    session.commit()

    rows = client.get("/api/portfolio/history").json()

    assert [row["date"] for row in rows] == ["2020-07-16", moscow_today().isoformat()]


def test_history_point_carries_origin_and_coverage(client, session):
    session.add(DailySnapshot(on_date=date(2024, 6, 3), total_value=Decimal("1000.0000"),
                              by_asset_class={}, by_account={}, source="backfill",
                              positions_total=59, valued_positions=57,
                              unpriced=["ТКС Холдинг", "Block"]))
    session.commit()

    row = client.get("/api/portfolio/history").json()[0]

    assert row["source"] == "backfill"
    assert (row["valued_positions"], row["positions_total"]) == (57, 59)
    assert row["unpriced"] == ["ТКС Холдинг", "Block"]


def test_history_window_still_works_when_asked(client, session):
    session.add_all([
        DailySnapshot(on_date=date(2020, 7, 16), total_value=Decimal("1000.0000"),
                      by_asset_class={}, by_account={}),
        DailySnapshot(on_date=moscow_today(), total_value=Decimal("2000.0000"),
                      by_asset_class={}, by_account={}),
    ])
    session.commit()

    rows = client.get("/api/portfolio/history?days=30").json()

    assert [row["date"] for row in rows] == [moscow_today().isoformat()]
