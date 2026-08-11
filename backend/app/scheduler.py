import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.connectors.tbank.connector import TBankConnector
from app.db import SessionLocal
from app.marketdata.cbr import CbrClient
from app.marketdata.fx import refresh_fx_rates, refresh_metal_rates
from app.marketdata.moex import MoexClient
from app.marketdata.service import refresh_last_prices
from app.snapshots.service import take_snapshot
from app.sync.service import sync_broker
from app.timeutils import MOSCOW_TZ, moscow_today

logger = logging.getLogger(__name__)

# Расписание задано по московскому времени (торговая сессия MOEX и вечернее
# закрытие торгов ориентированы на неё), а не по времени контейнера — тот
# живёт в UTC. Без явного пояса "19:30" превратилось бы в 22:30 по Москве.
# Календарная дата, под которой пишутся котировки и снимок, берётся из того же
# пояса (moscow_today), а не по поясу процесса: раньше связь между расписанием
# и датой держалась только на том, что задачи не попадают в окно 00:00-03:00 MSK.
MOSCOW = str(MOSCOW_TZ)


def job_refresh_prices() -> None:
    with SessionLocal() as session:
        updated = refresh_last_prices(session, MoexClient(), moscow_today())
        session.commit()
        logger.info("Обновлено котировок: %s", updated)


def job_refresh_fx() -> None:
    with SessionLocal() as session:
        today = moscow_today()
        # Отказ ЦБ не должен мешать курсу золота и наоборот: это разные
        # источники, и половина курсов лучше, чем ни одного.
        try:
            fiat = refresh_fx_rates(session, CbrClient(), today)
        except Exception:  # noqa: BLE001 — отказ источника не роняет задачу
            logger.warning("Курсы ЦБ недоступны", exc_info=True)
            fiat = 0
        try:
            metals = refresh_metal_rates(session, MoexClient(), today)
        except Exception:  # noqa: BLE001
            logger.warning("Курс металлов с MOEX недоступен", exc_info=True)
            metals = 0
        session.commit()
        logger.info("Курсов обновлено: валют %s, металлов %s", fiat, metals)


def job_daily_snapshot() -> None:
    with SessionLocal() as session:
        today = moscow_today()
        refresh_last_prices(session, MoexClient(), today)
        try:
            refresh_fx_rates(session, CbrClient(), today)
        except Exception:  # noqa: BLE001 — снимок важнее свежести курсов
            logger.warning("Курсы ЦБ недоступны, снимок пойдёт по последним известным", exc_info=True)
        try:
            refresh_metal_rates(session, MoexClient(), today)
        except Exception:  # noqa: BLE001
            logger.warning("Курс металлов недоступен", exc_info=True)
        snapshot = take_snapshot(session, today)
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
                "Синхронизация %s: %s, новых %s, исправлено %s, расхождений %s",
                run.broker, run.status, run.inserted, run.corrected, run.mismatches,
            )


def build_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=MOSCOW)
    scheduler.add_job(
        job_refresh_prices,
        CronTrigger(day_of_week="mon-fri", hour="10-18", minute="*/15"),
        id="refresh_prices",
    )
    # Курсы ЦБ на следующий день публикуются днём; 12:10 МСК — время, когда
    # они уже есть, а до вечернего снимка стоимости ещё далеко.
    scheduler.add_job(
        job_refresh_fx,
        CronTrigger(hour="12", minute="10"),
        id="refresh_fx",
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
