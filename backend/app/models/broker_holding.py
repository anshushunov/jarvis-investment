from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BrokerHolding(Base):
    """Снимок бумаг счёта у брокера: сколько есть и сколько из этого
    заблокировано.

    Раньше снимок брокера жил только внутри одного вызова сверки и нигде не
    сохранялся. Хранить его нужно по двум причинам: заблокированная часть
    известна только брокеру и должна быть видна на экране, а сама сверка
    перестаёт зависеть от того, дошёл ли до неё сетевой вызов в этот раз.

    `instrument_id` необязателен: у брокера может лежать бумага, которой нет в
    нашем справочнике — например, появившаяся в результате конвертации, о
    которой в журнале нет ни одной операции. Терять такую строку нельзя, именно
    она объясняет расхождение.
    """

    __tablename__ = "broker_holding"
    __table_args__ = (
        UniqueConstraint("account_id", "isin", name="uq_broker_holding_account_isin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"), index=True)
    isin: Mapped[str] = mapped_column(String(12), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    # Часть quantity, заблокированная брокером или биржей. Не добавка к нему.
    # Без дефолта: store_holdings — единственный писатель этой таблицы и
    # всегда передаёт blocked явно (у BrokerPosition.blocked своё дефолтное
    # значение Decimal("0")), голый питоновский 0 здесь никогда не сработал бы
    # и только маскировал бы пропущенный аргумент в новом коде.
    blocked: Mapped[Decimal] = mapped_column(Numeric(20, 8))
    # Только время создания строки: снимок не обновляется на месте, он
    # целиком заменяется в store_holdings через delete + insert, поэтому
    # UPDATE по этой таблице не издаётся никогда и onupdate был бы мёртвым
    # кодом.
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
