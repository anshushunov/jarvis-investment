from datetime import date
from decimal import Decimal

from app.analytics.service import Overview
from app.models import SNAPSHOT_BACKFILL, SNAPSHOT_LIVE, DailySnapshot
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
