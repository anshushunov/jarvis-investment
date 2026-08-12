from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Происхождение снимка. Живой снят в свой день по состоянию, которое система
# тогда видела; достроенный восстановлен задним числом по журналу и истории
# котировок. Это разные утверждения о мире, и правило перезаписи опирается на
# различие (см. app/snapshots/service.py:store_snapshot).
SNAPSHOT_LIVE = "live"
SNAPSHOT_BACKFILL = "backfill"


class DailySnapshot(Base):
    __tablename__ = "daily_snapshot"
    __table_args__ = (UniqueConstraint("on_date", name="uq_snapshot_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    by_asset_class: Mapped[dict] = mapped_column(JSONB, default=dict)
    by_account: Mapped[dict] = mapped_column(JSONB, default=dict)
    source: Mapped[str] = mapped_column(String(16), default=SNAPSHOT_LIVE,
                                        server_default=SNAPSHOT_LIVE)
    # NULL — покрытие неизвестно, и это не то же самое, что ноль: у снимков,
    # снятых до фазы 2c, его никто не считал.
    positions_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valued_positions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Бумаги без цены на эту дату, поимённо.
    unpriced: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
