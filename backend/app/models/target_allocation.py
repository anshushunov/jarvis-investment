from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TargetAllocation(Base):
    """Целевая доля — первая настройка, живущая в базе (дизайн 5a, раздел 4.4).

    Строка задаёт долю от всего портфеля либо на класс активов, либо на бумагу:
    ровно один из двух ключей заполнен, и это проверяет сама база. Смешивать
    внутри ветки нельзя (цель на Сбер при цели на акции считала бы один рубль
    дважды) — это правило про пару строк, а не про одну, и живёт оно в
    app/allocation/service.py.
    """

    __tablename__ = "target_allocation"
    __table_args__ = (
        # Уникальность каждого ключа по отдельности. NULL в уникальном
        # ограничении Postgres с NULL не конфликтует, поэтому две цели на класс
        # (у обеих instrument_id пуст) сравниваются только по asset_class, и
        # наоборот. Составной ключ из двух колонок не сработал бы: пары
        # (NULL, 5) и (NULL, 5) он счёл бы разными.
        UniqueConstraint("asset_class", name="uq_target_allocation_asset_class"),
        UniqueConstraint("instrument_id", name="uq_target_allocation_instrument"),
        CheckConstraint("(asset_class IS NULL) <> (instrument_id IS NULL)",
                        name="ck_target_allocation_one_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_class: Mapped[str | None] = mapped_column(String(32))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    # Доля от 0 до 1 с точностью до сотой процента: 0.6000 — это 60 %.
    share: Mapped[Decimal] = mapped_column(Numeric(7, 4))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
