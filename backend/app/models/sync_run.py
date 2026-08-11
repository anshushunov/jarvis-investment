from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SyncRun(Base):
    __tablename__ = "sync_run"

    id: Mapped[int] = mapped_column(primary_key=True)
    broker: Mapped[str] = mapped_column(String(16), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("account.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    mismatches: Mapped[int] = mapped_column(Integer, default=0)
    # Операции, которые брокер переписал задним числом: на разницу записана
    # корректирующая запись (см. AppendResult в app/ledger/service.py). Должно
    # быть редкостью — частый случай доисполняющейся заявки закрыт окном
    # STILL_FILLING_WINDOW в коннекторе. Стабильно ненулевой счётчик означает,
    # что обход перестал работать.
    corrected: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
