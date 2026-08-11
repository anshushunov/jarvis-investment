import logging
from datetime import date, datetime, timezone
from types import SimpleNamespace

import app.scheduler as scheduler_module
from app.scheduler import build_scheduler
from app.timeutils import MOSCOW_TZ, moscow_now, moscow_today


def test_scheduler_registers_expected_jobs():
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"refresh_prices", "refresh_fx", "daily_snapshot", "sync_tbank"}


def test_snapshot_runs_after_market_close():
    scheduler = build_scheduler()
    snapshot = scheduler.get_job("daily_snapshot")
    assert str(snapshot.trigger).startswith("cron")
    assert "hour='19'" in str(snapshot.trigger)


def test_jobs_use_moscow_timezone():
    # Контейнер живёт в UTC. Без явного пояса "19:30" планировщика означало бы
    # 19:30 UTC = 22:30 по Москве — уже после вечернего закрытия рынка и не
    # тот момент, который имелся в виду под "снимок после закрытия торгов".
    # Проверяем не только час, но и сам пояс триггеров.
    scheduler = build_scheduler()
    for job_id in ("refresh_prices", "daily_snapshot", "sync_tbank"):
        trigger = scheduler.get_job(job_id).trigger
        assert str(trigger.timezone) == "Europe/Moscow"


def test_calendar_date_is_taken_in_moscow_not_in_container_timezone():
    """Расписание объявлено в московском поясе, а календарная дата бралась по
    поясу процесса (в контейнере — UTC). С 21:00 UTC это уже следующие сутки по
    Москве; сейчас в это окно ни одна задача не попадает, но связь была
    неявной и держалась только на расписании."""
    utc_evening = datetime(2026, 3, 11, 22, 30, tzinfo=timezone.utc)
    assert utc_evening.date() == date(2026, 3, 11)
    assert utc_evening.astimezone(MOSCOW_TZ).date() == date(2026, 3, 12)

    assert moscow_today() == moscow_now().date()


def test_fx_job_is_registered():
    # build_scheduler() здесь не стартует (как и в остальных тестах файла),
    # поэтому shutdown() не нужен и упал бы с SchedulerNotRunningError.
    scheduler = build_scheduler()
    assert scheduler.get_job("refresh_fx") is not None


def test_sync_job_without_token_does_nothing(monkeypatch, caplog):
    """Пустой TBANK_TOKEN — задача молча пропускается, а не падает.

    У задачи снимка такой тест есть, у синхронизации не было: отказ здесь
    остановил бы весь планировщик, а вместе с ним и снимки, и курсы.
    """
    monkeypatch.setattr(scheduler_module, "get_settings",
                        lambda: SimpleNamespace(tbank_token=""))

    def fail(*args, **kwargs):
        raise AssertionError("К брокеру ходить не за чем: токена нет")

    monkeypatch.setattr(scheduler_module, "TBankConnector", fail)

    with caplog.at_level(logging.WARNING):
        scheduler_module.job_sync_tbank()

    assert any("TBANK_TOKEN" in record.getMessage() for record in caplog.records)
