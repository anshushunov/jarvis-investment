"""Инструмент find_instrument: превратить «Озон» в идентификатор.

Нужен не для удобства: без него модель начнёт угадывать тикеры и однажды
спутает T (AT&T) с T (Т-Технологии).
"""

from typing import Annotated

from pydantic import Field
from sqlalchemy.orm import Session

from app.ai import serialize as s
from app.analytics.service import asset_class_of
from app.instruments.search import search_instruments

NOTE_EMPTY = "Ничего не найдено: проверь написание или спроси по ISIN."
NOTE_MANY = ("Несколько кандидатов — это разные бумаги, даже с одним тикером (T — и AT&T, и "
             "Т-Технологии): выбирай по названию, валюте и признаку held.")


def find_instrument(
    session: Session,
    query: Annotated[str, Field(description=(
        "Тикер, ISIN, биржевой код или часть названия эмитента: «OZON», «Озон», «RU000A101234»"))],
    limit: Annotated[int, Field(ge=1, le=25, description="Сколько кандидатов вернуть")] = 10,
) -> dict:
    candidates = search_instruments(session, query, limit)
    return {
        "query": query,
        "candidates": [
            {**s.instrument_ref(candidate.instrument),
             "kind": candidate.instrument.kind, "currency": candidate.instrument.currency,
             "asset_class": asset_class_of(candidate.instrument),
             "held": candidate.held, "exact_match": candidate.exact}
            for candidate in candidates
        ],
        "note": NOTE_EMPTY if not candidates else NOTE_MANY if len(candidates) > 1 else None,
    }
