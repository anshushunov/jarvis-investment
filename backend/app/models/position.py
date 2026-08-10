from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Position(Base):
    __tablename__ = "position"
    __table_args__ = (
        UniqueConstraint("account_id", "instrument_id", name="uq_position_account_instrument"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    average_price: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    # Известна ли себестоимость всех партий позиции. Ложь у позиции, куда
    # бумаги пришли переводом: брокер себестоимости при переводе не сообщает.
    # По такой позиции не показываются ни средняя цена, ни доходность.
    cost_basis_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
