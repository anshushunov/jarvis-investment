"""Поиск бумаги по строке — для ассистента и для всех, кому нужно превратить
«Озон» в идентификатор.

Живёт в справочнике, а не в инструменте: правило «что считать совпадением»
одно на проект, и панель чата фазы 5b позовёт его напрямую.
"""

from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Instrument, Position

# Точные совпадения тикера, ISIN или биржевого кода берутся отдельным запросом
# (без LIMIT), чтобы не потеряться среди сотен частичных совпадений.
# Затем читаются частичные совпадения с FETCH_LIMIT, и результаты мержатся
# по instrument_id с приоритетом точных совпадений.
FETCH_LIMIT = 50


@dataclass(frozen=True)
class Candidate:
    instrument: Instrument
    # Есть ли открытая позиция по бумаге хотя бы на одном счёте.
    held: bool
    # Точное совпадение тикера, ISIN или биржевого кода — такие идут первыми.
    exact: bool


def search_instruments(session: Session, query: str, limit: int = 10) -> list[Candidate]:
    text = query.strip()
    if not text:
        return []

    upper = text.upper()
    held = set(session.execute(
        select(Position.instrument_id).where(Position.quantity != 0)
    ).scalars())

    # Точные совпадения тикера, ISIN или биржевого кода (без LIMIT).
    exact_rows = session.execute(
        select(Instrument).where(or_(
            func.upper(Instrument.ticker) == upper,
            func.upper(Instrument.isin) == upper,
            func.upper(Instrument.secid) == upper,
        ))
    ).scalars().all()

    # Частичные совпадения (ILIKE во всех полях, с LIMIT). Сортировка задаёт,
    # какая полсотня попадёт под лимит, — иначе выбор недетерминирован.
    pattern = f"%{text}%"
    partial_rows = session.execute(
        select(Instrument).where(or_(
            Instrument.ticker.ilike(pattern), Instrument.secid.ilike(pattern),
            Instrument.isin.ilike(pattern), Instrument.issuer.ilike(pattern),
        )).order_by(Instrument.issuer, Instrument.id).limit(FETCH_LIMIT)
    ).scalars().all()

    # Мерж: exact_rows + partial_rows, по instrument_id, с приоритетом exact —
    # точные совпадения пишутся в by_id вторыми и перезатирают частичные,
    # поэтому флаг exact у мержа выставляется верно.
    by_id = {}
    for row in partial_rows:
        by_id[row.id] = (row, False)
    for row in exact_rows:
        by_id[row.id] = (row, True)

    candidates = [
        Candidate(
            instrument=row, held=row.id in held,
            exact=is_exact,
        )
        for row, is_exact in by_id.values()
    ]
    # Точные раньше частичных, открытые раньше проданных, дальше по имени.
    # Порядок задан здесь, а не у читателя: у выдачи несколько потребителей.
    candidates.sort(key=lambda candidate: (
        not candidate.exact, not candidate.held,
        (candidate.instrument.issuer or candidate.instrument.ticker or "").lower(),
    ))
    return candidates[:limit]
