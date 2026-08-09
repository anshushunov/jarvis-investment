from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.connectors.base import BrokerAccount, BrokerPosition, BrokerPrice
from app.ledger.schemas import RawOperation
from app.models import Account, OperationType, Position, Price, SyncRun
from app.sync.service import (
    DEFAULT_HISTORY_DAYS,
    SYNC_OVERLAP_DAYS,
    resolve_since_for_account,
    sync_broker,
)

SINCE = datetime(2026, 1, 1, tzinfo=timezone.utc)


class FakeConnector:
    source = "tbank"

    def __init__(self, operations=None, positions=None, fail_on_positions=False, prices=None):
        self.operations = operations or []
        self.positions = positions or []
        self.fail_on_positions = fail_on_positions
        self.prices = prices or []

    def fetch_accounts(self):
        return [BrokerAccount(external_id="acc-1", name="Брокерский", kind="brokerage")]

    def fetch_operations(self, account_external_id, since):
        return self.operations

    def fetch_positions(self, account_external_id):
        if self.fail_on_positions:
            raise RuntimeError("брокер недоступен")
        return self.positions

    def fetch_prices(self, account_external_id):
        return self.prices

    def fetch_cash(self, account_external_id):
        return []


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

    def fetch_prices(self, account_external_id):
        return []

    def fetch_cash(self, account_external_id):
        return []


class LateDbFailureConnector:
    """Счёт заводится и операция записывается успешно; настоящая ошибка PostgreSQL
    (DataError) случается только на шаге сверки — снимок брокера содержит ISIN
    длиннее колонки reconciliation.isin (String(12)). Проверяет самый неприятный
    сценарий отката SAVEPOINT: он происходит уже ПОСЛЕ того, как run.account_id,
    run.inserted и run.skipped были присвоены реальным ненулевым значениям."""

    source = "tbank"

    def fetch_accounts(self):
        return [
            BrokerAccount(external_id="acc-late-fail", name="Просядет на сверке", kind="brokerage"),
            BrokerAccount(external_id="acc-2", name="ИИС", kind="brokerage"),
        ]

    def fetch_operations(self, account_external_id, since):
        return [buy()] if account_external_id == "acc-late-fail" else []

    def fetch_positions(self, account_external_id):
        if account_external_id == "acc-late-fail":
            return [BrokerPosition(isin="RU0009029540XX", ticker="FAKE", quantity=Decimal("1"))]
        return []

    def fetch_prices(self, account_external_id):
        return []

    def fetch_cash(self, account_external_id):
        return []


class TwoAccountsRecordingConnector:
    """Двойник с двумя счетами, который запоминает, какое значение `since`
    синхронизация фактически передала в fetch_operations для каждого из
    них — нужен, чтобы проверить, что резолвинг `since` идёт по счёту, а не
    по брокеру целиком."""

    source = "tbank"

    def __init__(self):
        self.received_since: dict[str, datetime] = {}

    def fetch_accounts(self):
        return [
            BrokerAccount(external_id="acc-with-history", name="Брокерский", kind="brokerage"),
            BrokerAccount(external_id="acc-without-history", name="ИИС", kind="iis"),
        ]

    def fetch_operations(self, account_external_id, since):
        self.received_since[account_external_id] = since
        return []

    def fetch_positions(self, account_external_id):
        return []

    def fetch_prices(self, account_external_id):
        return []

    def fetch_cash(self, account_external_id):
        return []


class AccountWithOpeningDateConnector:
    """Брокер, отдающий дату открытия счёта, — как настоящий T-Invest API."""

    source = "tbank"

    def fetch_accounts(self):
        return [
            BrokerAccount(external_id="acc-1", name="Брокерский", kind="brokerage",
                          opened_at=date(2020, 7, 15))
        ]

    def fetch_operations(self, account_external_id, since):
        return []

    def fetch_positions(self, account_external_id):
        return []

    def fetch_prices(self, account_external_id):
        return []

    def fetch_cash(self, account_external_id):
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
    assert runs[0].error.startswith("Ошибка брокера")
    assert "недоступен" in runs[0].error


def test_failed_sync_keeps_already_written_operations(session):
    runs = sync_broker(session, FakeConnector(operations=[buy()], fail_on_positions=True), SINCE)
    from app.models import Transaction
    assert session.query(Transaction).count() == 1

    # Отказ случился уже после успешной записи операции в журнал (на получении
    # позиций) — запись прогона обязана отражать это реальное число вставленных,
    # а не врать нулём просто потому, что путь оборвался до строчки с присвоением.
    assert runs[0].status == "failed"
    assert runs[0].inserted == 1
    assert runs[0].skipped == 0


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
    assert runs[0].error.startswith("Ошибка базы данных")
    assert runs[1].status == "success"

    accounts = session.query(Account).all()
    assert [a.external_id for a in accounts] == ["acc-2"]


def test_db_level_failure_after_operations_written_keeps_run_and_session_consistent(session):
    """Не декларация, а факт: ошибка PostgreSQL, случившаяся уже после того как счёт
    завёлся и операция записалась (на шаге сверки), обязана откатить SAVEPOINT этого
    счёта целиком — включая сам счёт, операцию и уже присвоенные run.account_id /
    run.inserted / run.skipped, — а не оставить запись прогона рассинхронизированной
    с содержимым БД и не уронить финальный flush на внешнем ключе к откатившемуся
    счёту (что утащило бы за собой обработку остальных счетов)."""
    runs = sync_broker(session, LateDbFailureConnector(), SINCE)

    assert len(runs) == 2
    failed_run, ok_run = runs

    assert failed_run.status == "failed"
    assert failed_run.error.startswith("Ошибка базы данных")

    from app.models import Transaction
    assert session.query(Account).filter_by(external_id="acc-late-fail").count() == 0
    assert session.query(Transaction).count() == 0

    # Запись прогона обязана быть согласована с фактическим содержимым БД после
    # отката SAVEPOINT: операций не осталось — inserted/skipped должны отражать
    # именно это, а не значения, вычисленные до отката.
    assert failed_run.inserted == 0
    assert failed_run.skipped == 0
    assert failed_run.account_id is None

    # SAVEPOINT не должен утащить за собой обработку остальных счетов.
    assert ok_run.status == "success"
    assert session.query(Account).filter_by(external_id="acc-2").count() == 1


def _make_account(session, external_id="acc-1", name="Брокерский", opened_at=None) -> Account:
    account = Account(
        broker="tbank", kind="brokerage", external_id=external_id, name=name, opened_at=opened_at
    )
    session.add(account)
    session.flush()
    return account


def test_resolve_since_starts_from_account_opening_date_on_first_sync(session):
    """Счёт старше DEFAULT_HISTORY_DAYS: «сегодня минус пять лет» обрезало бы
    покупки, сделанные до этой границы. Продажи этих бумаг в окно попадают, а
    покупок нет — движок позиций не даёт уйти в минус, отбрасывает излишек
    продажи, и на счёте навсегда остаётся бумага, которой давно нет."""
    account = _make_account(session, opened_at=date(2020, 7, 15))
    assert resolve_since_for_account(session, account.id) == datetime(2020, 7, 15, tzinfo=timezone.utc)


def test_resolve_since_falls_back_to_deep_history_when_opening_date_unknown(session):
    """Дату открытия отдаёт не всякий брокер — без неё опереться можно только
    на фиксированную глубину."""
    account = _make_account(session, opened_at=None)
    since = resolve_since_for_account(session, account.id)
    expected = datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)
    assert abs((since - expected).total_seconds()) < 5


def test_resolve_since_prefers_last_successful_run_over_opening_date(session):
    """Дата открытия — ориентир только для ПЕРВОЙ синхронизации. У счёта с
    историей успешных прогонов она не должна возвращать вычитывание всей
    истории заново на каждом запуске планировщика."""
    account = _make_account(session, opened_at=date(2020, 7, 15))
    last_started = datetime(2026, 3, 1, tzinfo=timezone.utc)
    session.add(SyncRun(broker="tbank", account_id=account.id, status="success", started_at=last_started))
    session.flush()

    assert resolve_since_for_account(session, account.id) == last_started - timedelta(days=SYNC_OVERLAP_DAYS)


def test_sync_broker_records_opening_date_for_new_account(session):
    sync_broker(session, AccountWithOpeningDateConnector(), SINCE)
    assert session.query(Account).one().opened_at == date(2020, 7, 15)


def test_sync_broker_backfills_opening_date_of_already_known_account(session):
    """Счета, заведённые до появления этого поля, стоят с пустой датой открытия.
    Дозаполнить её обязана обычная синхронизация — иначе первый же прогон
    такого счёта снова уйдёт на фиксированную глубину."""
    account = _make_account(session, external_id="acc-1", opened_at=None)

    sync_broker(session, AccountWithOpeningDateConnector(), SINCE)

    session.refresh(account)
    assert account.opened_at == date(2020, 7, 15)


def test_resolve_since_uses_deep_history_when_no_successful_run_for_account(session):
    account = _make_account(session)
    since = resolve_since_for_account(session, account.id)
    expected = datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)
    assert abs((since - expected).total_seconds()) < 5


def test_resolve_since_ignores_failed_runs_without_success(session):
    account = _make_account(session)
    session.add(SyncRun(broker="tbank", account_id=account.id, status="failed",
                        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
    session.flush()

    since = resolve_since_for_account(session, account.id)
    expected = datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)
    assert abs((since - expected).total_seconds()) < 5


def test_resolve_since_uses_window_from_last_successful_run(session):
    account = _make_account(session)
    last_started = datetime(2026, 3, 1, tzinfo=timezone.utc)
    session.add(SyncRun(broker="tbank", account_id=account.id, status="success", started_at=last_started))
    session.flush()

    since = resolve_since_for_account(session, account.id)
    assert since == last_started - timedelta(days=SYNC_OVERLAP_DAYS)


def test_resolve_since_picks_latest_successful_run_not_first(session):
    account = _make_account(session)
    session.add_all([
        SyncRun(broker="tbank", account_id=account.id, status="success",
                started_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        SyncRun(broker="tbank", account_id=account.id, status="success",
                started_at=datetime(2026, 3, 1, tzinfo=timezone.utc)),
    ])
    session.flush()

    since = resolve_since_for_account(session, account.id)
    assert since == datetime(2026, 3, 1, tzinfo=timezone.utc) - timedelta(days=SYNC_OVERLAP_DAYS)


def test_resolve_since_is_scoped_per_account_not_broker(session):
    """Точка отсчёта другого счёта того же брокера не должна протекать в
    резолвинг текущего — иначе счёт, который ни разу не синхронизировался,
    получит чужое узкое окно и его история тихо никогда не подтянется."""
    account_with_history = _make_account(session, external_id="acc-with-history")
    account_without_history = _make_account(session, external_id="acc-without-history")
    session.add(SyncRun(broker="tbank", account_id=account_with_history.id, status="success",
                        started_at=datetime(2026, 3, 1, tzinfo=timezone.utc)))
    session.flush()

    since = resolve_since_for_account(session, account_without_history.id)
    expected = datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)
    assert abs((since - expected).total_seconds()) < 5


def test_sync_stores_broker_prices(session):
    """Цена брокера доезжает до таблицы котировок тем же прогоном, что и
    операции: иначе новая бумага оставалась бы неоценённой до ближайшего
    обновления котировок."""
    connector = FakeConnector(
        operations=[buy()],
        positions=[],
        prices=[BrokerPrice(isin="RU0009029540", price=Decimal("315.00"), currency="RUB")],
    )

    sync_broker(session, connector, SINCE)

    stored = session.query(Price).one()
    assert (stored.close, stored.source) == (Decimal("315.0000"), "tbank")


def test_sync_broker_resolves_since_independently_per_account(session):
    """Многосчётный сценарий целиком через sync_broker (since=None, как в
    проде): один счёт этого брокера уже синхронизировался успешно раньше,
    другой — ни разу. Первый обязан получить узкое окно от своей же
    истории, второй — глубокую историю, а не окно соседа."""
    existing_account = _make_account(session, external_id="acc-with-history")
    last_started = datetime(2026, 3, 1, tzinfo=timezone.utc)
    session.add(SyncRun(broker="tbank", account_id=existing_account.id, status="success",
                        started_at=last_started))
    session.flush()

    connector = TwoAccountsRecordingConnector()
    sync_broker(session, connector)

    assert connector.received_since["acc-with-history"] == last_started - timedelta(days=SYNC_OVERLAP_DAYS)

    expected_deep = datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)
    since_without_history = connector.received_since["acc-without-history"]
    assert abs((since_without_history - expected_deep).total_seconds()) < 5
