from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DailySnapshot(Base):
    __tablename__ = "daily_snapshot"
    __table_args__ = (UniqueConstraint("on_date", name="uq_snapshot_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    by_asset_class: Mapped[dict] = mapped_column(JSONB, default=dict)
    by_account: Mapped[dict] = mapped_column(JSONB, default=dict)
