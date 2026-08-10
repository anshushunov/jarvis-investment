from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Instrument(Base):
    __tablename__ = "instrument"

    id: Mapped[int] = mapped_column(primary_key=True)
    isin: Mapped[str | None] = mapped_column(String(12), unique=True, index=True)
    ticker: Mapped[str | None] = mapped_column(String(32), index=True)
    secid: Mapped[str | None] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    issuer: Mapped[str | None] = mapped_column(String(255))
    sector: Mapped[str | None] = mapped_column(String(64))
    asset_class: Mapped[str | None] = mapped_column(String(32))
    maturity_date: Mapped[date | None] = mapped_column(Date)
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    # Бумагой нельзя распорядиться: брокер не даёт ни купить, ни продать.
    # Так выглядят все иностранные бумаги портфеля после 2022 года, а также
    # выпуски, снятые с торгов после конвертации (AGRO, FIVE). Это не то же
    # самое, что заблокированное количество в broker_holding: там блокировка
    # конкретных бумаг на конкретном счёте, здесь — свойство самой бумаги.
    trading_restricted: Mapped[bool] = mapped_column(Boolean, default=False,
                                                     server_default=text("false"))
