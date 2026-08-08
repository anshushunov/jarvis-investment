from app.scheduler import build_scheduler


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
