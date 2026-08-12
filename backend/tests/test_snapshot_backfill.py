from datetime import date, datetime
from decimal import Decimal

from app.analytics.service import Overview
from app.models import (
    SNAPSHOT_BACKFILL,
    SNAPSHOT_LIVE,
    DailySnapshot,
    Instrument,
    OperationType,
    Price,
    Transaction,
)
from app.snapshots.backfill import backfill_snapshots, first_operation_date
from app.snapshots.service import store_snapshot

DAY = date(2026, 8, 9)


def overview(total: str, valued: int | None, total_positions: int | None) -> Overview:
    return Overview(
        total_value=Decimal(total), securities_value=Decimal(total),
        cash_value=Decimal("0"), restricted_value=Decimal("0"),
        by_asset_class={}, by_account={}, by_currency={},
        position_currencies=[], currencies_without_rate=[],
        as_of=DAY, fx_as_of=DAY,
        valued_positions=valued, positions_total=total_positions, unpriced=[],
    )


def _stored(session) -> DailySnapshot:
    return session.query(DailySnapshot).filter(DailySnapshot.on_date == DAY).one()


def test_backfill_overwrites_a_snapshot_with_unknown_coverage(session):
    """Снимок 09.08.2026 снят живьём, но кодом до фазы 2a: в нём нет ни денег,
    ни двух третей позиций. Покрытие у него неизвестно, и это единственное, что
    достройке нужно знать, чтобы его перебить."""
    session.add(DailySnapshot(on_date=DAY, total_value=Decimal("6937338.9045"),
                              by_asset_class={}, by_account={}, source=SNAPSHOT_LIVE))
    session.flush()

    store_snapshot(session, DAY, overview("10948918.0777", 57, 59), SNAPSHOT_BACKFILL)

    stored = _stored(session)
    assert stored.total_value == Decimal("10948918.0777")
    assert stored.source == SNAPSHOT_BACKFILL


def test_backfill_does_not_overwrite_a_better_covered_live_snapshot(session):
    """Живой снимок не свят, но свято покрытие: достройка, оценившая меньше
    позиций, не имеет права затирать точку, где их оценено больше."""
    store_snapshot(session, DAY, overview("10948918.0777", 59, 59), SNAPSHOT_LIVE)

    store_snapshot(session, DAY, overview("1.0000", 40, 59), SNAPSHOT_BACKFILL)

    stored = _stored(session)
    assert stored.total_value == Decimal("10948918.0777")
    assert stored.source == SNAPSHOT_LIVE


def test_equal_coverage_leaves_the_live_snapshot_alone(session):
    """Равное покрытие — не повод переписывать: живой снимок снят по состоянию,
    которое система тогда видела, и это более прямое свидетельство."""
    store_snapshot(session, DAY, overview("10948918.0777", 57, 59), SNAPSHOT_LIVE)

    store_snapshot(session, DAY, overview("1.0000", 57, 59), SNAPSHOT_BACKFILL)

    assert _stored(session).total_value == Decimal("10948918.0777")


def test_a_run_can_always_refresh_its_own_snapshot(session):
    """Повторный прогон того же рода обязан обновлять свою же точку: иначе
    пересчёт после починки сопоставления символа не даст ничего."""
    store_snapshot(session, DAY, overview("1.0000", 57, 59), SNAPSHOT_BACKFILL)

    store_snapshot(session, DAY, overview("2.0000", 57, 59), SNAPSHOT_BACKFILL)

    assert _stored(session).total_value == Decimal("2.0000")


def _buy(session, account, instrument, day: str, quantity: str, price: str, external_id: str):
    session.add(Transaction(
        account_id=account.id, instrument_id=instrument.id, op_type=OperationType.BUY,
        executed_at=datetime.fromisoformat(day), quantity=Decimal(quantity),
        price=Decimal(price), amount=Decimal(price) * -Decimal(quantity), currency="RUB",
        fee=Decimal("0"), external_id=external_id, source="tbank",
        dedup_key=f"k-{external_id}", payload={},
    ))
    session.flush()


def test_backfill_builds_a_point_per_day(session, account):
    instrument = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                            currency="RUB", kind="share", issuer="Русагро")
    session.add(instrument)
    session.flush()
    _buy(session, account, instrument, "2024-06-03T10:00:00+00:00", "10", "100", "a")
    for day, close in [(date(2024, 6, 3), "100"), (date(2024, 6, 4), "110")]:
        session.add(Price(instrument_id=instrument.id, on_date=day, close=Decimal(close),
                          currency="RUB", source="moex"))
    session.flush()

    written = backfill_snapshots(session, date(2024, 6, 3), date(2024, 6, 4))

    assert written == 2
    points = session.query(DailySnapshot).order_by(DailySnapshot.on_date).all()
    assert [(p.on_date, p.total_value, p.source) for p in points] == [
        (date(2024, 6, 3), Decimal("1000.0000"), SNAPSHOT_BACKFILL),
        (date(2024, 6, 4), Decimal("1100.0000"), SNAPSHOT_BACKFILL),
    ]
    assert points[0].valued_positions == 1 and points[0].positions_total == 1


def test_backfill_records_coverage_when_a_price_is_missing(session, account):
    """День без цены — не день без портфеля: точка обязана появиться и назвать,
    чего в ней не хватило."""
    instrument = Instrument(isin="US87238U2033", ticker="US87238U2033", secid="US87238U2033",
                            currency="USD", kind="share", issuer="ТКС Холдинг")
    session.add(instrument)
    session.flush()
    _buy(session, account, instrument, "2024-06-03T10:00:00+00:00", "10", "100", "a")

    backfill_snapshots(session, date(2024, 6, 3), date(2024, 6, 3))

    point = session.query(DailySnapshot).one()
    assert (point.valued_positions, point.positions_total) == (0, 1)
    assert point.unpriced == ["ТКС Холдинг"]


def test_first_operation_date_is_the_start_of_history(session, account):
    instrument = Instrument(isin="RU000A0JQUZ6", ticker="AGRO", secid="AGRO",
                            currency="RUB", kind="share")
    session.add(instrument)
    session.flush()
    _buy(session, account, instrument, "2020-07-16T10:00:00+00:00", "1", "100", "a")
    _buy(session, account, instrument, "2024-06-03T10:00:00+00:00", "1", "100", "b")

    assert first_operation_date(session) == date(2020, 7, 16)
