from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.connectors.base import BrokerConnector
from app.ledger.service import append_operations
from app.marketdata.broker_prices import store_broker_prices
from app.models import Account, SyncRun
from app.positions.service import rebuild_positions
from app.sync.reconcile import reconcile_account
from app.timeutils import moscow_today

# Глубина истории для самой первой синхронизации брокера — когда успешных
# прогонов ещё не было и опереться не на что.
DEFAULT_HISTORY_DAYS = 365 * 5

# Запас времени, на который отступаем назад от начала последнего успешного
# прогона при повторной синхронизации. Нужен, потому что брокер может
# доложить операцию задним числом (например, расчёты по сделке пришли на
# день позже); дедупликация в журнале делает такое перекрытие безопасным.
SYNC_OVERLAP_DAYS = 3


def resolve_since_for_account(session: Session, account_id: int) -> datetime:
    """Точка отсчёта для следующей синхронизации конкретного счёта.

    Если у этого счёта уже был хотя бы один успешный прогон — берём момент
    его начала с запасом SYNC_OVERLAP_DAYS назад, а не глубокую историю
    заново: при десятках тысяч операций и синхронизации по расписанию
    вычитывать всю историю каждый раз слишком дорого.

    Прогонов ещё не было — идём от даты открытия счёта, если брокер её
    сообщил. Фиксированная глубина «сегодня минус DEFAULT_HISTORY_DAYS»
    молча обрезает историю ровно у тех счетов, что старше неё, и обрезает
    несимметрично: продажа бумаги попадает в окно, а покупка до границы —
    нет. Движок позиций не даёт остатку уйти в минус, отбрасывает излишек
    продажи, и на счёте навсегда остаётся бумага, которой давно нет. На
    живом счёте владельца (открыт 15.07.2020, окно начиналось 12.08.2021)
    так возникали фантомные остатки. DEFAULT_HISTORY_DAYS остаётся запасным
    путём для брокеров, которые дату открытия не отдают.

    Считать это по брокеру целиком (взять последний успешный прогон среди
    ЛЮБОГО счёта брокера) нельзя: при частичном сбое синхронизации — а такое
    уже случалось вживую — один счёт успешно синхронизировался, а другой
    нет. Общая по брокеру точка отсчёта в следующий раз возьмёт время
    успеха счёта-соседа и подсунет узкое окно счёту, который вообще ни разу
    не синхронизировался, — его история тогда тихо никогда не подтянется."""
    last_started_at = session.execute(
        select(func.max(SyncRun.started_at)).where(
            SyncRun.account_id == account_id, SyncRun.status == "success"
        )
    ).scalar_one()

    if last_started_at is not None:
        return last_started_at - timedelta(days=SYNC_OVERLAP_DAYS)

    opened_at = session.get(Account, account_id).opened_at
    if opened_at is not None:
        return datetime.combine(opened_at, time.min, tzinfo=timezone.utc)

    return datetime.now(tz=timezone.utc) - timedelta(days=DEFAULT_HISTORY_DAYS)


def _get_or_create_account(session: Session, broker: str, broker_account) -> Account:
    existing = session.execute(
        select(Account).where(Account.broker == broker, Account.external_id == broker_account.external_id)
    ).scalar_one_or_none()
    if existing is not None:
        # Дозаполняем дату открытия, но не переписываем уже известную: счета,
        # заведённые до появления этого поля, стоят с пустой датой, и без
        # дозаполнения их первая синхронизация навсегда осталась бы на
        # фиксированной глубине.
        if existing.opened_at is None and broker_account.opened_at is not None:
            existing.opened_at = broker_account.opened_at
        return existing

    account = Account(
        broker=broker,
        kind=broker_account.kind,
        external_id=broker_account.external_id,
        name=broker_account.name,
        currency="RUB",
        opened_at=broker_account.opened_at,
    )
    session.add(account)
    session.flush()
    return account


def sync_broker(
    session: Session, connector: BrokerConnector, since: datetime | None = None
) -> list[SyncRun]:
    """Синхронизирует все счета брокера.

    `since=None` (обычный режим планировщика и REST-эндпоинта) — точка
    отсчёта вычисляется для каждого счёта отдельно через
    resolve_since_for_account, внутри цикла, потому что у разных счётов
    этого брокера история успешных прогонов может отличаться (см. её
    docstring). Явно переданное значение `since` — точка отсчёта одна на
    все счета и переопределяет резолвинг; это осознанная лазейка для
    ручного полного пересчёта истории (и для тестов, которым нужен
    предсказуемый фиксированный since)."""
    runs: list[SyncRun] = []

    for broker_account in connector.fetch_accounts():
        run = SyncRun(broker=connector.source, status="running")
        session.add(run)
        session.flush()

        # Весь риск по этому счёту (включая заведение самого счёта — оно тоже может
        # упасть на битых данных брокера) идёт под собственным SAVEPOINT, а не в общей
        # транзакции: так отказ одного счёта не портит работу с остальными.
        savepoint = session.begin_nested()
        try:
            account = _get_or_create_account(session, connector.source, broker_account)
            run.account_id = account.id

            account_since = since if since is not None else resolve_since_for_account(session, account.id)
            operations = connector.fetch_operations(account.external_id, account_since)
            result = append_operations(session, account, connector.source, operations)
            # Присваиваем сразу, а не одной группой в конце: если сбой случится на
            # следующих шагах (пересборка позиций, получение снимка брокера, сверка),
            # запись прогона обязана отражать реально произошедшее, а не нули только
            # потому, что путь оборвался раньше финальных присвоений.
            run.inserted = result.inserted
            run.skipped = result.skipped

            rebuild_positions(session, account)

            # Цены брокера — запасной источник оценки для того, чего нет на
            # MOEX. Пишутся под московской календарной датой, той же, под
            # которой пишутся биржевые котировки и снимок стоимости.
            store_broker_prices(session, connector.fetch_prices(account.external_id), moscow_today())

            broker_positions = connector.fetch_positions(account.external_id)
            findings = reconcile_account(session, account, broker_positions)
            run.mismatches = len(findings)

            run.status = "success"
        except DBAPIError as error:
            # Настоящая ошибка PostgreSQL (например, битые данные счёта) переводит
            # транзакцию в aborted-состояние — откатываем SAVEPOINT именно этого счёта,
            # а не всю транзакцию, чтобы сессия осталась пригодна для следующего счёта.
            # Откат SAVEPOINT стирает и уже присвоенные выше числа (run.account_id,
            # run.inserted, run.skipped) вместе с самими данными — SQLAlchemy
            # восстанавливает атрибуты run до состояния на момент начала SAVEPOINT,
            # включая случай, когда откат происходит уже после того, как эти поля
            # получили ненулевые значения. Это не предположение: см.
            # test_db_level_failure_after_operations_written_keeps_run_and_session_consistent
            # в tests/test_sync_service.py — там записан фактически наблюдаемый после
            # отката run.account_id=None, run.inserted=0, а следующий счёт при этом
            # обрабатывается штатно (флаш на несуществующий account_id не падает).
            savepoint.rollback()
            run.status = "failed"
            run.error = f"Ошибка базы данных при обработке счёта: {error}"
        except Exception as error:  # noqa: BLE001 — отказ источника (сеть, брокер) не должен ронять синхронизацию
            # Это не ошибка PostgreSQL — транзакция не повреждена, поэтому уже
            # записанные на этом шаге данные (например, добавленные операции) сохраняются,
            # а не откатываются вместе с отказавшим последним шагом.
            savepoint.commit()
            run.status = "failed"
            run.error = f"Ошибка брокера при синхронизации счёта: {error}"
        else:
            savepoint.commit()

        run.finished_at = datetime.now(tz=timezone.utc)
        session.flush()
        runs.append(run)

    session.commit()
    return runs
