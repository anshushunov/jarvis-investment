from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FxRate(Base):
    """Курс одной единицы валюты к рублю на дату.

    Источник не обязательно ЦБ: золото (`XAU`) приходит с MOEX, потому что в
    XML_daily драгоценных металлов нет, а в денежных остатках Т-Банка золото
    лежит наравне с валютами.
    """

    __tablename__ = "fx_rate"
    __table_args__ = (UniqueConstraint("currency", "on_date", name="uq_fx_rate_currency_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    on_date: Mapped[date] = mapped_column(Date, index=True)
    # Восемь знаков: у валют с номиналом в сто и тысячу четырёх не хватает.
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    source: Mapped[str] = mapped_column(String(16), default="cbr")
