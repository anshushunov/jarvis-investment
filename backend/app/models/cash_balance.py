from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CashBalance(Base):
    """Денежный остаток счёта в одной валюте — снимок брокера, не производная
    журнала.

    Журнал остаётся источником истины по позициям, но денег он пока не считает:
    для этого в нём должны быть все до единого движения средств, включая
    пополнения и выводы, а их полноту мы не проверяли. Пока остаток берётся у
    брокера как есть — так же, как берётся его снимок позиций для сверки.
    """

    __tablename__ = "cash_balance"
    __table_args__ = (
        UniqueConstraint("account_id", "currency", name="uq_cash_balance_account_currency"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    # Часть остатка, недоступная к распоряжению. Входит в amount, не прибавляется.
    blocked: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
