import logging
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.connectors.tbank.connector import TBankConnector
from app.db import SessionLocal
from app.marketdata.moex import MoexClient
from app.marketdata.service import refresh_last_prices
from app.snapshots.service import take_snapshot
from app.sync.service import sync_broker

logger = logging.getLogger(__name__)

# Расписание задано по московскому времени (торговая сессия MOEX и вечернее
# закрытие торгов ориентированы на неё), а не по времени контейнера — тот
# живёт в UTC. Без явного пояса "19:30" превратилось бы в 22:30 по Москве.
MOSCOW = "Europe/Moscow"


def job_refresh_prices() -> None:
    with SessionLocal() as session:
        updated = refresh_last_prices(session, MoexClient(), date.today())
        session.commit()
        logger.info("Обновлено котировок: %s", updated)


def job_daily_snapshot() -> None:
    with SessionLocal() as session:
        refresh_last_prices(session, MoexClient(), date.today())
        snapshot = take_snapshot(session, date.today())
        session.commit()
        logger.info("Снимок за %s: %s", snapshot.on_date, snapshot.total_value)


def job_sync_tbank() -> None:
    token = get_settings().tbank_token
    if not token:
        logger.warning("TBANK_TOKEN не задан, синхронизация пропущена")
        return

    # since не передаём: sync_broker сам вычисляет точку отсчёта для каждого
    # счёта отдельно (см. resolve_since_for_account) — от последней успешной
    # синхронизации этого счёта с запасом, а для счёта, ни разу ещё не
    # синхронизированного, берёт глубокую историю. Если передать здесь
    # фиксированное "сейчас минус N дней", это сломает наверстывание после
    # простоя: счёт, который не синхронизировался дольше N дней, каждый раз
    # будет получать одно и то же короткое окно вместо расширяющегося.
    with SessionLocal() as session:
        runs = sync_broker(session, TBankConnector(token))
        for run in runs:
            logger.info(
                "Синхронизация %s: %s, новых %s, расхождений %s",
                run.broker, run.status, run.inserted, run.mismatches,
            )


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=MOSCOW)
    scheduler.add_job(
        job_refresh_prices,
        CronTrigger(day_of_week="mon-fri", hour="10-18", minute="*/15"),
        id="refresh_prices",
    )
    scheduler.add_job(
        job_daily_snapshot,
        CronTrigger(hour="19", minute="30"),
        id="daily_snapshot",
    )
    scheduler.add_job(
        job_sync_tbank,
        CronTrigger(hour="9,20", minute="0"),
        id="sync_tbank",
    )
    return scheduler
