from datetime import date

from sqlalchemy import Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (UniqueConstraint("broker", "external_id", name="uq_account_broker_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    broker: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    opened_at: Mapped[date | None] = mapped_column(Date)
