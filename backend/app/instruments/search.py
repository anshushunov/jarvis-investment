"""Поиск бумаги по строке — для ассистента и для всех, кому нужно превратить
«Озон» в идентификатор.

Живёт в справочнике, а не в инструменте: правило «что считать совпадением»
одно на проект, и панель чата фазы 5b позовёт его напрямую.
"""

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Instrument, Position

# Кандидатов читается больше, чем отдаётся: ранжирование — в Python, и точное
# совпадение тикера обязано попасть в ответ даже при сотне частичных.
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
    pattern = f"%{text}%"
    rows = session.execute(
        select(Instrument).where(or_(
            Instrument.ticker.ilike(pattern), Instrument.secid.ilike(pattern),
            Instrument.isin.ilike(pattern), Instrument.issuer.ilike(pattern),
        )).limit(FETCH_LIMIT)
    ).scalars().all()
    held = set(session.execute(
        select(Position.instrument_id).where(Position.quantity != 0)
    ).scalars())

    upper = text.upper()
    candidates = [
        Candidate(
            instrument=row, held=row.id in held,
            exact=upper in {(row.ticker or "").upper(), (row.isin or "").upper(),
                            (row.secid or "").upper()},
        )
        for row in rows
    ]
    # Точные раньше частичных, открытые раньше проданных, дальше по имени.
    # Порядок задан здесь, а не у читателя: у выдачи несколько потребителей.
    candidates.sort(key=lambda candidate: (
        not candidate.exact, not candidate.held,
        (candidate.instrument.issuer or candidate.instrument.ticker or "").lower(),
    ))
    return candidates[:limit]
