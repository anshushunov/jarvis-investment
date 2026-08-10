from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Price(Base):
    __tablename__ = "price"
    # Источник входит в ключ: биржевая и брокерская цена за один день — две
    # разные величины, и затирать одну другой значит отдать выбор между ними
    # порядку записи.
    __table_args__ = (
        UniqueConstraint("instrument_id", "on_date", "source", name="uq_price_instrument_date_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.id"), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    # Валюта цены — не то же самое, что валюта инструмента: замещающая
    # облигация номинирована в юанях, а в справочнике брокера числится
    # рублёвой, потому что расчёты по ней рублёвые.
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    source: Mapped[str] = mapped_column(String(16), default="moex")
