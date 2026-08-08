from datetime import date, datetime, timezone

from app.scheduler import build_scheduler
from app.timeutils import MOSCOW_TZ, moscow_now, moscow_today


def test_scheduler_registers_expected_jobs():
    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert job_ids == {"refresh_prices", "daily_snapshot", "sync_tbank"}


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
