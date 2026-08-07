from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DDL, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, event, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class OperationType(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    COUPON = "COUPON"
    FEE = "FEE"
    TAX = "TAX"
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    REDEMPTION = "REDEMPTION"
    AMORTIZATION = "AMORTIZATION"
    VARIATION_MARGIN = "VARIATION_MARGIN"
    OTHER = "OTHER"


class Transaction(Base):
    __tablename__ = "transaction"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_transaction_source_external"),
        UniqueConstraint("dedup_key", name="uq_transaction_dedup_key"),
        Index("ix_transaction_account_executed", "account_id", "executed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    op_type: Mapped[OperationType] = mapped_column(String(24))
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    external_id: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32))
    dedup_key: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    instrument = relationship("Instrument", lazy="joined")


# Журнал операций — append-only: UPDATE и DELETE запрещены триггером БД, исправления
# вносятся корректирующими операциями. Этот же SQL продублирован буквально в
# alembic/versions/0001_initial.py — там он владеет схемой в проде. Дубль здесь нужен
# потому, что тестовая схема собирается через Base.metadata.create_all и миграцию не
# видит. Меняешь один текст — обязательно правь оба.
_CREATE_APPEND_ONLY_FUNCTION_DDL = DDL(
    """
    CREATE FUNCTION transaction_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION 'Журнал операций неизменяем: UPDATE и DELETE запрещены, исправления вносятся корректирующими операциями';
    END;
    $$ LANGUAGE plpgsql;
    """
)
_CREATE_APPEND_ONLY_TRIGGER_DDL = DDL(
    """
    CREATE TRIGGER transaction_append_only_trigger
    BEFORE UPDATE OR DELETE ON transaction
    FOR EACH ROW EXECUTE FUNCTION transaction_append_only();
    """
)

event.listen(Transaction.__table__, "after_create", _CREATE_APPEND_ONLY_FUNCTION_DDL)
event.listen(Transaction.__table__, "after_create", _CREATE_APPEND_ONLY_TRIGGER_DDL)
