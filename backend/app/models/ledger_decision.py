from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DecisionKind(StrEnum):
    # Корпоративное действие: одна бумага превратилась в другую.
    CONVERSION = "CONVERSION"
    # Ручная поправка количества, когда пары нет и владелец знает причину.
    ADJUSTMENT = "ADJUSTMENT"
    # Расхождение остаётся, но объяснено и больше не требует внимания.
    ACCEPTED_AS_IS = "ACCEPTED_AS_IS"


class DecisionStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    # Гипотеза отклонена владельцем. Записей журнала не порождает; нужна
    # только чтобы не предлагать её снова после каждой синхронизации.
    REJECTED = "REJECTED"
    # Решение отменено более поздним (см. reverts_id у отменяющего).
    REVERTED = "REVERTED"


class LedgerDecision(Base):
    """Решение владельца по расхождению журнала со снимком брокера.

    Хранятся только принятые решения. Гипотезы конвертации в базу не пишутся —
    они пересчитываются из таблицы reconciliation при каждом запросе
    (app/decisions/suggestions.py). Отклонённая гипотеза оставляет здесь строку
    со статусом REJECTED: это единственный способ не предлагать её заново после
    каждой синхронизации.

    Подтверждённое решение порождает записи в журнале операций с
    source='manual' и payload.decision_id, указывающим сюда. Отмена решения
    ничего не удаляет: журнал append-only, поэтому создаётся новое решение с
    reverts_id, порождающее зеркальные записи.
    """

    __tablename__ = "ledger_decision"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id"), index=True)
    kind: Mapped[DecisionKind] = mapped_column(
        Enum(DecisionKind, name="decision_kind", native_enum=True,
             values_callable=lambda enum: [member.value for member in enum])
    )
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, name="decision_status", native_enum=True,
             values_callable=lambda enum: [member.value for member in enum])
    )
    from_instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    from_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    to_instrument_id: Mapped[int | None] = mapped_column(ForeignKey("instrument.id"))
    to_quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    # Себестоимость, если владелец её знает: у перевода извне брокер её не
    # сообщает, но владелец мог посмотреть отчёт прежнего брокера.
    cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    # Дата самого события, а не дата решения: конвертация случилась когда-то в
    # прошлом, и порождённые записи должны встать в журнал на своё место.
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Пояснение обязательно у любого вида решения. Через год «почему тут 1012»
    # не восстановит никто, а решение продолжит влиять на налоговую базу.
    note: Mapped[str] = mapped_column(Text, nullable=False)
    # На чём система построила гипотезу: чтобы решение можно было перечитать и
    # понять, что видел владелец в момент подтверждения.
    proposed: Mapped[dict] = mapped_column(JSONB, default=dict)
    reverts_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_decision.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
