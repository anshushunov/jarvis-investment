from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DDL, DateTime, Enum, ForeignKey, Index, Numeric, String, UniqueConstraint, event, func
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
    # Ввод и вывод бумаг: перевод от другого брокера или между счетами.
    # Количество двигают, себестоимости не несут — брокер её не сообщает.
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"
    # Две стороны корпоративного действия. Порождаются только решением
    # владельца (app/decisions/service.py) и связаны через payload.decision_id:
    # OUT снимает открытые партии, IN раскладывает их на новую бумагу.
    CONVERSION_OUT = "CONVERSION_OUT"
    CONVERSION_IN = "CONVERSION_IN"
    # Ручная поправка количества и корректировка операции, изменённой брокером
    # задним числом. Журнал append-only — правок нет, есть только новые записи.
    ADJUSTMENT = "ADJUSTMENT"


# Ключ, под которым корректирующая запись (op_type=ADJUSTMENT, см. ниже) хранит
# в payload id исправляемой ею записи. По аналогии с DECISION_PAYLOAD_KEY в
# app/models/ledger_decision.py — та же причина: строка задаётся в одном месте
# (app/ledger/service.py, _correction_for) и должна читаться оттуда же, а не
# дублироваться литералом там, где её понадобится найти.
CORRECTS_TRANSACTION_ID_PAYLOAD_KEY = "corrects_transaction_id"


class Transaction(Base):
    __tablename__ = "transaction"
    __table_args__ = (
        # Область действия — счёт, а не весь источник: T-Invest переиспользует один и
        # тот же internal id для двух РАЗНЫХ записей на РАЗНЫХ счетах одного владельца
        # (обе стороны перевода между своими счетами делят один "id" — живое
        # подтверждение см. docs/decisions/2026-08-08-ledger-external-id-per-account.md). Ограничение только на
        # (source, external_id) без account_id ложно принимало такую пару за дубль и
        # роняло весь батч синхронизации второго счёта.
        UniqueConstraint("account_id", "source", "external_id", name="uq_transaction_source_external"),
        UniqueConstraint("dedup_key", name="uq_transaction_dedup_key"),
        Index("ix_transaction_account_executed", "account_id", "executed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"))
    instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    # Нативный enum PostgreSQL, а не String(24): из строковой колонки значение
    # приходило как str, и `entry.op_type is OperationType.REDEMPTION` молча
    # возвращало ложь — погашение облигаций не закрывало позицию, а юнит-тест
    # на объекте из памяти при этом проходил.
    op_type: Mapped[OperationType] = mapped_column(
        Enum(OperationType, name="operation_type", native_enum=True,
             values_callable=lambda enum: [member.value for member in enum])
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[Decimal] = mapped_column(Numeric(20, 8), default=Decimal("0"))
    price: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4))
    currency: Mapped[str] = mapped_column(String(3))
    fee: Mapped[Decimal] = mapped_column(Numeric(20, 4), default=Decimal("0"))
    external_id: Mapped[str | None] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(32))
    # Без index=True: уникальное ограничение uq_transaction_dedup_key выше уже
    # создаёт индекс по этой колонке, и отдельный index=True давал второй
    # индекс на ту же колонку — лишняя запись на каждой вставке ради ровно тех
    # же возможностей поиска.
    dedup_key: Mapped[str] = mapped_column(String(64))
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
