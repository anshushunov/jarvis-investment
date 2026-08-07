from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.connectors.base import BrokerConnector
from app.ledger.service import append_operations
from app.models import Account, SyncRun
from app.positions.service import rebuild_positions
from app.sync.reconcile import reconcile_account


def _get_or_create_account(session: Session, broker: str, broker_account) -> Account:
    existing = session.execute(
        select(Account).where(Account.broker == broker, Account.external_id == broker_account.external_id)
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    account = Account(
        broker=broker,
        kind=broker_account.kind,
        external_id=broker_account.external_id,
        name=broker_account.name,
        currency="RUB",
    )
    session.add(account)
    session.flush()
    return account


def sync_broker(session: Session, connector: BrokerConnector, since: datetime) -> list[SyncRun]:
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

            operations = connector.fetch_operations(account.external_id, since)
            result = append_operations(session, account, connector.source, operations)
            rebuild_positions(session, account)

            broker_positions = connector.fetch_positions(account.external_id)
            findings = reconcile_account(session, account, broker_positions)

            run.inserted = result.inserted
            run.skipped = result.skipped
            run.mismatches = len(findings)
            run.status = "success"
        except DBAPIError as error:
            # Настоящая ошибка PostgreSQL (например, битые данные счёта) переводит
            # транзакцию в aborted-состояние — откатываем SAVEPOINT именно этого счёта,
            # а не всю транзакцию, чтобы сессия осталась пригодна для следующего счёта.
            savepoint.rollback()
            run.status = "failed"
            run.error = str(error)
        except Exception as error:  # noqa: BLE001 — отказ источника (сеть, брокер) не должен ронять синхронизацию
            # Это не ошибка PostgreSQL — транзакция не повреждена, поэтому уже
            # записанные на этом шаге данные (например, добавленные операции) сохраняются,
            # а не откатываются вместе с отказавшим последним шагом.
            savepoint.commit()
            run.status = "failed"
            run.error = str(error)
        else:
            savepoint.commit()

        run.finished_at = datetime.now(tz=timezone.utc)
        session.flush()
        runs.append(run)

    session.commit()
    return runs
